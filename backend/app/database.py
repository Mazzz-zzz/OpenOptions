from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Exogenous database ──────────────────────────────────────────────

_exo_engine = None
_ExoSessionLocal = None


def _init_exo():
    global _exo_engine, _ExoSessionLocal
    if _exo_engine is None and settings.db_host:
        _exo_engine = create_engine(
            settings.exo_database_url,
            pool_size=2,
            max_overflow=5,
            pool_pre_ping=True,
        )
        _ExoSessionLocal = sessionmaker(bind=_exo_engine, autocommit=False, autoflush=False)


def get_exo_db() -> Generator[Session, None, None]:
    _init_exo()
    if _ExoSessionLocal is None:
        raise RuntimeError("Exogenous DB not configured (no db_host)")
    db = _ExoSessionLocal()
    try:
        yield db
    finally:
        db.close()
