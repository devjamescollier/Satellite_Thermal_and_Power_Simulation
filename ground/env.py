"""Settings from the environment, falling back to the repo's .env file (see .env.example)."""

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def env_var(key, default=None):
    """From the environment, else .env, else default."""
    file_vars = {}
    if ENV_FILE.exists():
        for raw in ENV_FILE.read_text().splitlines():
            k, sep, value = raw.strip().partition("=")
            if sep and not k.startswith("#"):
                file_vars[k] = value.strip().strip('"')
    return os.environ.get(key) or file_vars.get(key) or default
