"""Server-side environment configuration for local and hosted execution."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent


def load_local_environment(env_file: Path | None = None) -> bool:
    """Load a project .env without replacing OS or hosting environment values."""
    path = Path(env_file) if env_file is not None else PROJECT_ROOT / ".env"
    if not path.is_file():
        return False
    return bool(load_dotenv(dotenv_path=path, override=False))


def environment_flag(name: str, true_values: set[str]) -> bool:
    """Return whether a project environment flag is explicitly enabled."""
    return os.getenv(name, "").strip().casefold() in true_values


def running_unittest_command(argv: list[str] | None = None) -> bool:
    """Detect ``python -m unittest`` from its command entry point, not imports."""
    arguments = sys.argv if argv is None else argv
    if not arguments:
        return False
    entry_point = Path(arguments[0])
    return (
        entry_point.name.casefold() == "__main__.py"
        and entry_point.parent.name.casefold() == "unittest"
    )


LIVE_TEST_REQUESTED = (
    environment_flag("RUN_GEMINI_LIVE_TESTS", {"true"})
    or environment_flag("RUN_LIVE_ABENA_TTS", {"1", "true"})
)
TEST_MODE_REQUESTED = environment_flag("AGRIBOT_TEST_MODE", {"1", "true"})
ORDINARY_UNIT_TEST_RUN = (
    (TEST_MODE_REQUESTED or running_unittest_command())
    and not LIVE_TEST_REQUESTED
)

# Ordinary automated tests must remain deterministic and must never consume
# live API quota merely because a developer has a local .env file. The
# explicitly opted-in live test is the sole exception.
LOCAL_ENV_LOADED = (
    False if ORDINARY_UNIT_TEST_RUN else load_local_environment()
)
