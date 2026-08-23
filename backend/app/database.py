from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import QueuePool

from app.config import get_settings

settings = get_settings()

# Pool settings spelled out explicitly rather than left to SQLAlchemy's
# defaults for a file-backed SQLite engine (QueuePool(pool_size=5,
# max_overflow=10, pool_timeout=30)) — those defaults happen to be exactly
# what we want, but the scheduler shares this engine/pool with the request
# path, so the tuning should be visible here rather than implicit.
engine = create_engine(
    f"sqlite:///{settings.database_path}",
    connect_args={"check_same_thread": False},
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
)


@event.listens_for(engine, "connect")
def _enable_wal(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    # The 23:00 snapshot rebuild legitimately holds one write transaction
    # open for minutes (a per-day N+1 valuation loop inside it). Without an
    # explicit busy_timeout, every connection inherits pysqlite's 5-second
    # default, so any concurrent write (booking a transaction, a manual
    # price refresh) blocks for 5s and then raises `OperationalError:
    # database is locked`, unhandled, as an HTTP 500 — reads are unaffected
    # under WAL, which is why only *some* things fail during the rebuild.
    # 20s comfortably covers a multi-minute writer's individual statements
    # while still bounding worst-case request latency to something sane.
    cursor.execute("PRAGMA busy_timeout=20000")
    # WAL's standard companion: fsync only at checkpoints rather than every
    # commit. Still durable under WAL (the WAL file itself is what
    # protects against a crash), and meaningfully faster on the Pi's
    # SD/USB storage.
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
