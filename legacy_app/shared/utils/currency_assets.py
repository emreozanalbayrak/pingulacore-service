"""
Türk Lirası referans görsel yükleyicisi.

YAML'da `context.generation.real_currency: true` bayrağı aktifse bu modül
`assets/turk_lirasi/manifest.yaml`'ı okuyup istenen para birimlerini PIL.Image
olarak döndürür. chain_generate_image bu görselleri Gemini image modeline
multimodal input olarak geçirir.
"""
from __future__ import annotations

import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml
from PIL import Image


class CurrencyAssetError(RuntimeError):
    """Referans görsel bulunamadığında veya bozuk olduğunda fırlatılır."""


_ASSETS_ROOT = Path(__file__).resolve().parent.parent / "assets" / "turk_lirasi"
_MANIFEST_PATH = _ASSETS_ROOT / "manifest.yaml"


@lru_cache(maxsize=1)
def _load_manifest() -> dict[str, dict[str, Any]]:
    """Manifest'i yükler ve id → entry dict'ine dönüştürür."""
    if not _MANIFEST_PATH.exists():
        raise CurrencyAssetError(
            f"Manifest bulunamadı: {_MANIFEST_PATH}. "
            "assets/turk_lirasi/ klasörünü README'deki gibi kur."
        )

    with open(_MANIFEST_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    entries = data.get("para_birimleri") or []
    by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        denom_id = entry.get("id")
        if not denom_id:
            continue
        by_id[str(denom_id)] = entry

    if not by_id:
        raise CurrencyAssetError(
            f"Manifest boş veya bozuk: {_MANIFEST_PATH}"
        )
    return by_id


def list_denomination_ids() -> list[str]:
    """Manifest'teki tüm mevcut para birimi id'lerini döndürür."""
    return sorted(_load_manifest().keys())


def get_asset_path(denomination_id: str) -> Path:
    """Verilen id için PNG dosya yolunu döndürür (dosyanın varlığını da kontrol eder)."""
    manifest = _load_manifest()
    entry = manifest.get(denomination_id)
    if entry is None:
        available = ", ".join(sorted(manifest.keys()))
        raise CurrencyAssetError(
            f"Manifest'te '{denomination_id}' id'si yok. Mevcut: {available}"
        )

    rel_path = entry.get("dosya")
    if not rel_path:
        raise CurrencyAssetError(
            f"Manifest kaydı eksik (dosya alanı yok): {denomination_id}"
        )

    path = _ASSETS_ROOT / rel_path
    if not path.exists():
        raise CurrencyAssetError(
            f"Referans görsel bulunamadı: {path}. "
            f"README'yi takip ederek '{denomination_id}' için PNG ekle."
        )
    return path


def load_reference_images(
    denomination_ids: list[str],
) -> list[tuple[str, Image.Image]]:
    """Verilen id listesindeki para birimleri için (id, PIL.Image) çiftleri döndürür.

    Sırayı korur. Dosya bulunamazsa veya RGBA olmayan bir PNG ise
    CurrencyAssetError fırlatır.
    """
    if not denomination_ids:
        return []

    loaded: list[tuple[str, Image.Image]] = []
    for denom_id in denomination_ids:
        path = get_asset_path(denom_id)
        try:
            img = Image.open(path)
            img.load()
        except Exception as exc:
            raise CurrencyAssetError(
                f"Referans görsel açılamadı ({denom_id}): {path} — {exc}"
            ) from exc
        loaded.append((denom_id, img))
    return loaded


@lru_cache(maxsize=64)
def _upload_and_wait_active(path_str: str, mtime_ns: int):
    """Dosyayi Gemini Files API'ya yukler, ACTIVE state'ini bekler, cache'ler.

    Cache keyi: mutlak path + mtime_ns. Dosya degisirse otomatik yeniden yuklenir.
    mtime_ns parametresi cache invalidation icin sinyaldir; fonksiyon kullanmaz.
    """
    # Import local to avoid circular dependency (utils.llm also uses utils)
    from legacy_app.shared.utils.llm import get_image_client

    client = get_image_client()
    uploaded = client.files.upload(file=path_str)

    # Wait for ACTIVE state (PROCESSING → ACTIVE typically 1-3 seconds)
    deadline = time.monotonic() + 60.0
    while uploaded.state and uploaded.state.name == "PROCESSING":
        if time.monotonic() > deadline:
            raise CurrencyAssetError(
                f"Referans gorsel ACTIVE state'e gecmedi (60s timeout): {path_str}"
            )
        time.sleep(1)
        uploaded = client.files.get(name=uploaded.name)

    if uploaded.state and uploaded.state.name not in {"ACTIVE", "SUCCEEDED"}:
        raise CurrencyAssetError(
            f"Referans gorsel yuklenemedi ({path_str}): state={uploaded.state.name}"
        )
    return uploaded


def upload_reference_files(denomination_ids: list[str]) -> list[tuple[str, Any]]:
    """Referans gorselleri Gemini Files API'ye yukler ve (id, uploaded_file) ciftleri doner.

    Uploaded file objeleri client.models.generate_content(contents=[...]) icine
    dogrudan eklenebilir; SDK URI-tabanli referans olarak gecirir.

    PIL.Image inline yaklasimina gore avantajlari:
      - Base64 inline icin her cagrida yeniden kodlanmaz
      - Gemini server'da 48h persistent; retry'lerde yeniden yuklenmez
      - Cok gorselli prompt'larda daha guvenilir

    Dosya degisirse (mtime_ns) cache invalidate olur.
    """
    if not denomination_ids:
        return []

    uploaded_list: list[tuple[str, Any]] = []
    for denom_id in denomination_ids:
        path = get_asset_path(denom_id)
        stat = path.stat()
        uploaded = _upload_and_wait_active(str(path.resolve()), stat.st_mtime_ns)
        uploaded_list.append((denom_id, uploaded))
    return uploaded_list


def build_reference_block(denomination_ids: list[str]) -> str:
    """Prompt'a eklenecek referans görsel açıklama bloğunu oluşturur.

    Gemini multimodal input'ta görseller ek olarak geçirilir; bu metin model'e
    görsellerin ne olduğunu ve nasıl kullanması gerektiğini söyler.
    """
    if not denomination_ids:
        return ""

    manifest = _load_manifest()
    lines = [
        "## REFERANS TÜRK LİRASI GÖRSELLERİ (KRİTİK)",
        "",
        "Aşağıda ekli referans görseller gerçek Türk Lirası banknot ve madeni paralarıdır.",
        "Sahne içinde yer alan paraları bu referanslara BİREBİR sadık kalarak çiz:",
        "- Atatürk portresi aynı konumda ve aynı stilde olmalı",
        "- Banknot arka plan deseni, filigran ve renk kodu aynı kalmalı",
        "- Rakam yazı tipi, büyüklüğü ve konumu referansla eşleşmeli",
        "- Madeni paraların kenar dokusu, simge ve yazıları aynı olmalı",
        "- Paraları yeniden tasarlama, yalnızca sahnenin içine doğal bir şekilde yerleştir",
        "- Referansların hiçbir detayını icat ederek değiştirme veya süsleme",
        "",
        "Ekli referans sırası:",
    ]
    for idx, denom_id in enumerate(denomination_ids, start=1):
        entry = manifest.get(denom_id, {})
        aciklama = entry.get("aciklama", denom_id)
        lines.append(f"  {idx}. {aciklama} (id: {denom_id})")

    return "\n".join(lines)


def resolve_required_denominations(
    required: Optional[list[str]],
) -> list[str]:
    """YAML'dan gelen required_denominations listesini doğrular ve normalize eder.

    None veya boş liste → CurrencyAssetError (real_currency=true ama id yoksa açıkça hata).
    Bilinmeyen id varsa → CurrencyAssetError.
    """
    if not required:
        raise CurrencyAssetError(
            "real_currency=true ayarlanmış ama required_denominations boş. "
            "Hangi para birimlerinin referans alınacağı YAML'da açıkça belirtilmeli."
        )

    manifest = _load_manifest()
    unknown = [d for d in required if d not in manifest]
    if unknown:
        available = ", ".join(sorted(manifest.keys()))
        raise CurrencyAssetError(
            f"Bilinmeyen para birimi id('leri): {unknown}. Mevcut: {available}"
        )
    return list(required)
