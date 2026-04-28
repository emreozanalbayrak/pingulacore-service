"""
Pre-flight rule consistency checker.

Compares template YAML declarations against hardcoded rules in batch_validator.py
to catch conflicts before an LLM call is spent on a doomed-to-fail generation.

Usage:
    python -m agentic.tools.rule_consistency_check --template <yaml_path>
    python -m agentic.tools.rule_consistency_check --glob "templates/4sinif/bolum6/*_{kolay,orta,zor}.yaml"

Exit codes:
    0 - all checks OK
    1 - WARNs only (non-blocking)
    2 - at least one FAIL (blocking)
"""

from __future__ import annotations

import argparse
import glob as _glob
import re
import sys
from pathlib import Path
from typing import Any

import yaml

# Hardcoded allowed-negative words for <u> tag (mirrors batch_validator.py rule)
NEGATIVE_U_WORDS: set[str] = {
    "olamaz", "değildir", "yoktur", "beklenemez",
    "çıkarılamaz", "söylenemez", "bulunmaz", "getirilemez",
    "yer almaz", "değil", "yapılamaz", "olmaz",
    "ulaşılamaz", "yer verilmemiştir", "verilmemiştir",
    "kullanılmamıştır",
}

# Turkish negation suffixes — any <u>X</u> whose word ends with these is accepted as negative.
NEGATION_SUFFIXES: tuple[str, ...] = (
    "maz", "mez", "mamıştır", "memiştir", "miyor", "mıyor",
    "mıyorum", "miyorum", "memiş", "mamış",
)

FORBIDDEN_HTML_TAGS: set[str] = {"ol", "li", "ul", "div", "span", "p", "strong", "em"}

ALLOWED_HTML_TAGS: set[str] = {"b", "u", "br"}


class Finding:
    __slots__ = ("level", "message")

    def __init__(self, level: str, message: str) -> None:
        self.level = level  # "OK" | "WARN" | "FAIL"
        self.message = message

    def __str__(self) -> str:
        return f"[{self.level}] {self.message}"


def _extract_u_phrases(text: str) -> list[str]:
    return re.findall(r"<u>\s*([^<]+?)\s*</u>", text, flags=re.IGNORECASE)


def _find_forbidden_tags(text: str) -> list[str]:
    tags = re.findall(r"</?\s*([a-zA-Z][a-zA-Z0-9]*)\b", text)
    return [t.lower() for t in tags if t.lower() in FORBIDDEN_HTML_TAGS]


def _iter_stems(template: dict) -> list[str]:
    stems = template.get("soru_kokleri") or template.get("question_stems") or []
    out: list[str] = []
    for s in stems:
        if isinstance(s, str):
            out.append(s)
        elif isinstance(s, dict):
            v = s.get("pattern") or s.get("text") or ""
            if v:
                out.append(v)
    return out


