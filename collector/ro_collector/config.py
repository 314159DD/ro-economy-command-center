"""Environment-based configuration."""
import os
from dataclasses import dataclass
from urllib.parse import urlparse

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    pass


# The FluxCP control panel and wiki of the server being tracked. Both are
# plain env vars so the code carries no server name.
DEFAULT_CP_URL = "https://example.com/cp/"
DEFAULT_WIKI_URL = "https://example.com/wiki/"


def cp_url() -> str:
    return os.environ.get("RO_CP_URL", DEFAULT_CP_URL).rstrip("/") + "/"


def wiki_url() -> str:
    return os.environ.get("RO_WIKI_URL", DEFAULT_WIKI_URL).rstrip("/") + "/"


def cp_domain() -> str:
    return urlparse(cp_url()).hostname or ""


@dataclass(frozen=True)
class Settings:
    session_cookie: str
    database_url: str
    cp_url: str
    wiki_url: str
    char_level: int = 72
    throttle_seconds: float = 2.0


def load_settings() -> Settings:
    load_dotenv()  # no-op if .env absent
    missing = [k for k in ("RO_SESSION_COOKIE", "DATABASE_URL", "RO_CP_URL", "RO_WIKI_URL") if not os.environ.get(k)]
    if missing:
        raise ConfigError(f"Missing required env vars: {', '.join(missing)}")
    return Settings(
        session_cookie=os.environ["RO_SESSION_COOKIE"],
        database_url=os.environ["DATABASE_URL"],
        cp_url=cp_url(),
        wiki_url=wiki_url(),
        char_level=int(os.environ.get("CHAR_LEVEL", "72")),
        throttle_seconds=float(os.environ.get("THROTTLE_SECONDS", "2.0")),
    )
