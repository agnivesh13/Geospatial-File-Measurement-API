"""Database engine and session setup."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base


def create_session_factory(database_url: str) -> sessionmaker[Session]:
    url = make_url(database_url)
    is_sqlite = url.get_backend_name() == "sqlite"
    if is_sqlite and url.database and url.database != ":memory:":
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    # FastAPI runs sync endpoints in a thread pool, so SQLite must allow cross-thread use.
    engine = create_engine(url, connect_args={"check_same_thread": False} if is_sqlite else {})
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
