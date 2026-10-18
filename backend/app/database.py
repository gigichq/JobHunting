"""SQLite + SQLAlchemy 2（WAL、busy_timeout、短事务）。"""
import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

settings = get_settings()
os.makedirs(os.path.dirname(os.path.abspath(settings.db_path)), exist_ok=True)

engine = create_engine(
    f"sqlite:///{settings.db_path}",
    connect_args={"check_same_thread": False, "timeout": 15},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=15000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
