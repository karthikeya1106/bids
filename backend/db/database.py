from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = (os.getenv("DATABASE_URL") or "sqlite:///bids.db").strip()

# Supabase, Heroku and Railway hand out "postgres://" URLs; SQLAlchemy only
# understands "postgresql://". Normalise instead of failing at import time.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

IS_SQLITE = DATABASE_URL.startswith("sqlite")

if DATABASE_URL.startswith("sqlite:///"):
    db_path = DATABASE_URL.replace("sqlite:///", "")
    if not os.path.isabs(db_path):
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        abs_db_path = os.path.normpath(os.path.join(backend_dir, db_path))
        DATABASE_URL = f"sqlite:///{abs_db_path.replace(os.sep, '/')}"

if IS_SQLITE:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # Managed Postgres (Supabase pooler, Neon, RDS) drops idle connections and
    # may be reached over a longer link than a local socket, so keep the pool
    # small, health-check connections and recycle them before the server does.
    connect_args = {
        "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "10")),
        # "prefer" negotiates TLS when the server offers it and still works
        # against a local server without certificates; set DB_SSLMODE=require
        # for Supabase.
        "sslmode": os.getenv("DB_SSLMODE", "prefer"),
    }
    engine = create_engine(
        DATABASE_URL,
        connect_args=connect_args,
        pool_pre_ping=True,
        pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "5")),
        pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "1800")),
        pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def database_backend() -> str:
    """Short label for health output and logs."""
    return "sqlite" if IS_SQLITE else engine.dialect.name


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
