from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
PROJECT_ENV_FILES = (".env", ".env.local")


def parse_env_file(path: Path) -> dict[str, str]:
    payload: dict[str, str] = {}
    if not path.exists():
        return payload

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            payload[key] = value
    return payload


def load_project_env(project_root: Path | None = None, *, override: bool = False) -> dict[str, str]:
    root = Path(project_root) if project_root is not None else PROJECT_ROOT
    loaded: dict[str, str] = {}
    for filename in PROJECT_ENV_FILES:
        env_path = root / filename
        for key, value in parse_env_file(env_path).items():
            loaded[key] = value
            if override or key not in os.environ:
                os.environ[key] = value
    return loaded


def get_project_env(name: str, default: str | None = None, *, project_root: Path | None = None) -> str | None:
    load_project_env(project_root)
    return os.getenv(name, default)
