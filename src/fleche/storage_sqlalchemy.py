from typing import Iterable, Any, List

from sqlalchemy import (
    create_engine,
    Column,
    String,
    Integer,
    ForeignKey,
    UniqueConstraint,
    select,
    and_,
)
from sqlalchemy.engine import Engine
from sqlalchemy import event
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session
from sqlalchemy.types import JSON

from .storage import CallStorage, AmbiguousDigestError
from .call import Call
from .digest import digest, Digest, DIGEST_LENGTH

Base = declarative_base()

class CallModel(Base):
    __tablename__ = "calls"
    # Full-length digest for the call key
    key = Column(String(DIGEST_LENGTH), primary_key=True)
    name = Column(String, nullable=False)
    module = Column(String, nullable=True)
    version = Column(Integer, nullable=True)
    # result is also a digest (or None if not yet computed)
    result = Column(String(DIGEST_LENGTH), nullable=True)

    # Children in long-form normalized tables
    args = relationship(
        "ArgModel",
        back_populates="call",
        cascade="all, delete-orphan",
        order_by="ArgModel.position",
    )
    kwargs = relationship(
        "KwargModel",
        back_populates="call",
        cascade="all, delete-orphan",
    )

class ArgModel(Base):
    __tablename__ = "args"
    id = Column(Integer, primary_key=True, autoincrement=True)
    call_key = Column(String(DIGEST_LENGTH), ForeignKey("calls.key", ondelete="CASCADE"), nullable=False)
    position = Column(Integer, nullable=False)
    value = Column(String(DIGEST_LENGTH), nullable=False)

    __table_args__ = (
        UniqueConstraint("call_key", "position", name="uq_args_call_pos"),
    )

    call = relationship("CallModel", back_populates="args")

class KwargModel(Base):
    __tablename__ = "kwargs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    call_key = Column(String(DIGEST_LENGTH), ForeignKey("calls.key", ondelete="CASCADE"), nullable=False)
    kwarg_key = Column(String, nullable=False)
    value = Column(String(DIGEST_LENGTH), nullable=False)

    __table_args__ = (
        UniqueConstraint("call_key", "kwarg_key", name="uq_kwargs_call_key"),
    )

    call = relationship("CallModel", back_populates="kwargs")


