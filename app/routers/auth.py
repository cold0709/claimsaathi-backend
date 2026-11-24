import hmac
import logging
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import DEMO_OTP, OTP_LOCK_SECONDS, OTP_MAX_ATTEMPTS, settings
from ..database import get_db
from ..models import OtpRequest, PolicyHolder
from ..otp_provider import get_otp_provider
from ..ratelimit import limiter
from ..schemas import ChangePhoneIn, SendOtpIn, VerifyOtpIn
from ..security import create_token, hash_otp, user_payload
from ..utils import mask_phone, normalise_phone, normalise_policy_number, utcnow

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger("claimsaathi.auth")
INVALID_OTP = "Invalid or expired OTP"


def _holder_or_404(db: Session, policy_number: str) -> PolicyHolder:
    holder = db.scalar(select(PolicyHolder).where(PolicyHolder.policy_number == policy_number))
    if not holder:
        raise HTTPException(404, "Policy number not found")
    return holder


def _check_lock(db: Session, pn: str) -> None:
    now = utcnow()
    locked = db.scalar(select(OtpRequest.locked_until)
                       .where(OtpRequest.policy_number == pn, OtpRequest.locked_until > now)
                       .order_by(OtpRequest.locked_until.desc()))
    if locked:
        secs = int((locked - now).total_seconds()) + 1
        raise HTTPException(429, f"Too many wrong attempts. Try again in {secs // 60 + 1} minute(s).",
                            headers={"Retry-After": str(secs)})


def _consume_otp(db: Session, pn: str, otp: str, purposes: tuple[str, ...], new_phone: str | None = None) -> None:
    _check_lock(db, pn)
    req = db.scalars(select(OtpRequest).where(
        OtpRequest.policy_number == pn, OtpRequest.used.is_(False), OtpRequest.purpose.in_(purposes))
        .order_by(OtpRequest.id.desc())).first()
    if not req or req.expires_at < utcnow() or req.attempts >= OTP_MAX_ATTEMPTS:
        raise HTTPException(400, INVALID_OTP)
    if not hmac.compare_digest(req.otp_hash, hash_otp(pn, req.purpose, otp.strip())):
        req.attempts += 1
        if req.attempts >= OTP_MAX_ATTEMPTS:
            req.locked_until = utcnow() + timedelta(seconds=OTP_LOCK_SECONDS)
            logger.warning("OTP locked for %s", pn)
        db.commit()
        raise HTTPException(400, INVALID_OTP)
    if req.new_phone and new_phone and req.new_phone != new_phone:
        raise HTTPException(400, "This OTP was requested for a different phone number")
    req.used = True
    db.commit()


@router.post("/send-otp")
@limiter.limit("5/minute")
def send_otp(request: Request, body: SendOtpIn, db: Session = Depends(get_db)):
    pn = normalise_policy_number(body.policy_number)
    holder = _holder_or_404(db, pn)
    _check_lock(db, pn)

    purpose = body.purpose if body.purpose in ("login", "change_phone") else "login"
    new_phone = None
    if purpose == "change_phone" and body.new_phone:
        new_phone = normalise_phone(body.new_phone)
        if not new_phone:
            raise HTTPException(400, "Enter a valid 10-digit Indian mobile number")

    otp = DEMO_OTP if settings.demo_mode else f"{secrets.randbelow(1_000_000):06d}"
    db.execute(update(OtpRequest).where(OtpRequest.policy_number == pn, OtpRequest.used.is_(False))
               .values(used=True))                                       # one live OTP at a time
    db.add(OtpRequest(policy_number=pn, otp_hash=hash_otp(pn, purpose, otp), purpose=purpose, new_phone=new_phone,
                      expires_at=utcnow() + timedelta(seconds=settings.otp_ttl_seconds)))
    db.commit()

    try:
        get_otp_provider().send(holder.phone, otp, purpose)        # OTP goes to the REGISTERED phone
    except Exception:
        logger.exception("OTP delivery failed")
        raise HTTPException(502, "Could not send OTP right now. Please try again.")

    resp = {"sent": True, "phone_masked": mask_phone(holder.phone)}
    if settings.demo_mode:
        resp["demo_otp"] = DEMO_OTP
    return resp


@router.post("/verify-otp")
def verify_otp(body: VerifyOtpIn, db: Session = Depends(get_db)):
    pn = normalise_policy_number(body.policy_number)
    holder = _holder_or_404(db, pn)
    _consume_otp(db, pn, body.otp, ("login",))
    return {"token": create_token(holder), "user": user_payload(holder)}


@router.post("/change-phone")
def change_phone(body: ChangePhoneIn, db: Session = Depends(get_db)):
    pn = normalise_policy_number(body.policy_number)
    holder = _holder_or_404(db, pn)
    new_phone = normalise_phone(body.new_phone)
    if not new_phone:                       # validate BEFORE burning the OTP
        raise HTTPException(400, "Enter a valid 10-digit Indian mobile number (starts with 6-9)")
    # Accepts a dedicated change_phone OTP, or a freshly sent (unused) login OTP:
    # both were delivered to the registered phone, which is the proof of ownership we need.
    _consume_otp(db, pn, body.otp, ("change_phone", "login"), new_phone)
    holder.phone = new_phone
    db.commit()
    return {"ok": True}