from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


engine = create_engine(get_settings().database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def initialize_database() -> None:
    import app.models  # noqa: F401 — register metadata

    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_task_workspace_column()


def _ensure_sqlite_task_workspace_column() -> None:
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.begin() as connection:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(tasks)")).fetchall()}
        if "workspace_id" not in columns:
            connection.execute(text("ALTER TABLE tasks ADD COLUMN workspace_id INTEGER"))
