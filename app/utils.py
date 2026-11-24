import math
import re
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC datetime (SQLite does not keep tzinfo)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds") + "Z"


def normalise_policy_number(v: str | None) -> str:
    return (v or "").strip().upper()


def mask_phone(phone: str) -> str:
    return phone[:2] + "X" * max(len(phone) - 4, 0) + phone[-2:]


_PHONE_RE = re.compile(r"^[6-9]\d{9}$")


def normalise_phone(raw) -> str | None:
    """Return a clean 10-digit Indian mobile (starts 6-9) or None."""
    s = re.sub(r"[\s\-()]", "", str(raw or ""))
    if s.startswith("+91"):
        s = s[3:]
    elif len(s) == 12 and s.startswith("91"):
        s = s[2:]
    elif len(s) == 11 and s.startswith("0"):
        s = s[1:]
    return s if _PHONE_RE.match(s) else None


_AMOUNT_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def parse_amount(v) -> float:
    """'₹ 1,200.50' / 'Rs. 1200' / 1200 -> float. Garbage -> 0.0"""
    if isinstance(v, bool):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else 0.0
    m = _AMOUNT_RE.search(str(v or ""))
    if not m:
        return 0.0
    try:
        return float(m.group().replace(",", ""))
    except ValueError:
        return 0.0


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y",
                 "%d/%m/%y", "%d-%m-%y", "%b %d, %Y", "%B %d, %Y")


def parse_date(v) -> str:
    """Return YYYY-MM-DD or '' when unparseable."""
    s = str(v or "").strip()
    if not s:
        return ""
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s[:20] if fmt != "%Y-%m-%d" else s[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""