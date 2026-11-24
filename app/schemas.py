from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from .utils import parse_amount


def _num_to_str(v):
    return str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v


LooseStr = Annotated[str, BeforeValidator(_num_to_str)]


class ApiModel(BaseModel):
    """Base: unknown fields are ignored; explicit nulls are treated as 'not sent'."""
    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _drop_none(cls, data: Any):
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None}
        return data


# ---- auth ----
class SendOtpIn(ApiModel):
    policy_number: str
    purpose: str = "login"          # optional; "change_phone" lets the app request a dedicated OTP
    new_phone: LooseStr | None = None


class VerifyOtpIn(ApiModel):
    policy_number: str
    otp: LooseStr


class ChangePhoneIn(ApiModel):
    policy_number: str
    new_phone: LooseStr
    otp: LooseStr


# ---- complaints ----
class ComplaintIn(ApiModel):
    policy_number: str
    category: str = Field(default="other", max_length=50)
    message: str = Field(max_length=2000)

    @field_validator("message")
    @classmethod
    def _min_len(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 5:
            raise ValueError("message must be at least 5 characters")
        return v


# ---- claims ----
class Item(ApiModel):
    name: str = ""
    amount: float = 0.0

    @field_validator("amount", mode="before")
    @classmethod
    def _amt(cls, v):
        return parse_amount(v)


class Bill(ApiModel):
    patient_name: str = ""
    hospital: str = ""
    admission_date: str = ""
    discharge_date: str = ""
    diagnosis: str = ""
    total_amount: float = 0.0
    items: list[Item] = Field(default_factory=list)
    confidence: float | None = None
    source: str | None = None

    @field_validator("total_amount", "confidence", mode="before")
    @classmethod
    def _amt(cls, v):
        return parse_amount(v)


class ClaimRequest(ApiModel):
    policy_id: str
    bill: Bill = Field(default_factory=Bill)
    documents_provided: list[str] = Field(default_factory=list)
    policy_holder_name: str = ""
    policy_number: str | None = None        # optional; used to link submitted claims to a holder
    validation: dict | None = None          # accepted but ignored - the server always re-validates


class ValidateRequest(ClaimRequest):
    pass