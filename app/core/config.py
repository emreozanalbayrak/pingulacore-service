from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _load_dotenv_file(root_dir: Path) -> None:
    """
    Lightweight .env loader.
    - Does not override existing process env vars.
    - Supports plain KEY=VALUE and `export KEY=VALUE`.
    """
    dotenv_path = root_dir / ".env"
    if not dotenv_path.exists() or not dotenv_path.is_file():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    database_url: str
    yaml_primary_dir: Path
    yaml_fallback_dir: Path
    output_dir: Path
    catalog_dir: Path
    runs_dir: Path

    question_max_retries: int
    layout_max_retries: int
    html_max_retries: int
    image_max_retries: int
    rule_eval_parallelism: int
    rule_eval_max_rules: int

    use_stub_agents: bool

    legacy_geo_yaml_dir: Path
    legacy_turkce_templates_dir: Path
    legacy_turkce_meb_books_dir: Path
    legacy_turkce_data_dir: Path
    legacy_turkce_configs_dir: Path
    legacy_turkce_konular_dir: Path
    legacy_uploads_dir: Path
    legacy_state_dir: Path
    legacy_timeout_seconds: int

    auth_token_ttl_hours: int
    password_min_length: int
    signup_enabled: bool
    admin_seed_email: str | None
    admin_seed_password: str | None


def build_settings() -> Settings:
    root_dir = Path(__file__).resolve().parents[2]
    _load_dotenv_file(root_dir)

    primary_yaml = root_dir / "legacy_app" / "geometri" / "ortak"
    fallback_yaml = root_dir / "old" / "ortak"
    output_dir = root_dir / "generated_assets"
    catalog_dir = root_dir / "catalog"
    runs_dir = root_dir / "runs"

    database_url = os.getenv("DATABASE_URL", f"sqlite:///{root_dir / 'service.db'}")

    gemini_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")

    # PydanticAI's Google provider expects GOOGLE_API_KEY.
    # If user configured only GEMINI_API_KEY, mirror it. Drop the duplicate so the
    # google-genai SDK doesn't emit a warning on every client init.
    if gemini_key and not os.getenv("GOOGLE_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = gemini_key
    if os.getenv("GOOGLE_API_KEY") and os.getenv("GEMINI_API_KEY"):
        os.environ.pop("GEMINI_API_KEY", None)

    use_stub_default = not (gemini_key or anthropic_key)

    def _path_or_none(env: str) -> Path | None:
        raw = os.getenv(env)
        return Path(raw) if raw else None

    return Settings(
        root_dir=root_dir,
        database_url=database_url,
        yaml_primary_dir=Path(os.getenv("YAML_PRIMARY_DIR", str(primary_yaml))),
        yaml_fallback_dir=Path(os.getenv("YAML_FALLBACK_DIR", str(fallback_yaml))),
        output_dir=Path(os.getenv("ASSET_OUTPUT_DIR", str(output_dir))),
        catalog_dir=Path(os.getenv("CATALOG_DIR", str(catalog_dir))),
        runs_dir=Path(os.getenv("RUNS_DIR", str(runs_dir))),
        question_max_retries=_as_int(os.getenv("QUESTION_MAX_RETRIES"), 3),
        layout_max_retries=_as_int(os.getenv("LAYOUT_MAX_RETRIES"), 3),
        html_max_retries=_as_int(os.getenv("HTML_MAX_RETRIES"), 3),
        image_max_retries=_as_int(os.getenv("IMAGE_MAX_RETRIES"), 2),
        rule_eval_parallelism=_as_int(os.getenv("RULE_EVAL_PARALLELISM"), 4),
        rule_eval_max_rules=_as_int(os.getenv("RULE_EVAL_MAX_RULES"), 12),
        use_stub_agents=_as_bool(os.getenv("AI_USE_STUB"), use_stub_default),
        legacy_geo_yaml_dir=Path(os.getenv("LEGACY_GEO_YAML_DIR", str(root_dir / "legacy_app" / "geometri" / "ortak"))),
        legacy_turkce_templates_dir=Path(os.getenv("LEGACY_TURKCE_TEMPLATES_DIR", str(root_dir / "legacy_app" / "kadir_hoca" / "templates"))),
        legacy_turkce_meb_books_dir=Path(os.getenv("LEGACY_TURKCE_MEB_BOOKS_DIR", str(root_dir / "meb_books"))),
        legacy_turkce_data_dir=Path(os.getenv("LEGACY_TURKCE_DATA_DIR", str(root_dir / "data"))),
        legacy_turkce_configs_dir=Path(os.getenv("LEGACY_TURKCE_CONFIGS_DIR", str(root_dir / "legacy_app" / "kadir_hoca" / "configs"))),
        legacy_turkce_konular_dir=Path(os.getenv("LEGACY_TURKCE_KONULAR_DIR", str(root_dir / "legacy_app" / "kadir_hoca" / "konular"))),
        legacy_uploads_dir=Path(os.getenv("LEGACY_UPLOADS_DIR", str(root_dir / ".legacy_uploads"))),
        legacy_state_dir=Path(os.getenv("LEGACY_STATE_DIR", str(root_dir / ".legacy_state"))),
        legacy_timeout_seconds=_as_int(os.getenv("LEGACY_TIMEOUT_SECONDS"), 1800),
        auth_token_ttl_hours=_as_int(os.getenv("AUTH_TOKEN_TTL_HOURS"), 168),
        password_min_length=_as_int(os.getenv("PASSWORD_MIN_LENGTH"), 8),
        signup_enabled=_as_bool(os.getenv("SIGNUP_ENABLED"), True),
        admin_seed_email=(os.getenv("ADMIN_EMAIL") or None),
        admin_seed_password=(os.getenv("ADMIN_PASSWORD") or None),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = build_settings()
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    settings.catalog_dir.mkdir(parents=True, exist_ok=True)
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    settings.legacy_state_dir.mkdir(parents=True, exist_ok=True)
    settings.legacy_uploads_dir.mkdir(parents=True, exist_ok=True)
    return settings
