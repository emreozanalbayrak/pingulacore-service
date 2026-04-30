"""
Deterministic audit helpers for 4th-grade Bolum 6 sentence-insertion templates.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .rule_consistency_check import check_template

BOLUM6_TEMPLATE_GLOB = "legacy_app/kadir_hoca/templates/4sinif/bolum6/paragraf_cumle_ekleme_*_sinif4_*.yaml"

HIGH_RISK_TOPIC_KEYWORDS = {
    "biyoteknoloji",
    "nükleer",
    "nukleer",
    "felsefe",
    "huku",
    "borsa",
    "gen mühendisliği",
    "gen muhendisligi",
    "aydınlanma",
    "aydinlanma",
    "olasılık",
    "olasilik",
    "istatistik",
    "gotik",
    "vasco da gama",
    "medeni kanun",
    "özel uzay şirketleri",
    "ozel uzay sirketleri",
    "klasik siyaset",
}

MEDIUM_RISK_TOPIC_KEYWORDS = {
    "rönesans",
    "ronesans",
    "mimari",
    "coğrafi keşif",
    "cografi kesif",
    "mitoloji",
    "arkeoloji",
    "iklim değişikliği",
    "iklim degisikligi",
    "florence nightingale",
    "mimar sinan",
    "gençlik",
    "genclik",
    "kimlik",
    "teknopark",
    "telif hakkı",
    "telif hakki",
    "dil aileleri",
    "evrim",
}


@dataclass
class TemplateAudit:
    """Audit result for a single template."""

    path: Path
    template_id: str
    position: str
    difficulty: str
    stem_count: int
    errors: list[str]
    warnings: list[str]
    profile: dict[str, Any]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_bolum6_template_paths() -> list[Path]:
    """Return the 9 active Bolum 6 difficulty templates."""
    templates_dir = _project_root() / "templates" / "4sinif" / "bolum6"
    return sorted(
        path
        for path in templates_dir.glob("paragraf_cumle_ekleme_*_sinif4_*.yaml")
        if path.name.endswith(("_kolay.yaml", "_orta.yaml", "_zor.yaml"))
    )


def default_bolum6_topics_path() -> Path:
    return _project_root() / "konular" / "4sinif" / "4_sinif_turkce_bolum6.txt"


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _detect_position(template_id: str) -> str:
    if "_basina_" in template_id:
        return "basina"
    if "_ortaya_" in template_id:
        return "ortaya"
    if "_sonuna_" in template_id:
        return "sonuna"
    return "bilinmiyor"


def _detect_difficulty(template_id: str) -> str:
    if template_id.endswith("_kolay"):
        return "kolay"
    if template_id.endswith("_orta"):
        return "orta"
    if template_id.endswith("_zor"):
        return "zor"
    return "bilinmiyor"


def _minimum_expected_stems(difficulty: str) -> int:
    if difficulty == "zor":
        return 5
    return 4


def _extract_stem_list(template: dict[str, Any]) -> list[str]:
    stems = template.get("soru_kokleri") or []
    result: list[str] = []
    for stem in stems:
        if isinstance(stem, str):
            result.append(stem)
        elif isinstance(stem, dict):
            result.append(stem.get("pattern") or stem.get("text") or "")
    return [stem for stem in result if stem]


def _collect_rule_texts(template: dict[str, Any]) -> str:
    paragraph_rules = template.get("format", {}).get("paragraph", {}).get("kurallar", []) or []
    correct_rules = template.get("dogru_cevap", {}).get("kurallar", []) or []
    strategy_rules = [
        strategy.get("nasil_olusturulur", "")
        for strategy in template.get("celdirici_stratejileri", []) or []
        if isinstance(strategy, dict)
    ]
    return "\n".join(str(item) for item in [*paragraph_rules, *correct_rules, *strategy_rules])


def _has_any(text: str, options: tuple[str, ...]) -> bool:
    return any(option in text for option in options)


def audit_template(path: Path) -> TemplateAudit:
    """Audit a single Bolum 6 template."""
    template = _load_yaml(path)
    template_id = template.get("meta", {}).get("id", path.stem)
    position = _detect_position(template_id)
    difficulty = _detect_difficulty(template_id)
    stems = _extract_stem_list(template)
    rule_text = _collect_rule_texts(template).lower()
    errors: list[str] = []
    warnings: list[str] = []

    required_stems = _minimum_expected_stems(difficulty)
    if len(stems) < required_stems:
        warnings.append(
            f"soru_kokleri onerilen seviyenin altinda: {len(stems)} mevcut, "
            f"{difficulty} icin onerilen en az {required_stems}"
        )

    paragraph_cfg = template.get("format", {}).get("paragraph", {}) or {}
    sentence_min = paragraph_cfg.get("sentence_count_min")
    sentence_max = paragraph_cfg.get("sentence_count_max")
    if paragraph_cfg.get("required") is not True:
        errors.append("format.paragraph.required=true olmali")
    if template.get("format", {}).get("options", {}).get("style") != "complete_sentence":
        errors.append("options.style complete_sentence olmali")
    if template.get("format", {}).get("options", {}).get("count") != 4:
        errors.append("options.count 4 olmali")

    placeholder_expected = {
        "basina": '"----" en basta',
        "ortaya": '"----" ortada',
        "sonuna": '"----" en sonda',
    }.get(position, "")
    role_expected = {
        "basina": "giriş cümlesi",
        "ortaya": "önceki ve sonraki cümle arasında köprü",
        "sonuna": "sonuç cümlesi",
    }.get(position, "")

    placeholder_ok = {
        "basina": _has_any(
            rule_text,
            (
                "en başında",
                "en basinda",
                "paragrafın en başında",
                "paragrafin en basinda",
                "ilk karakter",
                "ilk cümleden önce",
                "ilk cumleden once",
            ),
        ),
        "ortaya": _has_any(rule_text, ("ortasında", "ortasinda", "ne başta ne sonda", "ne basta ne sonda")),
        "sonuna": _has_any(rule_text, ("en sonunda", "son karakter", "en sonda")),
    }.get(position, True)
    role_ok = {
        "basina": _has_any(rule_text, ("giriş cümlesi", "giris cumlesi")),
        "ortaya": _has_any(rule_text, ("önceki", "onceki")) and _has_any(rule_text, ("sonraki",)),
        "sonuna": _has_any(rule_text, ("sonuç cümlesi", "sonuc cumlesi")),
    }.get(position, True)

    if placeholder_expected and not placeholder_ok:
        warnings.append(f"placeholder konumu acik degil: {placeholder_expected}")
    if role_expected and not role_ok:
        warnings.append(f"dogru cevap rolu acik degil: {role_expected}")
    if position == "ortaya" and sentence_min != 4:
        warnings.append("ortaya template'lerinde sentence_count_min genelde 4 olmali")
    if position in {"basina", "sonuna"} and not (3 <= int(sentence_min or 0) <= 4):
        warnings.append("basina/sonuna template'lerinde sentence_count_min 3 veya 4 olmali")
    if sentence_max and sentence_min and int(sentence_max) < int(sentence_min):
        errors.append("sentence_count_max sentence_count_min'den kucuk olamaz")

    consistency_findings = check_template(path)
    for finding in consistency_findings:
        if "options word range" in finding.message:
            continue
        if finding.level == "FAIL":
            errors.append(finding.message)
        elif finding.level == "WARN":
            warnings.append(finding.message)

    profile = {
        "template_id": template_id,
        "position": position,
        "difficulty": difficulty,
        "stem_count": len(stems),
        "required_min_stems": required_stems,
        "paragraph_sentence_range": [sentence_min, sentence_max],
        "paragraph_word_range": [
            paragraph_cfg.get("word_count_min"),
            paragraph_cfg.get("word_count_max"),
        ],
        "placeholder_expected": placeholder_expected,
        "role_expected": role_expected,
        "strategy_count": len(template.get("celdirici_stratejileri", []) or []),
    }
    return TemplateAudit(
        path=path,
        template_id=template_id,
        position=position,
        difficulty=difficulty,
        stem_count=len(stems),
        errors=errors,
        warnings=warnings,
        profile=profile,
    )


def flag_topic_line(line: str) -> dict[str, Any]:
    """Heuristic grade-level audit for a single topic line."""
    raw = line.strip()
    lower = raw.lower()
    status = "uygun"
    reasons: list[str] = []

    if any(keyword in lower for keyword in HIGH_RISK_TOPIC_KEYWORDS):
        status = "elenmeli"
        reasons.append("soyut/ileri kavram riski yuksek")
    elif any(keyword in lower for keyword in MEDIUM_RISK_TOPIC_KEYWORDS):
        status = "sadelestirilmeli"
        reasons.append("konu 4. sinif icin sadelestirme gerektirebilir")

    parts = [part.strip() for part in raw.split("/") if part.strip()]
    if len(raw.split()) > 14 and status == "uygun":
        status = "sadelestirilmeli"
        reasons.append("baslik/aciklama cok uzun")
    if any("'" in part for part in parts) and status == "uygun":
        status = "sadelestirilmeli"
        reasons.append("ozel tarihsel/teknik ad yogunlugu var")

    return {
        "line": raw,
        "status": status,
        "reasons": reasons,
    }


def audit_topics(topics_path: Path) -> list[dict[str, Any]]:
    """Audit the bolum6 topics file."""
    flags: list[dict[str, Any]] = []
    with open(topics_path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            entry = flag_topic_line(stripped)
            entry["line_number"] = lineno
            flags.append(entry)
    return flags


def build_bolum6_audit(
    template_paths: list[Path] | None = None,
    topics_path: Path | None = None,
) -> dict[str, Any]:
    """Build a full audit payload for Bolum 6."""
    template_paths = template_paths or default_bolum6_template_paths()
    topics_path = topics_path or default_bolum6_topics_path()

    audits = [audit_template(path) for path in template_paths]
    topic_flags = audit_topics(topics_path)

    errors = [
        {"template": audit.template_id, "message": message}
        for audit in audits
        for message in audit.errors
    ]
    warnings = [
        {"template": audit.template_id, "message": message}
        for audit in audits
        for message in audit.warnings
    ]

    return {
        "errors": errors,
        "warnings": warnings,
        "template_semantic_profile": {
            audit.template_id: audit.profile
            for audit in audits
        },
        "topic_grade_flags": topic_flags,
        "summary": {
            "template_count": len(audits),
            "error_count": len(errors),
            "warning_count": len(warnings),
            "topic_issue_count": sum(1 for flag in topic_flags if flag["status"] != "uygun"),
        },
    }
