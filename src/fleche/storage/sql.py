import contextlib
import json
import logging
import threading
from typing import Iterable, Any, List
from pathlib import Path
from dataclasses import dataclass, field
from .base import Intent, KeyManagement, CallStorage, register_storage
from .thread_safe import PerKeyLockMixin
from ..call import DigestedCall, QueryCall
from ..digest import Digest, DIGEST_LENGTH, digest

from pyiron_snippets.import_alarm import ImportAlarm

logger = logging.getLogger("fleche.storage")

with ImportAlarm(
    "Sql requires 'sqlalchemy' to be installed. "
    "Install it with `pip install fleche[sqlalchemy]`.",
    raise_exception=True,
) as sqlalchemy_alarm:
    from sqlalchemy import (
        create_engine,
        String,
        Integer,
        ForeignKey,
        UniqueConstraint,
        select,
        and_,
        delete,
    )
    from sqlalchemy import event
    from sqlalchemy.orm import (
        declarative_base,
        sessionmaker,
        relationship,
        aliased,
        Mapped,
        mapped_column,
    )
    from sqlalchemy.types import JSON

    Base = declarative_base()

    # MySQL/MariaDB reject ``VARCHAR`` columns without an explicit length; every
    # other dialect we support (sqlite, Postgres) treats unbounded ``String`` as
    # ``TEXT`` and is happy. Use ``with_variant`` so the length is applied only
    # on the MySQL family — keep ``TEXT`` for everyone else. 255 is the MySQL
    # convention for indexable VARCHARs and easily fits Python qualified names
    # and JSON-encoded scalar versions.
    _NAME_LEN = 255
    _Name = String().with_variant(String(_NAME_LEN), "mysql", "mariadb")

    class CallModel(Base):
        __tablename__ = "calls"
        key = mapped_column(String(DIGEST_LENGTH), primary_key=True)
        name: Mapped[str] = mapped_column(_Name, nullable=False)
        module: Mapped[str] = mapped_column(_Name, nullable=True)
        version: Mapped[str] = mapped_column(_Name, nullable=True)
        code_digest: Mapped[str] = mapped_column(String(DIGEST_LENGTH), nullable=True)
        result: Mapped[str] = mapped_column(String(DIGEST_LENGTH), nullable=True)

        arguments = relationship(
            "ArgumentModel",
            back_populates="call",
            cascade="all, delete-orphan",
            order_by="ArgumentModel.position",
        )

    class ArgumentModel(Base):
        __tablename__ = "arguments"
        id = mapped_column(Integer, primary_key=True, autoincrement=True)
        call_key = mapped_column(
            String(DIGEST_LENGTH),
            ForeignKey("calls.key", ondelete="CASCADE"),
            nullable=False,
        )
        position = mapped_column(Integer, nullable=False)
        name = mapped_column(_Name, nullable=False)
        value = mapped_column(String(DIGEST_LENGTH), nullable=False)

        __table_args__ = (
            UniqueConstraint("call_key", "name", name="uq_arguments_call_name"),
        )

        call = relationship("CallModel", back_populates="arguments")

    class MetaModel(Base):
        __tablename__ = "metadata"
        id = mapped_column(Integer, primary_key=True, autoincrement=True)
        call_key = mapped_column(
            String(DIGEST_LENGTH),
            ForeignKey("calls.key", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
        name: Mapped[str] = mapped_column(_Name, nullable=False, index=True)
        data: Mapped[dict] = mapped_column(JSON, nullable=False)

        __table_args__ = (
            UniqueConstraint("call_key", "name", name="uq_metadata_call_name"),
        )


def _coerce_sqlite_url(path_or_url: str | None) -> str:
    """Normalise the user-facing ``url=`` argument.

    Accepts a filesystem path (treated as sqlite), a ``sqlite:`` URL
    (passed through, parent dir auto-created), or any other SQLAlchemy URL
    such as ``postgresql://`` / ``mysql+pymysql://`` (passed through
    verbatim). Only sqlite paths get the parent-dir-create convenience.
    Leading ``~`` is expanded to the home directory in both bare paths and
    ``sqlite:///`` URLs.
    """
    if path_or_url is None:
        return "sqlite:///:memory:"

    s = str(path_or_url)

    # Already a SQLAlchemy URL of any dialect (driver scheme contains "://"
    # or the short ``sqlite:foo`` form). Leave it alone.
    if "://" in s or s.startswith("sqlite:"):
        url = s
    else:
        abs_path = Path(s).expanduser().absolute()
        url = f"sqlite:///{abs_path}"

    if url.startswith("sqlite:///"):
        db_path = url[len("sqlite:///"):]
        if db_path and db_path != ":memory:":
            expanded = Path(db_path).expanduser()
            if expanded != Path(db_path):
                url = f"sqlite:///{expanded}"
            expanded.parent.mkdir(parents=True, exist_ok=True)

    return url


# Use constants for the PRAGMA executions to avoid raw string injection risks.
SQLITE_FOREIGN_KEYS_ON = "PRAGMA foreign_keys=ON"
SQLITE_WAL_MODE = "PRAGMA journal_mode=WAL"


def _configure_sqlite_pragmas(engine) -> None:
    # PRAGMA is sqlite-only; running it on Postgres/MySQL connections would
    # raise at connect time, so gate the listener on the dialect.
    if engine.dialect.name != "sqlite":
        return

    # WAL mode requires a real file; skip it for in-memory databases where it
    # is a silent no-op but adds an unnecessary round-trip.
    is_memory = str(engine.url).endswith(":memory:")

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            # We use static constant strings here. We cannot use sqlalchemy.text()
            # because we are operating on a raw DBAPI cursor at the 'connect' event.
            cursor.execute(SQLITE_FOREIGN_KEYS_ON)
            if not is_memory:
                cursor.execute(SQLITE_WAL_MODE)
        finally:
            cursor.close()


@dataclass(frozen=True)
class Sql(PerKeyLockMixin, CallStorage):
    """SQLAlchemy-backed CallStorage with JSON metadata and DB-backed expand()."""

    url: str | None = None
    echo: bool = field(default=False, compare=False)

    engine: Any = field(init=False, repr=False, compare=False)
    session: Any = field(init=False, repr=False, compare=False)
    _local: threading.local = field(default_factory=threading.local, init=False, repr=False, compare=False)

    @sqlalchemy_alarm
    def __post_init__(self) -> None:
        coerced_url = _coerce_sqlite_url(self.url)
        assert coerced_url is not None
        object.__setattr__(self, "url", coerced_url)
        # ``check_same_thread=False`` is a pysqlite-only flag; passing it to
        # any other DBAPI driver raises ``TypeError`` at connect time.
        is_sqlite = coerced_url.startswith("sqlite:")
        connect_args = {"check_same_thread": False} if is_sqlite else {}
        engine = create_engine(coerced_url, echo=self.echo, future=True, connect_args=connect_args)
        _configure_sqlite_pragmas(engine)
        Base.metadata.create_all(engine)
        object.__setattr__(self, "engine", engine)
        object.__setattr__(self, "session", sessionmaker(
            bind=engine, expire_on_commit=False, future=True
        ))

    def __reduce__(self):
        # Constructor args are the complete durable state; __post_init__ rebuilds
        # engine/session and the mixin's lock fields are self-contained picklable types.
        return (type(self), (self.url, self.echo))

    def to_config(self) -> dict[str, Any]:
        return {"type": "sql", "url": self.url, "echo": self.echo}

    @contextlib.contextmanager
    def _session_context(self):
        if getattr(self._local, "session", None) is not None:
            yield
            return
        session = self.session()
        self._local.session = session
        try:
            yield
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
            self._local.session = None

    @contextlib.contextmanager
    def _operation_context(self, key, *, intent: Intent = Intent.WRITE):
        with self._session_context():
            with super()._operation_context(key, intent=intent):
                yield

    def _persist_call(self, call: DigestedCall, key: Digest) -> Digest:
        session = self._local.session
        existing = session.get(CallModel, str(key))
        if existing is not None:
            if self._fetch_call(key) == call:
                return key

            session.delete(existing)
            session.flush()

        call_model = CallModel(
            key=str(key),
            name=call.name,
            module=call.module,
            version=json.dumps(call.version) if call.version is not None else None,
            code_digest=call.code_digest,
            result=call.result if call.result is None else str(call.result),
        )
        session.add(call_model)

        for i, (k, v) in enumerate(call.arguments.items()):
            session.add(
                ArgumentModel(
                    call_key=str(key), position=i, name=str(k), value=str(v)
                )
            )

        if call.metadata:
            session.add_all(
                [
                    MetaModel(call_key=str(key), name=name, data=data)
                    for name, data in call.metadata.items()
                ]
            )
        session.commit()
        return key

    def _fetch_call(self, key: Digest) -> DigestedCall:
        session = self._local.session
        call_model = session.execute(
            select(CallModel).where(CallModel.key == str(key))
        ).scalar_one_or_none()
        if call_model is None:
            raise KeyError(key)

        arguments = {arg.name: Digest(arg.value) for arg in call_model.arguments}

        meta_rows = (
            session.execute(select(MetaModel).where(MetaModel.call_key == str(key)))
            .scalars()
            .all()
        )
        return DigestedCall(
            name=call_model.name,
            arguments=arguments,
            metadata={row.name: (row.data or {}) for row in meta_rows},
            module=call_model.module,
            version=(json.loads(call_model.version) if isinstance(call_model.version, str) else call_model.version) if call_model.version is not None else None,
            code_digest=Digest(call_model.code_digest) if call_model.code_digest is not None else None,
            result=(
                Digest(call_model.result) if call_model.result is not None else None
            ),
        )

    def _contains(self, key: Digest) -> bool:
        return (
            self._local.session.execute(
                select(CallModel.key).where(CallModel.key == str(key))
            ).first()
            is not None
        )

    def list(self) -> Iterable[Digest]:
        with self._session_context():
            return [Digest(row[0]) for row in self._local.session.execute(select(CallModel.key))]

    def _prefix_candidates(self, prefix: str) -> Iterable[Digest]:
        rows = self._local.session.execute(
            select(CallModel.key)
            .where(CallModel.key.like(f"{prefix}%"))
            .order_by(CallModel.key)
            .limit(2)
        ).all()
        return [Digest(r[0]) for r in rows]

    def _evict(self, key: Digest) -> None:
        session = self._local.session
        # Bypass ORM object loading and cascade-via-Python; rely on DB-level
        # ON DELETE CASCADE (foreign_keys=ON is set for SQLite via PRAGMA at
        # connect time; Postgres/MySQL enforce FK cascades natively).
        session.execute(
            delete(CallModel).where(CallModel.key == str(key))
        )
        session.commit()

    def save(self, call: DigestedCall) -> Digest:
        key = call.to_lookup_key()
        with self._operation_context(key):
            logger.debug("Saving call %s", key)
            # ``_persist_call`` runs a SELECT for the existing row and folds the
            # overwrite-vs-no-op decision into a single transaction; ``CallMixin``'s
            # ``contains`` / ``evict`` pre-check would be a redundant SELECT plus
            # an extra DELETE+COMMIT round-trip on collisions. Per-key locking via
            # ``PerKeyLockMixin`` keeps concurrent saves serialised (see
            # ``test_sql_concurrent_save.py``).
            return self._persist_call(call, key)

    def load(self, key: Digest | str) -> DigestedCall:
        with self._operation_context(key):
            key = self._normalize_key(key)
            logger.debug("Loading call with key %s", key)
            return self._fetch_call(key)

    def _normalize_value(self, v: Any) -> str:
        """Return the stored form used in SQL for argument/result matching.

        We must match the generic CallStorage.query semantics which compare
        digest(template_value) == digest(stored_call_value).
        In this backend, stored argument/result values are hex-digest strings,
        and digest(Digest(x)) == x. Therefore we should always compare
        Arg.value/CallModel.result to str(digest(template_value)).
        """
        return str(digest(v))

    def _build_call_conditions(self, template: QueryCall) -> List[Any]:
        conditions = []
        if template.name is not None:
            conditions.append(CallModel.name == template.name)
        if template.module is not None:
            conditions.append(CallModel.module == template.module)
        if template.version is not None:
            conditions.append(CallModel.version == json.dumps(template.version))
        if template.code_digest is not None:
            conditions.append(CallModel.code_digest == template.code_digest)
        if template.result is not None:
            conditions.append(
                CallModel.result == self._normalize_value(template.result)
            )
        return conditions

    def _apply_argument_filters(self, stmt: Any, arguments: dict[str, Any] | None) -> Any:
        if not arguments:
            return stmt

        for k, v in arguments.items():
            Arg = aliased(ArgumentModel)
            on_clause = and_(
                Arg.call_key == CallModel.key,
                Arg.name == str(k),
            )
            if v is not None:
                on_clause = and_(on_clause, Arg.value == self._normalize_value(v))
            stmt = stmt.join(Arg, on_clause)
        return stmt

    def _apply_metadata_filters(
        self, stmt: Any, meta_specs: dict[str, dict[str, Any]] | None
    ) -> Any:
        if not meta_specs:
            return stmt

        # Determine if all filters are server-side compatible
        server_side_meta = True
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
                stmt = stmt.join(
                    M,
                    and_(
                        M.call_key == CallModel.key,
                        M.name == mname,
                    ),
                )
                for k, v in (filters or {}).items():
                    if isinstance(v, bool):
                        stmt = stmt.where(M.data[k].as_boolean() == v)
                    elif isinstance(v, int):
                        stmt = stmt.where(M.data[k].as_integer() == v)
                    elif isinstance(v, float):
                        stmt = stmt.where(M.data[k].as_float() == v)
                    else:
                        stmt = stmt.where(M.data[k].as_string() == v)
        return stmt

    def query(self, template: QueryCall) -> Iterable[DigestedCall]:
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
        with self._session_context():
            stmt = select(CallModel.key).select_from(CallModel)

            conditions = self._build_call_conditions(template)
            if conditions:
                stmt = stmt.where(and_(*conditions))

            stmt = self._apply_argument_filters(stmt, template.arguments)
            stmt = self._apply_metadata_filters(stmt, template.metadata)

            # Distinct to avoid duplicate keys if multiple argument joins could overlap
            stmt = stmt.distinct()

            keys = [Digest(k) for (k,) in self._local.session.execute(stmt).all()]

        # Yield loaded calls using existing loader (ensures metadata returned too)
        def meta_matches(call: DigestedCall) -> bool:
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


register_storage("sql", kind="call")(Sql)
