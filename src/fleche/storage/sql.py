from typing import Iterable, Any
from pathlib import Path

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
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session, aliased
from sqlalchemy.types import JSON

from .base import CallStorage, AmbiguousDigestError
from ..call import Call
from ..digest import Digest, DIGEST_LENGTH, digest

Base = declarative_base()


class CallModel(Base):
    __tablename__ = "calls"
    key = Column(String(DIGEST_LENGTH), primary_key=True)
    name = Column(String, nullable=False)
    module = Column(String, nullable=True)
    version = Column(Integer, nullable=True)
    result = Column(String(DIGEST_LENGTH), nullable=True)

    arguments = relationship(
        "ArgumentModel",
        back_populates="call",
        cascade="all, delete-orphan",
        order_by="ArgumentModel.position",
    )


class ArgumentModel(Base):
    __tablename__ = "arguments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    call_key = Column(
        String(DIGEST_LENGTH),
        ForeignKey("calls.key", ondelete="CASCADE"),
        nullable=False,
    )
    position = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    value = Column(String(DIGEST_LENGTH), nullable=False)

    __table_args__ = (
        UniqueConstraint("call_key", "name", name="uq_arguments_call_name"),
    )

    call = relationship("CallModel", back_populates="arguments")


class MetaModel(Base):
    __tablename__ = "metadata"
    id = Column(Integer, primary_key=True, autoincrement=True)
    call_key = Column(
        String(DIGEST_LENGTH),
        ForeignKey("calls.key", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String, nullable=False, index=True)
    data = Column(JSON, nullable=False)

    __table_args__ = (
        UniqueConstraint("call_key", "name", name="uq_metadata_call_name"),
    )


def _coerce_sqlite_url(path_or_url: str | None) -> str:
    if path_or_url is None:
        return "sqlite:///:memory:"

    if isinstance(path_or_url, str) and path_or_url.startswith("sqlite:"):
        url = path_or_url
    else:
        abs_path = Path(str(path_or_url)).absolute()
        url = f"sqlite:///{abs_path}"

    if url.startswith("sqlite:///"):
        db_path = url[len("sqlite:///"):]
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    return url


# Use a constant for the PRAGMA execution to avoid raw string injection risks.
SQLITE_FOREIGN_KEYS_ON = "PRAGMA foreign_keys=ON"


def _enable_sqlite_foreign_keys(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            # We use a static constant string here. We cannot use sqlalchemy.text()
            # because we are operating on a raw DBAPI cursor at the 'connect' event.
            cursor.execute(SQLITE_FOREIGN_KEYS_ON)
        finally:
            cursor.close()


class Sql(CallStorage):
    """SQLAlchemy-backed CallStorage with JSON metadata and DB-backed expand()."""

    def __init__(self, url: str | None = None, echo: bool = False):
        url = _coerce_sqlite_url(url)
        self.engine = create_engine(url, echo=echo, future=True)
        _enable_sqlite_foreign_keys(self.engine)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(
            bind=self.engine, expire_on_commit=False, future=True
        )

    def _save(self, call: Call) -> Digest:
        key = call.to_lookup_key()
        session: Session = self.Session()
        try:
            existing = session.get(CallModel, str(key))
            if existing is not None:
                if self.load(key) == call:
                    return key

                session.delete(existing)
                session.flush()

            call_model = CallModel(
                key=str(key),
                name=call.name,
                module=call.module,
                version=call.version,
                result=call.result if call.result is None else str(call.result),
            )
            session.add(call_model)

            for i, (k, v) in enumerate(call.arguments.items()):
                session.add(
                    ArgumentModel(call_key=str(key), position=i, name=str(k), value=str(v))
                )

            if call.metadata:
                session.add_all(
                    [
                        MetaModel(call_key=str(key), name=name, data=data)
                        for name, data in call.metadata.items()
                    ]
                )
            session.commit()
            # Always return a Digest instance, not a plain str
            return key
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _load(self, key: str) -> Call:
        session: Session = self.Session()
        try:
            call_model = session.execute(
                select(CallModel).where(CallModel.key == key)
            ).scalar_one_or_none()
            if call_model is None:
                raise KeyError(key)

            arguments = {arg.name: Digest(arg.value) for arg in call_model.arguments}

            meta_rows = (
                session.execute(select(MetaModel).where(MetaModel.call_key == key))
                .scalars()
                .all()
            )
            call = Call(
                name=call_model.name,
                arguments=arguments,
                metadata={row.name: (row.data or {}) for row in meta_rows},
                module=call_model.module,
                version=call_model.version,
                result=(
                    Digest(call_model.result) if call_model.result is not None else None
                ),
            )
            return call
        finally:
            session.close()

    def list(self) -> Iterable[Digest]:
        session: Session = self.Session()
        try:
            # Return Digest instances for keys
            return [Digest(row[0]) for row in session.execute(select(CallModel.key))]
        finally:
            session.close()

    def expand(self, key: Digest | str) -> Digest:
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
        for i, (c1, c2) in enumerate(zip(m1, m2)):
            if c1 != c2:
                break
        else:
            i = min(len(m1), len(m2))
        raise AmbiguousDigestError(
            f"Short digest {key} is ambiguous; need at least {i+1} characters."
        )

    def _evict(self, key: str) -> None:
        session: Session = self.Session()
        try:
            instance = session.get(CallModel, key)
            if instance is None:
                return
            session.delete(instance)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def query(self, template: Call) -> Iterable[Call]:
        """Find cached calls matching a template using SQL-side filtering.

        Semantics match CallStorage.query:
        - Fields set to None are wildcards.
        - Arguments and result are compared by digest(template_value) == digest(stored_value).
        - Metadata can be filtered by providing template.metadata as a mapping of
          metadata name -> dict of key/value filters. An empty dict for a given
          name means "presence of that metadata name". Filters with simple types
          (str, bool, int, float) are pushed down to SQL via JSON-extract
          expressions; other types (e.g., lists) or None values fall back to
          client-side checks after loading.

        This method builds a SELECT over calls, joining the arguments table and
        metadata table as needed to reduce candidate rows, then loads the
        resulting calls and performs any remaining client-side validation.

        Args:
            template: A Call used as a template. None-valued fields are wildcards.

        Yields:
            Call: Matching calls including their decoded metadata.
        """
        session: Session = self.Session()
        try:
            def normalize_value(v: Any) -> str:
                """Return the stored form used in SQL for argument/result matching.

                We must match the generic CallStorage.query semantics which compare
                digest(template_value) == digest(stored_call_value).
                In this backend, stored argument/result values are hex-digest strings,
                and digest(Digest(x)) == x. Therefore we should always compare
                Arg.value/CallModel.result to str(digest(template_value)).
                """
                return str(digest(v))

            # Start by selecting the keys from calls that match simple field predicates
            conditions = []
            if template.name is not None:
                conditions.append(CallModel.name == template.name)
            if template.module is not None:
                conditions.append(CallModel.module == template.module)
            if template.version is not None:
                conditions.append(CallModel.version == template.version)
            if template.result is not None:
                # Stored as hex string; normalize template value accordingly
                conditions.append(CallModel.result == normalize_value(template.result))

            stmt = select(CallModel.key).select_from(CallModel)

            # For each argument filter, join an aliased ArgumentModel and constrain name/value
            if template.arguments:
                for k, v in template.arguments.items():
                    Arg = aliased(ArgumentModel)
                    on_clause = and_(
                        Arg.call_key == CallModel.key,
                        Arg.name == str(k),
                    )
                    if v is not None:
                        on_clause = and_(on_clause, Arg.value == normalize_value(v))
                    stmt = stmt.join(Arg, on_clause)

            # Optional: metadata filtering
            server_side_meta = True
            meta_specs: dict[str, dict[str, Any]] | None = template.metadata
            if meta_specs:
                # Determine if all filters are server-side compatible
                for _mname, filters in meta_specs.items():
                    for _k, _v in (filters or {}).items():
                        if _v is None or not isinstance(_v, (str, bool, int, float)):
                            server_side_meta = False
                            break
                    if not server_side_meta:
                        break

                if server_side_meta:
                    # Build joins and conditions per metadata name
                    for mname, filters in meta_specs.items():
                        M = aliased(MetaModel)
                        stmt = stmt.join(M, and_(
                            M.call_key == CallModel.key,
                            M.name == mname,
                        ))
                        for k, v in (filters or {}).items():
                            if isinstance(v, bool):
                                stmt = stmt.where(M.data[k].as_boolean() == v)
                            elif isinstance(v, int):
                                stmt = stmt.where(M.data[k].as_integer() == v)
                            elif isinstance(v, float):
                                stmt = stmt.where(M.data[k].as_float() == v)
                            else:
                                stmt = stmt.where(M.data[k].as_string() == v)

            if conditions:
                stmt = stmt.where(and_(*conditions))

            # Distinct to avoid duplicate keys if multiple argument joins could overlap
            stmt = stmt.distinct()

            keys = [Digest(k) for (k,) in session.execute(stmt).all()]
        finally:
            session.close()

        # Yield loaded calls using existing loader (ensures metadata returned too)
        def meta_matches(call: Call) -> bool:
            specs = template.metadata
            if not specs:
                return True
            for mname, filters in specs.items():
                data = (call.metadata or {}).get(mname)
                if data is None:
                    return False
                for kk, vv in (filters or {}).items():
                    if vv is None:
                        if kk not in data:
                            return False
                    else:
                        if data.get(kk) != vv:
                            return False
            return True

        for k in keys:
            c = self.load(k)
            if meta_matches(c):
                yield c

    # find_by_metadata removed; metadata filtering is supported via query(template)
