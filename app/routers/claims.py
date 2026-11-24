import hashlib
import json
import secrets
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from ..config import MAX_UPLOAD_BYTES, settings
from ..database import get_db
from ..extraction import extract_from_image, prepare_image
from ..models import Claim, ClaimEvent, PolicyHolder
from ..pdf import build_claim_pdf
from ..policies import EXPECTED_DAYS, POLICIES, public_policy
from ..samples import SAMPLE_META, get_sample
from ..schemas import ClaimRequest, ValidateRequest
from ..security import enforce_owner, get_current_policy
from ..utils import iso, normalise_policy_number, utcnow
from ..validation import validate_claim

router = APIRouter(prefix="/api", tags=["claims"], dependencies=[Depends(get_current_policy)])


@router.get("/policies")
def list_policies():
    return [public_policy(p) for p in POLICIES.values()]


@router.get("/samples")
def list_samples():
    return SAMPLE_META


# ---------------------------------------------------------------- extract
@router.post("/extract")
async def extract(request: Request):
    cl = request.headers.get("content-length", "")
    if cl.isdigit() and int(cl) > MAX_UPLOAD_BYTES + 64 * 1024:
        raise HTTPException(400, "File too large (max 8 MB)")

    ctype = request.headers.get("content-type", "").lower()
    upload, sample_id = None, None
    if ctype.startswith("multipart/") or ctype.startswith("application/x-www-form-urlencoded"):
        form = await request.form()
        upload, sample_id = form.get("file"), form.get("sample_id")
    else:
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(400, "Send a multipart 'file' or JSON {\"sample_id\": ...}")
        if isinstance(payload, dict):
            sample_id = payload.get("sample_id")

    if upload is not None:
        if not isinstance(upload, UploadFile):
            raise HTTPException(400, "'file' must be an uploaded file")
        if not (upload.content_type or "").lower().startswith("image/"):
            raise HTTPException(400, "Only image files are accepted")
        data = await upload.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, "File too large (max 8 MB)")
        if not data:
            raise HTTPException(400, "Empty file")
        try:
            jpeg = await run_in_threadpool(prepare_image, data)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return await run_in_threadpool(extract_from_image, jpeg)

    if sample_id:
        sample = get_sample(str(sample_id))
        if not sample:
            raise HTTPException(404, "Unknown sample_id")
        return sample
    raise HTTPException(400, "Provide an image 'file' or a 'sample_id'")


# ---------------------------------------------------------------- validate / pdf / submit
def _validate(body: ClaimRequest) -> dict:
    try:
        return validate_claim(body.policy_id, body.bill, body.documents_provided, body.policy_holder_name)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/validate")
def validate(body: ValidateRequest):
    return _validate(body)


@router.post("/claim-pdf")
def claim_pdf(body: ClaimRequest):
    v = _validate(body)     # never trust a client-supplied 'validation'
    pdf = build_claim_pdf(body, v)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="claimsaathi-claim.pdf"'})


def _resolve_policy_number(db: Session, body: ClaimRequest, user: Optional[str]) -> str:
    if body.policy_number:
        pn = normalise_policy_number(body.policy_number)
        if db.scalar(select(PolicyHolder.id).where(PolicyHolder.policy_number == pn)):
            return pn
    if user:
        return user
    holders = db.scalars(select(PolicyHolder).where(PolicyHolder.policy_id == body.policy_id)).all()
    by_name = [h for h in holders if h.name.strip().lower() == body.policy_holder_name.strip().lower()]
    if len(by_name) == 1:
        return by_name[0].policy_number
    if len(holders) == 1:
        return holders[0].policy_number
    return "UNKNOWN"


def _bill_hash(body: ClaimRequest) -> str:
    b = body.bill
    canon = {"p": body.policy_id, "n": b.patient_name.strip().lower(), "h": b.hospital.strip().lower(),
             "a": b.admission_date, "d": b.discharge_date, "t": round(b.total_amount, 2),
             "i": sorted((i.name.strip().lower(), round(i.amount, 2)) for i in b.items)}
    return hashlib.sha256(json.dumps(canon, sort_keys=True).encode()).hexdigest()


