from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

_url = settings.database_url
engine = create_engine(_url, connect_args={"check_same_thread": False} if _url.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


SEED_HOLDERS = [
    dict(policy_number="HLT-2026-001234", name="Ramesh Kumar", phone="9876543210", policy_id="basic_health",
         sum_insured=100000, valid_till=date(2027, 3, 31), status="Active", nominee="Meena Kumar"),
    dict(policy_number="ACC-2026-005678", name="Sunita Devi", phone="9812345678", policy_id="gig_accident",
         sum_insured=200000, valid_till=date(2027, 1, 15), status="Active", nominee="Raju Devi"),
]


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for h in SEED_HOLDERS:
            exists = db.scalar(select(models.PolicyHolder).where(models.PolicyHolder.policy_number == h["policy_number"]))
            if not exists:
                db.add(models.PolicyHolder(**h))
        db.commit()