"""
Database setup with SQLAlchemy async support.
Supports both SQLite (for development) and PostgreSQL (for production).
"""
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.engine import make_url
from sqlalchemy import event, inspect as sa_inspect
from .config import get_settings

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setLevel(logging.DEBUG)
    _h.setFormatter(logging.Formatter("database %(levelname)s: %(message)s"))
    logger.addHandler(_h)
    logger.propagate = False
settings = get_settings()

# Convert database URL for async drivers and handle query params
url = make_url(settings.database_url)

if url.drivername == "postgresql":
    url = url.set(drivername="postgresql+asyncpg")
    # Extract non-asyncpg params from URL query
    query = dict(url.query)
    ssl_mode = query.pop("sslmode", None)
    query.pop("schema", None)
    url = url.set(query=query)
    connect_args = {}
    if ssl_mode:
        connect_args["ssl"] = ssl_mode
    engine = create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=5,
        max_overflow=5,
        connect_args=connect_args,
    )
elif url.drivername.startswith("sqlite"):
    url = url.set(drivername="sqlite+aiosqlite")
    engine = create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
else:
    engine = create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    """Dependency for getting database session."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


def _apply_rls_lockdown(sync_conn):
    """Postgres-only defense-in-depth for Supabase deployments.

    Enables Row Level Security (default-deny: enabled but with NO policies)
    on every model table and strips grants from Supabase's public API roles,
    so PostgREST / supabase-js clients can never read or write app data even
    with valid anon/service keys. The backend connects as the table owner,
    which bypasses RLS unless FORCE is used (we never force).

    Idempotent; runs on every startup so tables added by new models are
    locked automatically. No-op on other dialects (e.g. SQLite in tests).
    See sql/001_tier1_rls_lockdown.sql for the standalone equivalent.
    """
    if sync_conn.dialect.name != "postgresql":
        return
    for table_name in Base.metadata.tables:
        enabled = sync_conn.exec_driver_sql(
            "SELECT c.relrowsecurity FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            f"WHERE n.nspname = 'public' AND c.relname = '{table_name}'"
        ).scalar()
        sync_conn.exec_driver_sql(
            f'ALTER TABLE public."{table_name}" ENABLE ROW LEVEL SECURITY'
        )
        if not enabled:
            logger.info("RLS: enabled row level security on %s", table_name)
    for role in ("anon", "authenticated", "service_role"):
        exists = sync_conn.exec_driver_sql(
            f"SELECT 1 FROM pg_roles WHERE rolname = '{role}'"
        ).scalar()
        if exists:
            sync_conn.exec_driver_sql(
                f'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM "{role}"'
            )
            sync_conn.exec_driver_sql(
                f'REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM "{role}"'
            )


async def init_db():
    """Create all tables and auto-migrate missing columns."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Auto-migrate: add columns that exist in models but not in the actual DB
    async with engine.begin() as conn:
        def _migrate(sync_conn):
            inspector = sa_inspect(sync_conn)
            for table_name, table in Base.metadata.tables.items():
                existing = {c["name"] for c in inspector.get_columns(table_name)}
                for col in table.columns:
                    if col.name not in existing:
                        col_type = col.type.compile(sync_conn.dialect)
                        sql_parts = [f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type}"]
                        if not col.nullable:
                            sql_parts.append("NOT NULL")
                            # Use server_default or Python default for existing rows
                            default = None
                            if col.server_default is not None:
                                default = col.server_default.arg
                            if default is None and col.default is not None:
                                default = col.default.arg
                            if default is None:
                                # Type-based fallback to prevent migration crash
                                type_name = col.type.__class__.__name__.upper()
                                if "INT" in type_name:
                                    default = "0"
                                elif "BOOL" in type_name:
                                    default = "FALSE"
                                elif "DATETIME" in type_name or "TIMESTAMP" in type_name:
                                    default = "CURRENT_TIMESTAMP"
                                elif "TEXT" in type_name or "VARCHAR" in type_name or "STRING" in type_name:
                                    default = "''"
                                elif "FLOAT" in type_name or "NUMERIC" in type_name or "DECIMAL" in type_name:
                                    default = "0"
                                else:
                                    default = "NULL"
                            sql_parts.append(f"DEFAULT {default}")
                        sql = " ".join(sql_parts)
                        sync_conn.exec_driver_sql(sql)
                        logger.info("Migrated: added column %s.%s (%s)", table_name, col.name, col_type)

            # Auto-migrate: create indexes that exist in models but not in the DB
            for table_name, table in Base.metadata.tables.items():
                existing = set()
                for idx in inspector.get_indexes(table_name):
                    existing.add(idx["name"])
                for idx in table.indexes:
                    if idx.name in existing:
                        continue
                    cols = ", ".join(c.name for c in idx.columns)
                    unique = "UNIQUE " if idx.unique else ""
                    sql = f"CREATE {unique}INDEX IF NOT EXISTS {idx.name} ON {table_name} ({cols})"
                    sync_conn.exec_driver_sql(sql)
                    logger.info("Migrated: created index %s on %s (%s)", idx.name, table_name, cols)

            # Keep every table (including newly added models) locked down.
            _apply_rls_lockdown(sync_conn)

    async with engine.begin() as conn:
        await conn.run_sync(_migrate)

    # Data migration: reclassify files whose stored file_type doesn't match
    # their mime/extension (e.g. .mkv delivered as a Telegram document was
    # stored as "document"). ONE-TIME, guarded by an app_meta flag: the scan
    # reads every file row and issues one UPDATE per changed row inside a
    # single transaction — too slow to repeat on every boot of a large
    # library. Files inserted after this fixup are classified at insert time.
    from sqlalchemy import text
    from .media_types import classify_file_type
    async with engine.begin() as conn:
        done = (await conn.execute(
            text("SELECT value FROM app_meta WHERE key = 'file_type_reclassified'")
        )).scalar()
        if done:
            return
        rows = (await conn.execute(text("SELECT id, file_name, mime_type, file_type FROM files"))).all()
        changed = 0
        for fid, fname, mime, ftype in rows:
            effective = classify_file_type(fname, mime)
            if effective != ftype:
                await conn.execute(
                    text("UPDATE files SET file_type = :t WHERE id = :id"),
                    {"t": effective, "id": fid},
                )
                changed += 1
                logger.info("Reclassified file %s: %s -> %s", fid, ftype, effective)
        await conn.execute(
            text("INSERT INTO app_meta (key, value) VALUES ('file_type_reclassified', '1')")
        )
        if changed:
            logger.info("Reclassification complete: %d file(s) fixed (will not run again)", changed)
