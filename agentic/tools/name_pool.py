"""
Turkish character name pool with diversity tracking.

Provides diverse Turkish character names for question generation,
preventing repetition of common names like "Kerem", "Elif", "Ali", "Ayse".

Uses least-used-first selection (same pattern as stem_usage).
"""

import json
import logging
import random
from pathlib import Path

logger = logging.getLogger(__name__)

# Cache directory (same as stem_usage)
_CACHE_DIR = Path.home() / ".cache" / "agentic"
_NAME_USAGE_FILE = _CACHE_DIR / "name_usage.json"

# ============================================================================
# NAME POOLS
# ============================================================================

MALE_NAMES = [
    "Emre", "Berk", "Arda", "Kaan", "Yusuf", "Cem", "Burak", "Deniz",
    "Mert", "Hasan", "Selim", "Can", "Umut", "Baran", "Emir", "Eren",
    "Barış", "Efe", "Koray", "Onur", "Serkan", "Tolga",
    "Alp", "Batuhan", "Çağrı", "Furkan", "Görkem", "İlker", "Murat",
    "Tuna", "Volkan", "Çınar", "Ege", "Poyraz", "Rüzgar", "Atlas",
    "Demir", "Toprak",
]

FEMALE_NAMES = [
    "Zeynep", "Defne", "Ecrin", "Ela", "Nehir", "Sude", "Yaren",
    "İrem", "Nazlı", "Azra", "Ceren", "Melis", "Seda", "Gizem",
    "Dilara", "Pınar", "Buse", "Damla", "Eylül", "Simge", "Asya",
    "Duru", "Lina", "Nisa", "Rüya", "Selin", "Şule", "Tuğçe",
    "Yağmur", "Almila", "Beril", "Cansu", "Esra", "Hilal", "İpek",
    "Lale", "Melisa", "Naz", "Öykü", "Beren",
]

# Names to AVOID (too common / overused in generated questions)
OVERUSED_NAMES = {
    "Kerem", "Elif", "Ali", "Ayşe", "Mehmet", "Fatma",
    "Ahmet", "Mustafa", "Emine", "Hüseyin",
}


def _load_usage() -> dict[str, int]:
    """Load name usage counts from cache."""
    if _NAME_USAGE_FILE.exists():
        try:
            return json.loads(_NAME_USAGE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_usage(usage: dict[str, int]) -> None:
    """Save name usage counts to cache."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _NAME_USAGE_FILE.write_text(
        json.dumps(usage, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_diverse_names(
    count: int = 4,
    gender_mix: bool = True,
    exclude: list[str] | None = None,
) -> list[str]:
    """
    Get diverse Turkish character names using least-used-first selection.

    Args:
        count: Number of names to return
        gender_mix: If True, mix male and female names
        exclude: Additional names to exclude

    Returns:
        List of diverse Turkish names
    """
    usage = _load_usage()
    exclude_set = OVERUSED_NAMES.copy()
    if exclude:
        exclude_set.update(exclude)

    if gender_mix and count >= 2:
        # Split roughly evenly between genders
        female_count = count // 2
        male_count = count - female_count

        male_picks = _pick_least_used(MALE_NAMES, male_count, usage, exclude_set)
        female_picks = _pick_least_used(FEMALE_NAMES, female_count, usage, exclude_set)
        selected = male_picks + female_picks
    else:
        all_names = MALE_NAMES + FEMALE_NAMES
        selected = _pick_least_used(all_names, count, usage, exclude_set)

    # Update usage counts
    for name in selected:
        usage[name] = usage.get(name, 0) + 1
    _save_usage(usage)

    # Shuffle to avoid predictable ordering
    random.shuffle(selected)
    logger.debug(f"[NAME_POOL] Selected names: {selected}")
    return selected


def _pick_least_used(
    pool: list[str],
    count: int,
    usage: dict[str, int],
    exclude: set[str],
) -> list[str]:
    """Pick least-used names from pool, excluding specified names."""
    available = [n for n in pool if n not in exclude]
    if not available:
        available = pool  # fallback if all excluded

    # Sort by usage count (ascending), then shuffle ties
    scored = [(usage.get(n, 0), random.random(), n) for n in available]
    scored.sort()

    return [name for _, _, name in scored[:count]]


def get_name_prompt_section(count: int = 4) -> str:
    """
    Get a prompt section with suggested character names.

    Returns a formatted string for inclusion in LLM prompts.
    """
    names = get_diverse_names(count=count, gender_mix=True)
    return (
        f"KARAKTER ISIMLERI: Asagidaki isimlerden SEC veya benzer cesitlikte isim kullan: "
        f"{', '.join(names)}\n"
        f"TEKRAR YASAK: Kerem, Elif, Ali, Ayse, Mehmet, Fatma gibi sik kullanilan isimleri KULLANMA!"
    )


def reset_name_usage() -> None:
    """Clear name usage tracking."""
    if _NAME_USAGE_FILE.exists():
        _NAME_USAGE_FILE.unlink()
    logger.info("[NAME_POOL] Name usage reset")
