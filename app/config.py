"""All configuration comes from environment / .env. Properties are read lazily so tests can monkeypatch."""
import logging
import os

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
JWT_TTL_SECONDS = 2 * 60 * 60
OTP_MAX_ATTEMPTS = 5
OTP_LOCK_SECONDS = 10 * 60
DEMO_OTP = "123456"


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    @property
    def database_url(self) -> str:
        return os.getenv("DATABASE_URL", "sqlite:///claimsaathi.db")

    @property
    def demo_mode(self) -> bool:
        return _bool("DEMO_MODE", True)

    @property
    def require_auth(self) -> bool:
        return _bool("REQUIRE_AUTH", False)

    @property
    def otp_ttl_seconds(self) -> int:
        try:
            return int(os.getenv("OTP_TTL_SECONDS", "300"))
        except ValueError:
            return 300

    @property
    def jwt_secret(self) -> str:
        secret = os.getenv("JWT_SECRET")
        if not secret:
            logging.getLogger(__name__).warning("JWT_SECRET not set - using insecure development secret!")
            return "dev-only-insecure-secret-change-me-please-0123456789"
        return secret

    @property
    def otp_provider(self) -> str:
        return os.getenv("OTP_PROVIDER", "console").strip().lower()

    # ---------------- AI providers ----------------
    @property
    def anthropic_api_key(self) -> str:
        return os.getenv("ANTHROPIC_API_KEY", "").strip()

    @property
    def claude_model(self) -> str:
        return os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")

    @property
    def gemini_api_key(self) -> str:
        return os.getenv("GEMINI_API_KEY", "").strip()

    
    @property
    def gemini_model(self) -> str:
        return os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest").strip()

    @property
    def gemini_source_label(self) -> str:
        return os.getenv("GEMINI_SOURCE_LABEL", "gemini").strip() or "gemini"

    @property
    def ai_provider(self) -> str:
        """'anthropic' | 'gemini' | 'none'. AI_PROVIDER=auto picks whichever key is set (Anthropic first)."""
        pref = os.getenv("AI_PROVIDER", "auto").strip().lower()
        has_gemini = bool(self.gemini_api_key)
        has_claude = False
        if self.anthropic_api_key:
            try:
                import anthropic  # noqa: F401
                has_claude = True
            except ImportError:
                pass
        if pref == "gemini":
            return "gemini" if has_gemini else "none"
        if pref in ("anthropic", "claude"):
            return "anthropic" if has_claude else "none"
        return "anthropic" if has_claude else "gemini" if has_gemini else "none"

    @property
    def ai_enabled(self) -> bool:
        return self.ai_provider != "none"


settings = Settings()