def _get_nested(d: dict, *keys: str, default: Any = None) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def check_template(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        with open(path, encoding="utf-8") as f:
            tpl = yaml.safe_load(f) or {}
    except Exception as e:
        return [Finding("FAIL", f"{path.name}: YAML parse error: {e}")]

    stems = _iter_stems(tpl)

    # 1. <u> tag usage — must wrap an allowed negative word (or negation suffix)
    for stem in stems:
        for phrase in _extract_u_phrases(stem):
            phrase_norm = phrase.strip().lower()
            has_listed = any(neg in phrase_norm for neg in NEGATIVE_U_WORDS)
            has_suffix = any(
                w.endswith(sfx)
                for w in phrase_norm.split()
                for sfx in NEGATION_SUFFIXES
            )
            if not (has_listed or has_suffix):
                findings.append(Finding(
                    "FAIL",
                    f"{path.name}: stem'de <u>{phrase}</u> negatif kelime listesinde degil "
                    f"(batch_validator hardcoded negatif kelime/eklerinden biri bekleniyor)"
                ))

    # 2. Forbidden HTML tags in stems
    for stem in stems:
        bad = _find_forbidden_tags(stem)
        if bad:
            findings.append(Finding(
                "FAIL",
                f"{path.name}: stem'de yasak tag'ler: {set(bad)}. "
                f"Sadece {sorted(ALLOWED_HTML_TAGS)} kullanilabilir."
            ))

    # 3. Option count consistency
    fmt = tpl.get("format", {}) or {}
    opts = fmt.get("options", {}) or {}
    opt_count = opts.get("count")
    if opt_count is not None:
        if opt_count not in (3, 4, 5):
            findings.append(Finding(
                "FAIL",
                f"{path.name}: options.count={opt_count} desteklenmiyor (3/4/5 bekleniyor)"
            ))

    # 4. Paragraph required vs PDF-heavy validation checks
    paragraph_required = _get_nested(fmt, "paragraph", "required", default=True)
    if paragraph_required is False:
        # Inverse template — PDF-dependent checks may be noisy
        findings.append(Finding(
            "WARN",
            f"{path.name}: paragraph.required=false (inverse). "
            f"accuracy/curriculum_alignment PDF check'leri faydali olmayabilir."
        ))

    # 5. Option word-count range vs length-balance hardcoded rule
    wmin = _get_nested(opts, "word_count_min")
    wmax = _get_nested(opts, "word_count_max")
    if isinstance(wmin, int) and isinstance(wmax, int) and wmin > 0:
        spread_ratio = wmax / wmin if wmin else 0
        if spread_ratio >= 2.5:
            findings.append(Finding(
                "WARN",
                f"{path.name}: options word range {wmin}-{wmax} (spread x{spread_ratio:.1f}) "
                f"genis. Hardcoded length-balance >%20 kurali retry tetikleyebilir."
            ))

    # 6. Style vs completeness conflict
    style = opts.get("style")
    if style == "roman_numeral_combination":
        # Hardcoded validator expects complete sentences often — flag informational
        findings.append(Finding(
            "WARN",
            f"{path.name}: options.style=roman_numeral_combination. "
            f"Hardcoded 'complete sentence' kontrolleri bypass edilmeli (validator zaten farkinda)."
        ))

    # 8. Roman numerals ban — 4. sinif sorularinda yalnizca Arap rakamlari. Stem'de
    # veya options.labels icinde Roma rakami (I, II, III, IV, V, VI, VII, VIII, IX, X)
    # veya "I ve II" / "I, II" gibi kombinasyonlar gorulurse FAIL.
    grade = _get_nested(tpl, "meta", "sinif_seviyesi")
    if grade == 4:
        roman_pattern = re.compile(
            r"(?<![A-Za-zÇĞİıÖŞÜçğişöşü])"  # no letter before
            r"(I{1,3}|IV|V|VI{0,3}|IX|X)"     # I..X
            r"(?![A-Za-zÇĞİıÖŞÜçğişöşü])"   # no letter after
        )
        for stem in stems:
            stem_text = re.sub(r"<[^>]+>", "", stem)  # strip HTML for clean scan
            if roman_pattern.search(stem_text):
                findings.append(Finding(
                    "FAIL",
                    f"{path.name}: 4. sinif sorusunda Roma rakami kullanilmis. "
                    f"Sadece Arap rakamlari (1, 2, 3) kullanilabilir."
                ))
                break
        # Option labels also checked
        labels = opts.get("labels") or []
        if any(isinstance(l, str) and roman_pattern.fullmatch(l.strip()) for l in labels):
            findings.append(Finding(
                "FAIL",
                f"{path.name}: options.labels icinde Roma rakami var. "
                f"4. sinif sorulari Arap rakami kullanmali."
            ))
        if opts.get("style") == "roman_numeral_combination":
            findings.append(Finding(
                "FAIL",
                f"{path.name}: options.style=roman_numeral_combination. "
                f"4. sinif Arap rakami zorunlu."
            ))

    # 7. Character name Ozan ban — check only stems/examples (not rule-description text
    # that may legitimately say "Ozan ismini kullanma" as a forbidden_rule)
    for stem in stems:
        if re.search(r"\bOzan\b", stem):
            findings.append(Finding(
                "FAIL",
                f"{path.name}: soru kokunde 'Ozan' ismi gecti — hardcoded yasak."
            ))
            break

    if not findings:
        findings.append(Finding("OK", f"{path.name}: tum kontroller gecti"))

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="YAML <-> batch_validator tutarlilik kontrolu")
    parser.add_argument("--template", type=str, help="Tek YAML yolu")
    parser.add_argument("--glob", type=str, help="Glob pattern (ornek: 'templates/4sinif/bolum6/*_kolay.yaml')")
    parser.add_argument("--quiet", action="store_true", help="Sadece WARN/FAIL goster")
    args = parser.parse_args()

    paths: list[Path] = []
    if args.template:
        paths.append(Path(args.template))
    if args.glob:
        paths.extend(Path(p) for p in _glob.glob(args.glob))

    if not paths:
        print("Hata: --template veya --glob gerekli", file=sys.stderr)
        return 2

    max_level = "OK"
    for p in paths:
        if not p.exists():
            print(f"[FAIL] {p}: dosya bulunamadi")
            max_level = "FAIL"
            continue
        for finding in check_template(p):
            if args.quiet and finding.level == "OK":
                continue
            print(finding)
            if finding.level == "FAIL":
                max_level = "FAIL"
            elif finding.level == "WARN" and max_level != "FAIL":
                max_level = "WARN"

    if max_level == "FAIL":
        return 2
    if max_level == "WARN":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
