"""
Varyant Rotasyon Modulu

Her pipeline calistirmasinda otomatik olarak bir sonraki varyanti secer.
Ust uste calistirmalarda farkli varyantlar dogal olarak sirayla gelir.

State dosyasi: .variant_rotation.json (proje kokunde)
Thread/process-safe: fcntl.flock ile dosya kilidi
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from pomodoro.yaml_loader import ParsedTemplate

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(os.environ["LEGACY_STATE_DIR"]) if os.environ.get("LEGACY_STATE_DIR") else Path(__file__).resolve().parent.parent
_DEFAULT_STATE_FILE = _PROJECT_ROOT / ".variant_rotation.json"


def get_variant_names(template: ParsedTemplate) -> list[str]:
    """ParsedTemplate'ten siralanmis varyant isimlerini cikarir.

    Desteklenen formatlar:
      - Dict-style: varyantlar: {varyant_1: {ad: "..."}, varyant_3: {ad: "..."}}
      - List-style: varyantlar: [{varyant_adi: "..."}, ...]
      - Per-question: context.questions[].varyant_adi
    """
    names: list[str] = []

    # 1) varyant_tanimlari["varyantlar"] — dict-style (Pattern A)
    top_varyantlar = template.varyant_tanimlari.get("varyantlar")
    if isinstance(top_varyantlar, dict):
        for key, val in top_varyantlar.items():
            if isinstance(val, dict):
                names.append(val.get("ad", key))
            else:
                names.append(key)
        if names:
            return names

    # 2) raw YAML'daki varyantlar — list-style (Pattern B)
    raw_varyantlar = template.raw.get("varyantlar") or template.raw.get("varyant")
    if isinstance(raw_varyantlar, list):
        for item in raw_varyantlar:
            if isinstance(item, dict):
                name = item.get("varyant_adi") or item.get("ad") or ""
                if name:
                    names.append(name)
        if names:
            return names

    # 3) Per-question varyant_adi (Pattern C)
    questions = template.context.get("questions", [])
    seen: set[str] = set()
    for q in questions:
        v_name = q.get("varyant_adi") or ""
        if v_name and v_name not in seen:
            names.append(v_name)
            seen.add(v_name)

    return names


def get_variant_details(template: ParsedTemplate, variant_name: str) -> dict[str, Any]:
    """Belirtilen varyant adina ait detaylari ParsedTemplate'ten bulur.

    Senaryo cekirdegi, gorsel notlari, soru koku ornekleri gibi
    zengin verileri dondurur. Bulamazsa bos dict.
    """
    # 1) raw YAML'daki varyantlar — dict-style
    raw_varyantlar = template.raw.get("varyantlar") or template.raw.get("varyant") or {}

    if isinstance(raw_varyantlar, dict):
        for key, val in raw_varyantlar.items():
            if not isinstance(val, dict):
                continue
            if val.get("ad") == variant_name or key == variant_name:
                return dict(val)

    # 2) raw YAML'daki varyantlar — list-style
    if isinstance(raw_varyantlar, list):
        for item in raw_varyantlar:
            if not isinstance(item, dict):
                continue
            item_name = item.get("varyant_adi") or item.get("ad") or ""
            if item_name == variant_name:
                return dict(item)

    # 3) Per-question varyantlar
    for q in template.context.get("questions", []):
        if q.get("varyant_adi") == variant_name:
            return dict(q)
        for v in q.get("varyantlar", []):
            if isinstance(v, dict):
                v_name = v.get("varyant_adi") or v.get("ad") or ""
                if v_name == variant_name:
                    return dict(v)

    return {}


def _yaml_key(yaml_path: str | Path) -> str:
    """YAML dosya yolundan stabil bir state key uretir."""
    return Path(yaml_path).stem


def select_next_variant(
    yaml_path: str | Path,
    available_variants: list[str],
    state_file: Path | None = None,
) -> str:
    """Siradaki varyanti secer ve state dosyasini gunceller.

    Round-robin rotasyon: her cagri bir sonraki varyanti dondurur.
    File lock ile thread/process-safe.
    """
    if not available_variants:
        raise ValueError("available_variants bos olamaz")

    if len(available_variants) == 1:
        return available_variants[0]

    state_path = state_file or _DEFAULT_STATE_FILE
    key = _yaml_key(yaml_path)

    state_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(state_path, "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                fh.seek(0)
                content = fh.read().strip()
                state = json.loads(content) if content else {}
            except (json.JSONDecodeError, ValueError):
                logger.warning("Bozuk state dosyasi, sifirlaniyor: %s", state_path)
                state = {}

            entry = state.get(key, {})
            last_index = entry.get("last_index", -1)
            next_index = (last_index + 1) % len(available_variants)
            selected = available_variants[next_index]

            state[key] = {
                "last_index": next_index,
                "last_variant": selected,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }

            fh.seek(0)
            fh.truncate()
            json.dump(state, fh, ensure_ascii=False, indent=2)

            fcntl.flock(fh, fcntl.LOCK_UN)

    except OSError:
        logger.warning("State dosyasina erisilemedi, ilk varyant seciliyor: %s", state_path)
        selected = available_variants[0]

    return selected
