from typing import Iterable, Any, List
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
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session
from sqlalchemy.types import JSON

from .base import CallStorage, AmbiguousDigestError
from ..call import Call
from ..digest import Digest, DIGEST_LENGTH

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


def _enable_sqlite_foreign_keys(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
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

    def _save(self, value: Call, key: Digest) -> str:
        session: Session = self.Session()
        try:
            existing = session.get(CallModel, str(key))
            if existing is not None:
                session.delete(existing)
                session.flush()

            call_model = CallModel(
                key=str(key),
                name=value.name,
                module=value.module,
                version=value.version,
                result=value.result if value.result is None else str(value.result),
            )
            session.add(call_model)

            for i, (k, v) in enumerate(value.arguments.items()):
                session.add(
                    ArgumentModel(call_key=str(key), position=i, name=str(k), value=str(v))
                )

            if value.metadata:
                session.add_all(
                    [
                        MetaModel(call_key=str(key), name=name, data=data)
                        for name, data in value.metadata.items()
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

    def list(self) -> Iterable[str]:
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

    def find_by_metadata(self, name: str | None = None, **filters: Any) -> List[str]:
        session: Session = self.Session()
        try:
            supported = (str, bool, int, float)
            use_server_side = all(isinstance(v, supported) for v in filters.values())
            if use_server_side:
                conditions = []
                if name is not None:
                    conditions.append(MetaModel.name == name)
                for k, v in filters.items():
                    if isinstance(v, bool):
                        conditions.append(MetaModel.data[k].as_boolean() == v)
                    elif isinstance(v, int):
                        conditions.append(MetaModel.data[k].as_integer() == v)
                    elif isinstance(v, float):
                        conditions.append(MetaModel.data[k].as_float() == v)
                    else:
                        conditions.append(MetaModel.data[k].as_string() == v)

                if conditions:
                    stmt = (
                        select(MetaModel.call_key).where(and_(*conditions)).distinct()
                    )
                    try:
                        result = [Digest(row[0]) for row in session.execute(stmt).all()]
                        # Ensure uniqueness and stable order
                        return sorted(set(result))
                    except Exception:
                        pass

            stmt = select(MetaModel.call_key, MetaModel.name, MetaModel.data)
            if name is not None:
                stmt = stmt.where(MetaModel.name == name)
            rows = session.execute(stmt).all()

            def matches(data: dict[str, Any]) -> bool:
                for kk, vv in filters.items():
                    if kk not in data or data[kk] != vv:
                        return False
                return True

            keys: set[Digest] = set()
            for call_key, _mname, mdata in rows:
                if matches(mdata or {}):
                    keys.add(Digest(call_key))
            return sorted(keys)
        finally:
            session.close()