class MetaModel(Base):
    __tablename__ = "metadata"
    id = Column(Integer, primary_key=True, autoincrement=True)
    call_key = Column(String(DIGEST_LENGTH), ForeignKey("calls.key", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False, index=True)
    data = Column(JSON, nullable=False)

    __table_args__ = (
        UniqueConstraint("call_key", "name", name="uq_metadata_call_name"),
    )

def _coerce_sqlite_url(path_or_url: str | None) -> str:
    """Return a valid SQLAlchemy URL.

    - None -> sqlite in-memory
    - If already a URL (startswith "sqlite:") use as-is
    - Else treat as filesystem path
    """
    if path_or_url is None:
        return "sqlite:///:memory:"
    if isinstance(path_or_url, str) and path_or_url.startswith("sqlite:"):
        return path_or_url
    # treat as filesystem path
    import os
    abs_path = os.path.abspath(str(path_or_url))
    return f"sqlite:///{abs_path}"


def _enable_sqlite_foreign_keys(engine: Engine) -> None:
    # Ensure ON DELETE CASCADE works if used and protect referential integrity
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: D401
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


class Sql(CallStorage):
    """SQLAlchemy-backed CallStorage.

    Notes:
    - args, kwargs, and result are stored as digests (strings), one row per element (normalized long-form).
    - metadata is stored in a single JSON table keyed by (call_key, name).
    """

    def __init__(self, path_or_url: str | None = None, echo: bool = False):
        url = _coerce_sqlite_url(path_or_url)
        self.engine = create_engine(url, echo=echo, future=True)
        _enable_sqlite_foreign_keys(self.engine)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    def save(self, value: Call, key: Digest | None = None) -> str:
        """Persist a Call in normalized long-form tables.

        Args:
            value: Call instance. Its args/kwargs/result are expected to be Digests (strings) already.
            key: Optional digest override; if None, computed from the Call.

        Returns:
            The call's digest key.
        """
        if key is None:
            key = digest(value)

        session: Session = self.Session()
        try:
            existing = session.execute(select(CallModel).where(CallModel.key == key)).scalar_one_or_none()
            if existing is not None:
                return key

            call_model = CallModel(
                key=str(key),
                name=value.name,
                module=value.module,
                version=value.version,
                result=value.result if value.result is None else str(value.result),
            )
            session.add(call_model)

            for i, arg_val in enumerate(value.args):
                session.add(ArgModel(call_key=str(key), position=i, value=str(arg_val)))

            for k, v in value.kwargs.items():
                session.add(KwargModel(call_key=str(key), kwarg_key=str(k), value=str(v)))

            # Persist metadata (JSON). By design, metadata is created together with the call
            # and not updated in later saves, so we simply insert rows here.
            if value.metadata:
                session.add_all(
                    [MetaModel(call_key=str(key), name=name, data=data) for name, data in value.metadata.items()]
                )
            session.commit()
            return str(key)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def load(self, key: str) -> Call:
        """Load a Call by its key (supports short digests via expand())."""
        if len(key) < DIGEST_LENGTH:
            key = self.expand(key)

        session: Session = self.Session()
        try:
            call_model = session.execute(select(CallModel).where(CallModel.key == key)).scalar_one_or_none()
            if call_model is None:
                raise KeyError(key)

            # Re-wrap stored digests as Digest so Cache can hydrate values on load
            args = tuple(Digest(arg.value) for arg in call_model.args)
            kwargs = {kw.kwarg_key: Digest(kw.value) for kw in call_model.kwargs}

            # load metadata rows inline (single query)
            meta_rows = session.execute(select(MetaModel).where(MetaModel.call_key == key)).scalars().all()
            call = Call(
                name=call_model.name,
                args=args,
                kwargs=kwargs,
                metadata={row.name: (row.data or {}) for row in meta_rows},
                module=call_model.module,
                version=call_model.version,
                result=Digest(call_model.result) if call_model.result is not None else None,
            )
            return call
        finally:
            session.close()

    def list(self) -> Iterable[str]:
        session: Session = self.Session()
        try:
            return [row[0] for row in session.execute(select(CallModel.key))]
        finally:
            session.close()

    def expand(self, key: Digest | str) -> Digest:
        """Efficiently expand a short digest using a database query.

        Queries for at most two matching keys ordered lexicographically to
        detect ambiguity without scanning the entire table.
        """
        # If already full length, return as-is
        if len(key) >= DIGEST_LENGTH:
            return Digest(str(key))
        if len(key) < 4:
            raise KeyError(key)

        prefix = str(key)
        session: Session = self.Session()
        try:
            rows = session.execute(
                select(CallModel.key)
                .where(CallModel.key.like(f"{prefix}%"))
                .order_by(CallModel.key)
                .limit(2)
            ).all()
        finally:
            session.close()

        if not rows:
            raise KeyError(key)

        if len(rows) == 1:
            return Digest(rows[0][0])

        m1, m2 = rows[0][0], rows[1][0]
        # find divergence point
        for i, (c1, c2) in enumerate(zip(m1, m2)):
            if c1 != c2:
                break
        else:
            i = min(len(m1), len(m2))
        raise AmbiguousDigestError(f"Short digest {key} is ambiguous; need at least {i+1} characters.")

    def evict(self, key: str) -> None:
        """Remove a call and its args/kwargs from storage.

        Deletion is performed via ORM to leverage relationship cascade.
        """
        if len(key) < DIGEST_LENGTH:
            key = self.expand(key)

        session: Session = self.Session()
        try:
            instance = session.get(CallModel, key)
            if instance is None:
                # no-op if not present
                return
            session.delete(instance)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # -----------------------------
    # Metadata querying
    # -----------------------------

    def find_by_metadata(self, name: str | None = None, **filters: Any) -> List[str]:
        """Find call keys by metadata content using JSON-aware SQL when possible.

        Falls back to a portable client-side filter if the backend/dialect
        doesn't support the required JSON operations.
        """
        session: Session = self.Session()
        try:
            # Attempt server-side JSON filtering for supported primitive types
            # using the appropriate JSON accessors.
            supported = (str, bool, int, float)
            use_server_side = all(isinstance(v, supported) for v in filters.values())
            if use_server_side:
                conditions = []
                if name is not None:
                    conditions.append(MetaModel.name == name)
                for k, v in filters.items():
                    # Handle bool before int since bool is a subclass of int in Python
                    if isinstance(v, bool):
                        conditions.append(MetaModel.data[k].as_boolean() == v)
                    elif isinstance(v, int):
                        conditions.append(MetaModel.data[k].as_integer() == v)
                    elif isinstance(v, float):
                        conditions.append(MetaModel.data[k].as_float() == v)
                    else:  # str
                        conditions.append(MetaModel.data[k].as_string() == v)

                if conditions:
                    stmt = (
                        select(MetaModel.call_key)
                        .where(and_(*conditions))
                        .distinct()
                    )
                    try:
                        result = [row[0] for row in session.execute(stmt).all()]
                        return sorted(set(result))
                    except Exception:
                        # Fall back to client-side if dialect can't handle JSON ops
                        pass

            # Fallback: client-side filtering
            stmt = select(MetaModel.call_key, MetaModel.name, MetaModel.data)
            if name is not None:
                stmt = stmt.where(MetaModel.name == name)
            rows = session.execute(stmt).all()

            def matches(data: dict[str, Any]) -> bool:
                for kk, vv in filters.items():
                    if kk not in data or data[kk] != vv:
                        return False
                return True

            keys: set[str] = set()
            for call_key, _mname, mdata in rows:
                if matches(mdata or {}):
                    keys.add(call_key)
            return sorted(keys)
        finally:
            session.close()
