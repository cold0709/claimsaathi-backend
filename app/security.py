import hashlib
import hmac
import time
from typing import Optional

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import JWT_TTL_SECONDS, settings
from .models import PolicyHolder
from .policies import POLICIES

_bearer = HTTPBearer(auto_error=False)


def hash_otp(policy_number: str, purpose: str, otp: str) -> str:
    """HMAC keyed with the server secret; policy+purpose act as salt. Raw OTPs are never stored."""
    msg = f"{policy_number}|{purpose}|{otp}".encode()
    return hmac.new(settings.jwt_secret.encode(), msg, hashlib.sha256).hexdigest()


def create_token(holder: PolicyHolder) -> str:
    now = int(time.time())
    payload = {"sub": holder.policy_number, "policy_id": holder.policy_id, "iat": now, "exp": now + JWT_TTL_SECONDS}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def user_payload(h: PolicyHolder) -> dict:
    p = POLICIES[h.policy_id]
    return {
        "policy_number": h.policy_number, "name": h.name, "phone": h.phone, "policy_id": h.policy_id,
        "type_en": p["name"], "type_hi": p["name_hi"], "sum_insured": h.sum_insured,
        "valid_till": h.valid_till.isoformat(), "status": h.status, "nominee": h.nominee,
    }


def get_current_policy(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> Optional[str]:
    """The single auth dependency for every /api route except /api/auth/*.
    REQUIRE_AUTH=false -> token optional (returns policy number if a valid one is sent, else None).
    REQUIRE_AUTH=true  -> valid Bearer token mandatory."""
    unauthorised = HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    if creds is None:
        if settings.require_auth:
            raise unauthorised
        return None
    try:
        payload = jwt.decode(creds.credentials, settings.jwt_secret, algorithms=["HS256"],
                             options={"require": ["exp", "sub"]})
        return payload["sub"]
    except jwt.PyJWTError:
        if settings.require_auth:
            raise unauthorised
        return None


def enforce_owner(user: Optional[str], policy_number: str) -> None:
    """When auth is mandatory, a token may only touch its own policy's data."""
    if settings.require_auth and user != policy_number:
        raise HTTPException(403, "You can only access your own policy data")