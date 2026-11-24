import logging
import os
from abc import ABC, abstractmethod

from .config import settings

logger = logging.getLogger("claimsaathi.otp")


class OtpProvider(ABC):
    @abstractmethod
    def send(self, phone: str, otp: str, purpose: str) -> None:
        """Deliver the OTP. Raise on failure."""


class ConsoleOtpProvider(OtpProvider):
    """Dev provider: prints the OTP to the server log."""

    def send(self, phone: str, otp: str, purpose: str) -> None:
        msg = f"[OTP] purpose={purpose} phone={phone} otp={otp}"
        logger.info(msg)
        print(msg, flush=True)


class TwilioOtpProvider(OtpProvider):
    """Stub - enable by: pip install twilio, uncomment below, set OTP_PROVIDER=twilio and TWILIO_* env vars."""

    def __init__(self) -> None:
        self.sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.token = os.getenv("TWILIO_AUTH_TOKEN")
        self.from_number = os.getenv("TWILIO_FROM_NUMBER")

    def send(self, phone: str, otp: str, purpose: str) -> None:
        # from twilio.rest import Client
        # client = Client(self.sid, self.token)
        # client.messages.create(
        #     body=f"Your ClaimSaathi OTP is {otp}. Valid for 5 minutes. Do not share it.",
        #     from_=self.from_number,
        #     to=f"+91{phone}",
        # )
        # return
        raise NotImplementedError("TwilioOtpProvider is a stub - see comments in otp_provider.py")


def get_otp_provider() -> OtpProvider:
    return TwilioOtpProvider() if settings.otp_provider == "twilio" else ConsoleOtpProvider()