@router.post("/submit")
def submit(body: ClaimRequest, db: Session = Depends(get_db), user: Optional[str] = Depends(get_current_policy)):
    v = _validate(body)
    pn = _resolve_policy_number(db, body, user)
    enforce_owner(user, pn)
    h = _bill_hash(body)

    dup = db.scalar(select(Claim).where(Claim.policy_number == pn, Claim.bill_hash == h))
    if dup:   # idempotent: re-submitting the same bill never creates a second claim
        return {"tracking_id": dup.tracking_id, "expected_days": EXPECTED_DAYS, "simulated": True}

    while True:
        tid = f"CS-{utcnow().year}-{secrets.randbelow(90000) + 10000}"
        if not db.scalar(select(Claim.id).where(Claim.tracking_id == tid)):
            break
    now = utcnow()
    db.add(Claim(tracking_id=tid, policy_number=pn, patient_name=body.bill.patient_name or body.policy_holder_name,
                 covered_amount=v["covered_amount"], readiness_score=v["readiness_score"], bill_hash=h,
                 status="submitted", created_at=now))
    db.add(ClaimEvent(tracking_id=tid, status="submitted", note="Claim submitted (simulated)", created_at=now))
    db.commit()
    return {"tracking_id": tid, "expected_days": EXPECTED_DAYS, "simulated": True}


# ---------------------------------------------------------------- claims & timeline
def _advance(db: Session, claim: Claim) -> None:
    """Demo only: simulate the insurer progressing the claim based on its age."""
    if not settings.demo_mode:
        return
    age = (utcnow() - claim.created_at).total_seconds()
    seen = set(db.scalars(select(ClaimEvent.status).where(ClaimEvent.tracking_id == claim.tracking_id)))
    final = (("approved", "Claim approved. Payout will be credited to your bank account (simulated).")
             if claim.readiness_score >= 70 else
             ("more_info_needed", "The insurer needs more information. Please check your documents (simulated)."))
    changed = False
    for delay, status, note in [(60, "documents_verified", "Documents verified (simulated)"),
                                (180, "under_review", "Claim is under review by the insurer (simulated)"),
                                (420, *final)]:
        if age >= delay and status not in seen:
            db.add(ClaimEvent(tracking_id=claim.tracking_id, status=status, note=note,
                              created_at=claim.created_at + timedelta(seconds=delay)))
            claim.status = status
            changed = True
    if changed:
        db.commit()


def _claim_dict(c: Claim) -> dict:
    return {"tracking_id": c.tracking_id, "policy_number": c.policy_number, "patient_name": c.patient_name,
            "covered_amount": c.covered_amount, "readiness_score": c.readiness_score, "status": c.status,
            "created_at": iso(c.created_at)}


@router.get("/claims")
def list_claims(policy_number: Optional[str] = None, db: Session = Depends(get_db),
                user: Optional[str] = Depends(get_current_policy)):
    pn = normalise_policy_number(policy_number or user)
    if not pn:
        raise HTTPException(400, "policy_number is required")
    enforce_owner(user, pn)
    claims = db.scalars(select(Claim).where(Claim.policy_number == pn)
                        .order_by(Claim.created_at.desc(), Claim.id.desc())).all()
    for c in claims:
        _advance(db, c)
    return [_claim_dict(c) for c in claims]


@router.get("/claims/{tracking_id}")
def get_claim(tracking_id: str, db: Session = Depends(get_db),
              user: Optional[str] = Depends(get_current_policy)):
    claim = db.scalar(select(Claim).where(Claim.tracking_id == tracking_id.strip().upper()))
    if not claim:
        raise HTTPException(404, "Claim not found")
    enforce_owner(user, claim.policy_number)
    _advance(db, claim)
    events = db.scalars(select(ClaimEvent).where(ClaimEvent.tracking_id == claim.tracking_id)
                        .order_by(ClaimEvent.created_at, ClaimEvent.id)).all()
    timeline = [{"status": e.status, "note": e.note, "created_at": iso(e.created_at)} for e in events]
    return {**_claim_dict(claim), "events": timeline, "timeline": timeline}