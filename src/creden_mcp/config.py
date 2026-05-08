"""Environment / configuration loading."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _load_env() -> None:
    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        load_dotenv(cwd_env)
    else:
        load_dotenv()


@dataclass(frozen=True)
class Settings:
    email: str | None
    password: str | None
    base_url: str
    request_delay: float
    default_lang: str
    session_file: Path

    @classmethod
    def from_env(cls) -> "Settings":
        _load_env()
        return cls(
            email=os.getenv("CREDEN_EMAIL"),
            password=os.getenv("CREDEN_PASSWORD"),
            base_url=os.getenv("CREDEN_BASE_URL", "https://data.creden.co").rstrip("/"),
            request_delay=float(os.getenv("CREDEN_REQUEST_DELAY", "1.5")),
            default_lang=os.getenv("CREDEN_DEFAULT_LANG", "th"),
            session_file=Path(os.getenv("CREDEN_SESSION_FILE", ".creden_session.json")),
        )

    def require_credentials(self) -> tuple[str, str]:
        if not self.email or not self.password:
            raise RuntimeError(
                "CREDEN_EMAIL and CREDEN_PASSWORD must be set in environment or .env file"
            )
        return self.email, self.password
