from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .utils import utcnow


class PolicyHolder(Base):
    __tablename__ = "policy_holders"
    id: Mapped[int] = mapped_column(primary_key=True)
    policy_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(15))
    policy_id: Mapped[str] = mapped_column(String(32))
    sum_insured: Mapped[int] = mapped_column(Integer)
    valid_till: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))
    nominee: Mapped[str] = mapped_column(String(120))


class OtpRequest(Base):
    __tablename__ = "otp_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    policy_number: Mapped[str] = mapped_column(String(32), index=True)
    otp_hash: Mapped[str] = mapped_column(String(128))          # HMAC-SHA256, never the raw OTP
    purpose: Mapped[str] = mapped_column(String(20))            # "login" | "change_phone"
    new_phone: Mapped[str | None] = mapped_column(String(15), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    # extra bookkeeping columns (needed for the 10-minute lockout)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Complaint(Base):
    __tablename__ = "complaints"
    id: Mapped[int] = mapped_column(primary_key=True)
    complaint_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    policy_number: Mapped[str] = mapped_column(String(32), index=True)
    category: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[int] = mapped_column(primary_key=True)
    tracking_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    policy_number: Mapped[str] = mapped_column(String(32), index=True)
    patient_name: Mapped[str] = mapped_column(String(120))
    covered_amount: Mapped[float] = mapped_column(Float)
    readiness_score: Mapped[int] = mapped_column(Integer)
    bill_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="submitted")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ClaimEvent(Base):
    __tablename__ = "claim_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    tracking_id: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(30))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)