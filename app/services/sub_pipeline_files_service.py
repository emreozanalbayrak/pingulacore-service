from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from app.core.config import get_settings
from app.schemas.domain import LayoutPlan, QuestionSpec

SpKind = Literal["q_json", "layout", "q_html"]
StoredJsonKind = Literal["q_json", "layout"]
ExplorerRoot = Literal["runs", "sp_files"]
_FAVORITES_FILE = ".stored_json_favorites.json"
_PATH_FAVORITES_KEY = "path_favorites"


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


def _favorites_path() -> Path:
    return _root_dir() / _FAVORITES_FILE


def _read_favorites_raw() -> dict[str, Any]:
    path = _favorites_path()
    if not path.exists() or not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    return raw


def _write_favorites_raw(payload: dict[str, Any]) -> None:
    path = _favorites_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


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


def _read_favorites_payload() -> dict[str, list[str]]:
    raw = _read_favorites_raw()

    out: dict[str, list[str]] = {}
    for key, value in raw.items():
        if key not in {"q_json", "layout"}:
            continue
        if not isinstance(value, list):
            continue
        valid_items: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            token = Path(item)
            if token.is_absolute() or ".." in token.parts or token.name != item:
                continue
            valid_items.append(token.name)
        out[key] = valid_items
    return out


def _write_favorites_payload(payload: dict[str, list[str]]) -> None:
    raw = _read_favorites_raw()
    clean: dict[str, list[str]] = {}
    for key in ("q_json", "layout"):
        values = payload.get(key, [])
        uniq = sorted({Path(name).name for name in values if isinstance(name, str)})
        clean[key] = uniq
    raw.update(clean)
    _write_favorites_raw(raw)


def get_stored_json_favorite(kind: StoredJsonKind, filename: str) -> bool:
    token = Path(filename)
    if token.is_absolute() or ".." in token.parts or token.name != filename:
        raise ValueError("Geçersiz dosya adı")
    payload = _read_favorites_payload()
    return token.name in set(payload.get(kind, []))


def set_stored_json_favorite(kind: StoredJsonKind, filename: str, is_favorite: bool) -> None:
    token = Path(filename)
    if token.is_absolute() or ".." in token.parts or token.name != filename:
        raise ValueError("Geçersiz dosya adı")

    payload = _read_favorites_payload()
    values = set(payload.get(kind, []))
    if is_favorite:
        values.add(token.name)
    else:
        values.discard(token.name)
    payload[kind] = sorted(values)
    _write_favorites_payload(payload)


def _safe_relative_path(path: str) -> str:
    token = Path(path)
    if token.is_absolute() or ".." in token.parts or token.name == "":
        raise ValueError("Geçersiz dosya yolu")
    return str(token).replace("\\", "/")


def get_path_favorite(root: ExplorerRoot, path: str) -> bool:
    safe_path = _safe_relative_path(path)
    raw = _read_favorites_raw()
    path_favorites = raw.get(_PATH_FAVORITES_KEY)
    if not isinstance(path_favorites, dict):
        return False
    values = path_favorites.get(root, [])
    if not isinstance(values, list):
        return False
    return safe_path in {str(item) for item in values if isinstance(item, str)}


def set_path_favorite(root: ExplorerRoot, path: str, is_favorite: bool) -> None:
    safe_path = _safe_relative_path(path)
    raw = _read_favorites_raw()
    path_favorites = raw.get(_PATH_FAVORITES_KEY)
    if not isinstance(path_favorites, dict):
        path_favorites = {}

    current_values = path_favorites.get(root, [])
    values = {str(item) for item in current_values if isinstance(item, str)}
    if is_favorite:
        values.add(safe_path)
    else:
        values.discard(safe_path)

    path_favorites[root] = sorted(values)
    raw[_PATH_FAVORITES_KEY] = path_favorites
    _write_favorites_raw(raw)
