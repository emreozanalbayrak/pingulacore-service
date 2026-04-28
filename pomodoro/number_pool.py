"""
Nesne ve sayı çeşitliliği için pool, claim ve geçmiş yönetimi.
Thread/process-safe: fcntl.LOCK_EX.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import random
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(os.environ["LEGACY_STATE_DIR"]) if os.environ.get("LEGACY_STATE_DIR") else Path(__file__).resolve().parent.parent
_DEFAULT_HISTORY_FILE = _PROJECT_ROOT / ".number_pool_history.json"


def _pool_key(yaml_path: str | Path) -> str:
    return Path(yaml_path).stem


def _claim_rotating_index(
    yaml_path: str | Path,
    slot: str,
    n: int,
    history_file: Path | None = None,
) -> int:
    """Genel amacli round-robin index claim (0..n-1). Thread-safe."""
    history_path = history_file or _DEFAULT_HISTORY_FILE
    key = f"{_pool_key(yaml_path)}__{slot}"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(history_path, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                fh.seek(0); content = fh.read().strip()
                state = json.loads(content) if content else {}
            except (json.JSONDecodeError, ValueError):
                state = {}
            last = state.get(key, {}).get("last", -1)
            nxt = (last + 1) % n
            state[key] = {"last": nxt, "updated_at": datetime.now().isoformat(timespec="seconds")}
            fh.seek(0); fh.truncate()
            json.dump(state, fh, ensure_ascii=False, indent=2)
            fcntl.flock(fh, fcntl.LOCK_UN)
            return nxt
    except OSError:
        return 0


# ---------------------------------------------------------------------------
# Nesne havuzu ve claim
# ---------------------------------------------------------------------------

# Turkce, 2. sinif duzeyine uygun, gorsel olarak kolayca sayilabilir nesneler.
# Her kategori ayri grupta — cesitlilik icin havuzda karsik tutulur.
OBJECT_POOL_BY_CATEGORY: dict[str, list[str]] = {
    "meyveler": [
        "elma", "muz", "armut", "çilek", "kiraz", "şeftali", "kayısı", "erik",
        "karpuz", "kavun", "üzüm", "nar", "limon", "portakal", "mandalina",
        "incir", "hurma", "ananas", "kivi", "ahududu", "dut", "muşmula",
        "ayva", "trabzon hurması", "yenidünya",
    ],
    "sebzeler": [
        "domates", "havuç", "patates", "biber", "kabak", "patlıcan", "salatalık",
        "soğan", "sarımsak", "mısır", "bezelye", "fasulye", "brokoli", "ıspanak",
        "pazı", "pancar", "turp", "pırasa", "kereviz", "enginar",
        "sarı kabak", "kırmızı lahana", "taze soğan", "maydanoz demeti",
    ],
    "kırtasiye": [
        "kalem", "silgi", "defter", "cetvel", "boya kalemi", "makas", "zımba",
        "pergel", "iletki", "raptiye", "tebeşir", "yapıştırıcı", "renkli kağıt",
        "dosya", "klasör", "lastik bant", "ataş", "tükenmez kalem", "fosforlu kalem",
        "bant rulosu", "karton parçası", "kalem kılıfı", "açı ölçer",
    ],
    "spor_oyuncak": [
        "futbol topu", "basketbol topu", "voleybol topu", "tenis topu", "masa tenisi topu",
        "hentbol topu", "golf topu",
        "oyuncak araba", "tahta blok", "zar", "satranç taşı", "yapboz parçası",
        "atlama ipi", "yo-yo", "misket", "karo taş", "tahta kule parçası",
        "dart oku", "bilardo topu", "badminton topu",
        "su tabancası", "fırıldak", "kum torbası",
    ],
    "müzik_aleti": [
        "davul", "gitar", "keman", "flüt", "kastanyet", "trompet", "zil",
        "marakas", "üçgen", "akordeon", "bağlama", "ut", "ksilofon çubuğu",
        "tef", "zurna", "klarnet", "ritim çubuğu", "bongo",
    ],
    "ev_mutfak": [
        "fincan", "tabak", "kaşık", "bardak", "şişe", "kase", "çatal",
        "tencere", "tava", "ölçek bardak", "kavanoz", "kutu", "tepsi", "mum",
        "çay bardağı", "salata kasesi", "çorba kasesi", "tuzluk", "biberlik",
        "yumurta kabı", "ekmek sepeti",
    ],
    "doğa_koleksiyon": [
        "deniz kabuğu", "çakıl taşı", "yaprak", "tohum", "kozalak",
        "çiçek", "dal parçası", "taş kristali", "kelebek figürü",
        "düz taş", "kurumuş yaprak", "meşe palamudu",
        "lavanta dalı", "mantar dilimi", "amber taşı",
    ],
    "hayvan_figürü": [
        "kedi figürü", "kuş figürü", "balık figürü", "tavşan figürü",
        "kurbağa figürü", "fil figürü", "zürafa figürü", "penguen figürü",
        "arı figürü", "salyangoz figürü", "köpek figürü", "at figürü",
        "aslan figürü", "timsah figürü", "kaplumbağa figürü", "panda figürü",
        "tilki figürü", "kartal figürü", "yunus figürü",
    ],
    "giysi_aksesuar": [
        "çorap", "eldiven", "şapka", "atkı", "kemer", "düğme", "bilezik",
        "yüzük", "broş", "klips", "iplik yumağı",
        "kravat", "papyon", "kafa bandı",
    ],
    "yiyecek_tatlı": [
        "kurabiye", "ekmek dilimi", "sandviç", "şeker", "çikolata",
        "gofret", "kraker", "kek dilimi", "lokum", "muffin",
        "marshmallow", "dondurma külahı", "waffle parçası", "beze",
        "karamel küpü",
    ],
    "atölye_hobi": [
        "pul", "manyetik kart", "renkli boncuk", "bilye", "lego parçası",
        "iplik yumağı", "düğme", "origami kağıdı", "mozaik parçası",
        "boya tüpü", "fırça", "kil topu", "maket parçası",
        "tahta küp", "tahta çubuk", "bez parçası", "seramik karo",
    ],
    "araç_modeli": [
        "oyuncak tren vagonu", "oyuncak gemi", "oyuncak uçak",
        "minyatür otomobil", "minyatür kamyon", "minyatür bisiklet",
        "minyatür itfaiye", "minyatür traktör",
        "yelkenli gemi modeli",
    ],
    "alet_araç": [
        "tornavida", "çekiç", "anahtar", "pense", "metre şerit",
        "kerpeten", "zımpara kağıdı", "çivi", "vida", "somun",
    ],
    "bahçe_tarım": [
        "çiçek tohumu paketi", "fide saksısı", "sulama kabı", "bahçe küreği",
        "saksı", "bahçe eldiveni", "bitki etiketi",
        "çim tohumu torbası",
    ],
    "laboratuvar_bilim": [
        "deney tüpü", "petri kabı", "büyüteç",
        "pil", "mıknatıs", "termometre",
        "prizma", "renk filtresi", "cam boncuk",
    ],
    "diğer": [
        "renkli kart", "manyetik mıknatıs", "sticker", "rozet",
        "madalya", "jeton", "sicim parçası",
        "kartpostal", "kum saati", "anahtarlık", "pusula",
    ],
}

# Duz liste (geri uyumluluk)
OBJECT_POOL: list[str] = [
    obj for objs in OBJECT_POOL_BY_CATEGORY.values() for obj in objs
]

# Kategori sirasi (rotasyon icin)
_CATEGORY_ORDER: list[str] = list(OBJECT_POOL_BY_CATEGORY.keys())

_DEFAULT_OBJECT_CLAIM_FILE = _PROJECT_ROOT / ".object_claim_history.json"


def claim_object_suggestion(
    yaml_path: str | Path,
    history_file: Path | None = None,
) -> str:
    """YAML icin bir sonraki nesneyi secer — kategori round-robin + iceride rastgele.

    Art arda cagrimlarda farkli kategorilerden nesne gelir.
    Kategori tum nesneleri tukenmeden baska kategoriye gecmez.
    Thread/process-safe: fcntl.LOCK_EX.
    """
    history_path = history_file or _DEFAULT_OBJECT_CLAIM_FILE
    key = _pool_key(yaml_path)
    history_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(history_path, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                fh.seek(0)
                content = fh.read().strip()
                state = json.loads(content) if content else {}
            except (json.JSONDecodeError, ValueError):
                state = {}

            entry = state.get(key, {})
            last_cat_idx = entry.get("last_cat_idx", -1)
            used_per_cat: dict[str, list[str]] = entry.get("used_per_cat", {})

            # Siradaki kategoriyi bul (mevcut kategoride bitmemis nesne olabilir)
            n_cats = len(_CATEGORY_ORDER)
            next_cat_idx = (last_cat_idx + 1) % n_cats
            cat_name = _CATEGORY_ORDER[next_cat_idx]
            cat_objects = OBJECT_POOL_BY_CATEGORY[cat_name]
            used_in_cat = set(used_per_cat.get(cat_name, []))
            remaining = [o for o in cat_objects if o not in used_in_cat]

            if not remaining:
                # Bu kategori bitti, sifirla
                used_in_cat = set()
                remaining = list(cat_objects)
                used_per_cat[cat_name] = []

            selected = random.choice(remaining)
            used_in_cat.add(selected)
            used_per_cat[cat_name] = sorted(used_in_cat)

            state[key] = {
                "last_cat_idx": next_cat_idx,
                "last_selected": selected,
                "last_category": cat_name,
                "used_per_cat": used_per_cat,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }

            fh.seek(0)
            fh.truncate()
            json.dump(state, fh, ensure_ascii=False, indent=2)
            fcntl.flock(fh, fcntl.LOCK_UN)

            return selected

    except OSError:
        logger.warning("Nesne claim dosyasina erisilemedi: %s", history_path)
        return random.choice(OBJECT_POOL)


# ---------------------------------------------------------------------------
# Sayi gecmisi (post-hoc: LLM uretimden sonra kayit, sonraki uretimde exclusion)
# ---------------------------------------------------------------------------

_DEFAULT_NUMBER_HISTORY_FILE = _PROJECT_ROOT / ".number_history.json"


def register_numbers(
    yaml_path: str | Path,
    numbers: list[int],
    history_file: Path | None = None,
) -> None:
    """Kullanilan sayi setini YAML-stem bazinda gecmise ekler.

    Her uretimin tam sayi seti ayri bir liste olarak saklanir.
    Bireysel sayilar degil, SET bazinda tekrar engellenir.
    Thread-safe (fcntl.LOCK_EX).
    """
    if not numbers:
        return
    clean = sorted({int(n) for n in numbers if isinstance(n, (int, float))})
    if not clean:
        return

    history_path = history_file or _DEFAULT_NUMBER_HISTORY_FILE
    key = _pool_key(yaml_path)
    history_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(history_path, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                fh.seek(0)
                content = fh.read().strip()
                state = json.loads(content) if content else {}
            except (json.JSONDecodeError, ValueError):
                state = {}

            entry = state.get(key, {})
            sets: list[list[int]] = entry.get("sets", [])

            # Ayni set zaten kayitli degilse ekle
            if clean not in sets:
                sets.append(clean)

            state[key] = {
                "sets": sets,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
            fh.seek(0)
            fh.truncate()
            json.dump(state, fh, ensure_ascii=False, indent=2)
            fcntl.flock(fh, fcntl.LOCK_UN)
    except OSError:
        logger.warning("Sayi gecmisi dosyasina yazilamadi: %s", history_path)


def get_excluded_number_sets(
    yaml_path: str | Path,
    history_file: Path | None = None,
) -> list[list[int]]:
    """Bu YAML icin daha once kullanilmis sayi setlerini dondurur."""
    history_path = history_file or _DEFAULT_NUMBER_HISTORY_FILE
    key = _pool_key(yaml_path)
    try:
        with open(history_path, "r", encoding="utf-8") as fh:
            content = fh.read().strip()
        state = json.loads(content) if content else {}
        return state.get(key, {}).get("sets", [])
    except (OSError, json.JSONDecodeError):
        return []


# ---------------------------------------------------------------------------
# Nesne gecmisi (post-hoc kayit — ikincil katman)
# ---------------------------------------------------------------------------

_DEFAULT_OBJECT_HISTORY_FILE = _PROJECT_ROOT / ".object_history.json"


def _object_key(yaml_path: str | Path) -> str:
    return _pool_key(yaml_path)


def register_objects(
    yaml_path: str | Path,
    objects: list[str],
    history_file: Path | None = None,
) -> None:
    """Uretimde kullanilan nesneleri gecmis dosyasina ekler. Thread-safe."""
    if not objects:
        return

    history_path = history_file or _DEFAULT_OBJECT_HISTORY_FILE
    key = _object_key(yaml_path)
    history_path.parent.mkdir(parents=True, exist_ok=True)

    normalized = [o.strip().lower() for o in objects if o.strip()]
    if not normalized:
        return

    try:
        with open(history_path, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                fh.seek(0)
                content = fh.read().strip()
                state = json.loads(content) if content else {}
            except (json.JSONDecodeError, ValueError):
                state = {}

            existing = set(state.get(key, {}).get("objects", []))
            existing.update(normalized)

            state[key] = {
                "objects": sorted(existing),
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }

            fh.seek(0)
            fh.truncate()
            json.dump(state, fh, ensure_ascii=False, indent=2)
            fcntl.flock(fh, fcntl.LOCK_UN)

    except OSError:
        logger.warning("Nesne gecmisi dosyasina yazilamadi: %s", history_path)


def get_excluded_objects(
    yaml_path: str | Path,
    history_file: Path | None = None,
) -> list[str]:
    """Bu key icin daha once kullanilmis nesneleri dondurur."""
    history_path = history_file or _DEFAULT_OBJECT_HISTORY_FILE
    key = _object_key(yaml_path)

    try:
        with open(history_path, "r", encoding="utf-8") as fh:
            content = fh.read().strip()
        state = json.loads(content) if content else {}
        return state.get(key, {}).get("objects", [])
    except (OSError, json.JSONDecodeError):
        return []



# ---------------------------------------------------------------------------
# Gecmis temizleme
# ---------------------------------------------------------------------------

_ALL_HISTORY_FILES = [
    _DEFAULT_HISTORY_FILE,           # .number_pool_history.json
    _DEFAULT_NUMBER_HISTORY_FILE,    # .number_history.json
    _DEFAULT_OBJECT_HISTORY_FILE,    # .object_history.json
    _DEFAULT_OBJECT_CLAIM_FILE,      # .object_claim_history.json
    _PROJECT_ROOT / ".variant_rotation.json",
]


def clear_yaml_history(yaml_path: str | Path) -> None:
    """Bir YAML'a ait tum gecmis kayitlarini havuz dosyalarindan siler.

    Yeniden uretim oncesinde cagrilir: onceki uretimin number/object/variant
    gecmisi temizlenir, yeni uretim havuzdan bastan baslar.
    Thread-safe: her dosya icin ayri fcntl lock.
    """
    stem = _pool_key(yaml_path)
    # template_pool_key bazli ek anahtarlar: number_history bunlari da kullanabilir
    # Basit yaklasim: tum dosyalarda stem ile baslayan veya stem'e esit tum keyleri sil

    for history_path in _ALL_HISTORY_FILES:
        if not history_path.exists():
            continue
        try:
            with open(history_path, "a+", encoding="utf-8") as fh:
                fcntl.flock(fh, fcntl.LOCK_EX)
                try:
                    fh.seek(0)
                    content = fh.read().strip()
                    state = json.loads(content) if content else {}
                except (json.JSONDecodeError, ValueError):
                    state = {}

                keys_to_delete = [k for k in state if k == stem or k.startswith(f"{stem}__")]
                for k in keys_to_delete:
                    del state[k]

                if keys_to_delete:
                    fh.seek(0)
                    fh.truncate()
                    json.dump(state, fh, ensure_ascii=False, indent=2)

                fcntl.flock(fh, fcntl.LOCK_UN)
        except OSError:
            logger.warning("Gecmis temizlenemedi: %s", history_path)
