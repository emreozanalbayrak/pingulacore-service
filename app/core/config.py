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

    s3_endpoint_url: str
    s3_access_key: str
    s3_secret_key: str
    s3_region: str
    s3_catalog_bucket: str
    s3_generated_bucket: str
    s3_rendered_bucket: str

    question_max_retries: int
    layout_max_retries: int
    html_max_retries: int
    image_max_retries: int
    rule_eval_parallelism: int
    rule_eval_max_rules: int

    use_stub_agents: bool


def build_settings() -> Settings:
    root_dir = Path(__file__).resolve().parents[2]
    _load_dotenv_file(root_dir)

    primary_yaml = root_dir / "ortak"
    fallback_yaml = root_dir / "old" / "ortak"
    output_dir = root_dir / "generated_assets"
    catalog_dir = root_dir / "catalog"
    runs_dir = root_dir / "runs"

    database_url = os.getenv("DATABASE_URL", f"sqlite:///{root_dir / 'service.db'}")

    gemini_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")

    # PydanticAI's Google provider expects GOOGLE_API_KEY.
    # If user configured only GEMINI_API_KEY, mirror it for compatibility.
    if gemini_key and not os.getenv("GOOGLE_API_KEY"):
        os.environ.setdefault("GOOGLE_API_KEY", gemini_key)

    use_stub_default = not (gemini_key or anthropic_key)

    return Settings(
        root_dir=root_dir,
        database_url=database_url,
        yaml_primary_dir=Path(os.getenv("YAML_PRIMARY_DIR", str(primary_yaml))),
        yaml_fallback_dir=Path(os.getenv("YAML_FALLBACK_DIR", str(fallback_yaml))),
        output_dir=Path(os.getenv("ASSET_OUTPUT_DIR", str(output_dir))),
        catalog_dir=Path(os.getenv("CATALOG_DIR", str(catalog_dir))),
        runs_dir=Path(os.getenv("RUNS_DIR", str(runs_dir))),
        s3_endpoint_url=os.getenv("S3_ENDPOINT_URL", "http://localhost:9000"),
        s3_access_key=os.getenv("S3_ACCESS_KEY", "pingula"),
        s3_secret_key=os.getenv("S3_SECRET_KEY", "pingula-secret"),
        s3_region=os.getenv("S3_REGION", "us-east-1"),
        s3_catalog_bucket=os.getenv("S3_BUCKET_CATALOG", "catalog-assets"),
        s3_generated_bucket=os.getenv("S3_BUCKET_GENERATED", "generated-assets"),
        s3_rendered_bucket=os.getenv("S3_BUCKET_RENDERED", "rendered-outputs"),
        question_max_retries=_as_int(os.getenv("QUESTION_MAX_RETRIES"), 3),
        layout_max_retries=_as_int(os.getenv("LAYOUT_MAX_RETRIES"), 3),
        html_max_retries=_as_int(os.getenv("HTML_MAX_RETRIES"), 3),
        image_max_retries=_as_int(os.getenv("IMAGE_MAX_RETRIES"), 2),
        rule_eval_parallelism=_as_int(os.getenv("RULE_EVAL_PARALLELISM"), 4),
        rule_eval_max_rules=_as_int(os.getenv("RULE_EVAL_MAX_RULES"), 12),
        use_stub_agents=_as_bool(os.getenv("AI_USE_STUB"), use_stub_default),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = build_settings()
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    settings.catalog_dir.mkdir(parents=True, exist_ok=True)
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    return settings
