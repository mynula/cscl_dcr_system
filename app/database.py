import logging
from sqlalchemy import Table, create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateColumn
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

logger = logging.getLogger(__name__)

db_url = settings.DATABASE_URL
connect_args = {}
if db_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

try:
    engine = create_engine(
        db_url,
        pool_pre_ping=True,
        connect_args=connect_args
    )
    with engine.connect() as conn:
        logger.info("Successfully connected to primary database.")
except Exception as e:
    logger.warning(
        "Database connection to %s failed (%s). "
        "Falling back to local SQLite database (./cscl_dcr.db) for zero-interruption operation. "
        "Update DATABASE_URL in .env with your PostgreSQL credentials to use PostgreSQL.",
        engine.url.render_as_string(hide_password=True),
        type(e).__name__,
    )
    if settings.APP_ENV.lower() == "production":
        raise RuntimeError("Could not connect to the configured production database.") from None
    db_url = "sqlite:///./cscl_dcr.db"
    engine = create_engine(
        db_url,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False}
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def ensure_table_columns(table: Table, target_engine: Engine = engine):
    """Add model columns missing from an existing table."""
    with target_engine.begin() as conn:
        existing_columns = {
            column["name"] for column in inspect(conn).get_columns(table.name)
        }
        preparer = conn.dialect.identifier_preparer
        quoted_table = preparer.quote(table.name)

        for column in table.columns:
            if column.name in existing_columns:
                continue

            column_ddl = CreateColumn(column).compile(dialect=conn.dialect)
            conn.execute(text(f"ALTER TABLE {quoted_table} ADD COLUMN {column_ddl}"))
            logger.info("Added missing column %s.%s.", table.name, column.name)


def get_db():
    """FastAPI dependency yielding a thread-local database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
