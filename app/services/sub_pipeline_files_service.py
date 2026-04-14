from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from app.core.config import get_settings
from app.schemas.domain import LayoutPlan, QuestionSpec

SpKind = Literal["q_json", "layout", "q_html"]


def _safe_token(value: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9_.-]+", "_", (value or "").strip())
    return token.strip("._") or "item"


def _root_dir() -> Path:
    return get_settings().root_dir / "sp_files"


def _kind_dir(kind: SpKind) -> Path:
    root = _root_dir()
    target = root / kind
    target.mkdir(parents=True, exist_ok=True)
    return target


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _safe_path(kind: SpKind, filename: str) -> Path:
    token = Path(filename)
    if token.is_absolute() or ".." in token.parts or token.name != filename:
        raise ValueError("Geçersiz dosya adı")
    return _kind_dir(kind) / token.name


def list_files(kind: SpKind) -> list[str]:
    folder = _kind_dir(kind)
    items = [path.name for path in folder.iterdir() if path.is_file()]
    return sorted(items, reverse=True)


def read_json_file(kind: Literal["q_json", "layout"], filename: str) -> dict[str, Any]:
    path = _safe_path(kind, filename)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(filename)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON üst seviye dict olmalı")
    return data


def read_html_file(filename: str) -> str:
    path = _safe_path("q_html", filename)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(filename)
    return path.read_text(encoding="utf-8")


def write_question_file(question: QuestionSpec, *, sub_pipeline_id: str) -> str:
    qid = _safe_token(question.question_id)
    sid = _safe_token(sub_pipeline_id)
    filename = f"{_timestamp()}_{sid}_{qid}.question.json"
    path = _kind_dir("q_json") / filename
    path.write_text(json.dumps(question.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    return filename


def write_layout_file(layout: LayoutPlan, *, sub_pipeline_id: str) -> str:
    qid = _safe_token(layout.question_id or "no_question_id")
    sid = _safe_token(sub_pipeline_id)
    filename = f"{_timestamp()}_{sid}_{qid}.layout.json"
    path = _kind_dir("layout") / filename
    path.write_text(json.dumps(layout.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    return filename


def write_html_file(html_payload: dict[str, Any], *, sub_pipeline_id: str, question_id: str | None = None) -> str:
    sid = _safe_token(sub_pipeline_id)
    qid = _safe_token(question_id or "no_question_id")
    filename = f"{_timestamp()}_{sid}_{qid}.question.html"
    html_content = str(html_payload.get("html_content") or "")
    path = _kind_dir("q_html") / filename
    path.write_text(html_content, encoding="utf-8")
    return filename
