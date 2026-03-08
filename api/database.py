from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./bitcoin_optimizer.db",
)

is_sqlite = DATABASE_URL.startswith("sqlite")

engine_kwargs = {"pool_pre_ping": True}
if is_sqlite:
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()