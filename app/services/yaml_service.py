from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.core.config import get_settings


def resolve_yaml_path(filename: str) -> Path:
    settings = get_settings()
    primary = settings.yaml_primary_dir / filename
    if primary.exists() and primary.is_file():
        return primary

    fallback = settings.yaml_fallback_dir / filename
    if fallback.exists() and fallback.is_file():
        return fallback

    raise FileNotFoundError(
        f"YAML bulunamadı: {filename}. Aranan dizinler: {settings.yaml_primary_dir}, {settings.yaml_fallback_dir}"
    )


def load_yaml_file(filename: str) -> dict[str, Any]:
    path = resolve_yaml_path(filename)
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError("YAML üst seviye dict olmalı")
    return data
