import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Complaint, PolicyHolder
from ..schemas import ComplaintIn
from ..security import enforce_owner, get_current_policy
from ..utils import iso, normalise_policy_number

router = APIRouter(prefix="/api", tags=["complaints"], dependencies=[Depends(get_current_policy)])


def _known(db: Session, pn: str) -> None:
    if not db.scalar(select(PolicyHolder.id).where(PolicyHolder.policy_number == pn)):
        raise HTTPException(404, "Policy number not found")


@router.post("/complaints")
def create_complaint(body: ComplaintIn, db: Session = Depends(get_db),
                     user: Optional[str] = Depends(get_current_policy)):
    pn = normalise_policy_number(body.policy_number)
    _known(db, pn)
    enforce_owner(user, pn)
    while True:
        cid = f"CMP-{secrets.randbelow(90000) + 10000}"
        if not db.scalar(select(Complaint.id).where(Complaint.complaint_id == cid)):
            break
    db.add(Complaint(complaint_id=cid, policy_number=pn, category=body.category.strip() or "other",
                     message=body.message, status="open"))
    db.commit()
    return {"complaint_id": cid, "status": "open"}


@router.get("/complaints")
def list_complaints(policy_number: Optional[str] = None, db: Session = Depends(get_db),
                    user: Optional[str] = Depends(get_current_policy)):
    pn = normalise_policy_number(policy_number or user)
    if not pn:
        raise HTTPException(400, "policy_number is required")
    enforce_owner(user, pn)
    rows = db.scalars(select(Complaint).where(Complaint.policy_number == pn)
                      .order_by(Complaint.created_at.desc(), Complaint.id.desc())).all()
    return [{"complaint_id": c.complaint_id, "policy_number": c.policy_number, "category": c.category,
             "message": c.message, "status": c.status, "created_at": iso(c.created_at)} for c in rows]