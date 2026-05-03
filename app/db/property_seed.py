from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.db.database import SessionLocal
from app.db import models


@dataclass(frozen=True)
class PropertySeed:
    defined_at_path: str
    property_key: str
    canonical_path: str
    label: str
    description: str
    data_type: str
    parent_ref: tuple[str, str] | None = None
    constraints: Any | None = None
    is_required: bool = False


def _to_json_text(payload: Any) -> str | None:
    if payload is None:
        return None
    return json.dumps(payload, ensure_ascii=False, default=str)


def _grade_range(start: int, end: int) -> list[int]:
    return list(range(start, end + 1))


def _build_root_property_seeds() -> list[PropertySeed]:
    return [
        PropertySeed(
            defined_at_path="root",
            property_key="ethics_rules",
            canonical_path="ethics_rules",
            label="Etik kurallar",
            description="Soru içeriğinde uyulması gereken etik, güvenlik ve yaş uygunluğu kuralları.",
            data_type="text",
        ),
        PropertySeed(
            defined_at_path="root",
            property_key="visual",
            canonical_path="visual",
            label="Görsel",
            description="Soru üretiminde kullanılan tüm görsel politika ve kısıtların kök nesnesi.",
            data_type="json",
        ),
        PropertySeed(
            defined_at_path="root",
            property_key="exists",
            canonical_path="visual.exists",
            label="Görsel var mı",
            description="Soru çıktısında görsel kullanımının zorunlu olup olmadığını belirtir.",
            data_type="bool",
            parent_ref=("root", "visual"),
        ),
        PropertySeed(
            defined_at_path="root",
            property_key="format_class",
            canonical_path="format_class",
            label="Format class",
            description="Sorunun üst seviye sunum sınıfını belirler.",
            data_type="enum",
            constraints={
                "allowed_values": [
                    "metin-gorsel-soru-secenekler",
                    "gorsel-soru-secenekler",
                    "metin-gorsel-metin-soru-secenekler",
                ]
            },
        ),
        PropertySeed(
            defined_at_path="root",
            property_key="option_count",
            canonical_path="option_count",
            label="Şık sayısı",
            description="Soruda kaç seçenek üretileceğini tanımlar.",
            data_type="number",
            constraints={"min": 2, "max": 6, "example": 4},
        ),
    ]


def _build_grade_property_seeds() -> list[PropertySeed]:
    seeds: list[PropertySeed] = []

    allowed_shape_examples = {
        1: ["daire", "kare", "ucgen", "dikdortgen"],
        2: ["daire", "kare", "ucgen", "dikdortgen", "kup", "silindir", "kure"],
        3: ["daire", "kare", "ucgen", "dikdortgen", "kup", "silindir", "kure", "koni"],
        4: ["daire", "kare", "ucgen", "dikdortgen", "kup", "prizma", "silindir", "kure", "koni"],
        5: ["daire", "kare", "ucgen", "dikdortgen", "cokgen", "kup", "prizma", "silindir", "kure", "koni"],
    }
    for grade in _grade_range(1, 5):
        seeds.append(
            PropertySeed(
                defined_at_path=f"root/grade-{grade}",
                property_key="allowed_shapes",
                canonical_path="visual.allowed_shapes",
                label="Kullanılabilir şekiller",
                description=f"{grade}. sınıf düzeyinde tüm derslerde güvenle kullanılabilecek temel şekil ve cisim kümesi.",
                data_type="array",
                parent_ref=("root", "visual"),
                constraints={"example": allowed_shape_examples[grade]},
            )
        )

    scene_complexity = {
        1: "dusuk",
        2: "dusuk",
        3: "dusuk",
        4: "orta",
        5: "orta",
        6: "orta",
        7: "orta_yuksek",
        8: "orta_yuksek",
    }
    for grade in _grade_range(1, 8):
        seeds.append(
            PropertySeed(
                defined_at_path=f"root/grade-{grade}",
                property_key="scene_complexity",
                canonical_path="visual.scene_complexity",
                label="Görsel sahne karmaşıklığı",
                description=f"{grade}. sınıf sorularında kullanılacak sahnenin görsel kalabalık ve detay seviyesi.",
                data_type="enum",
                parent_ref=("root", "visual"),
                constraints={"allowed_values": ["dusuk", "orta", "orta_yuksek"], "example": scene_complexity[grade]},
            )
        )

    max_object_count = {1: 5, 2: 6, 3: 8, 4: 10}
    for grade in _grade_range(1, 4):
        seeds.append(
            PropertySeed(
                defined_at_path=f"root/grade-{grade}",
                property_key="max_object_count",
                canonical_path="visual.max_object_count",
                label="Maksimum nesne sayısı",
                description=f"{grade}. sınıf için tek bir soru görselinde önerilen üst nesne sınırı.",
                data_type="number",
                parent_ref=("root", "visual"),
                constraints={"min": 1, "max": 20, "example": max_object_count[grade]},
            )
        )

    stem_limits = {1: 90, 2: 110, 3: 140, 4: 170, 5: 200, 6: 220, 7: 240, 8: 260}
    for grade in _grade_range(1, 8):
        seeds.append(
            PropertySeed(
                defined_at_path=f"root/grade-{grade}",
                property_key="max_characters",
                canonical_path="stem.max_characters",
                label="Soru kökü maksimum karakter",
                description=f"{grade}. sınıf düzeyinde soru kökü için önerilen üst karakter sınırı.",
                data_type="number",
                constraints={"min": 20, "max": 400, "example": stem_limits[grade]},
            )
        )

    option_limits = {1: 24, 2: 28, 3: 36, 4: 44, 5: 56, 6: 64, 7: 72, 8: 80}
    for grade in _grade_range(1, 8):
        seeds.append(
            PropertySeed(
                defined_at_path=f"root/grade-{grade}",
                property_key="max_characters",
                canonical_path="option.max_characters",
                label="Şık maksimum karakter",
                description=f"{grade}. sınıf düzeyinde tek bir metin şıkkı için önerilen üst karakter sınırı.",
                data_type="number",
                constraints={"min": 4, "max": 120, "example": option_limits[grade]},
            )
        )

    abstraction_level = {
        1: "somut",
        2: "somut",
        3: "somut",
        4: "somut_karma",
        5: "somut_karma",
        6: "yari_soyut",
        7: "yari_soyut",
        8: "yari_soyut",
        9: "soyut",
        10: "soyut",
        11: "soyut",
        12: "soyut",
    }
    for grade in _grade_range(1, 12):
        seeds.append(
            PropertySeed(
                defined_at_path=f"root/grade-{grade}",
                property_key="abstraction_level",
                canonical_path="abstraction_level",
                label="Soyutlama seviyesi",
                description=f"{grade}. sınıf için soru kurgusunun hedeflediği bilişsel soyutlama seviyesi.",
                data_type="enum",
                constraints={"allowed_values": ["somut", "somut_karma", "yari_soyut", "soyut"], "example": abstraction_level[grade]},
            )
        )

    return seeds


def _build_subject_property_seeds() -> list[PropertySeed]:
    seeds: list[PropertySeed] = []

    number_ranges = {
        1: "0-20",
        2: "0-100",
        3: "0-1000",
        4: "0-10000",
        5: "dogal_sayilar_ve_temel_kesirler",
        6: "tam_sayilar_ve_oranlar",
        7: "rasyonel_sayilar_ve_yuzdeler",
        8: "ustlu_ifadeler_ve_koklu_sayilara_giris",
        9: "gercel_sayilar_ve_cebirsel_gosterimler",
        10: "fonksiyonlar_ve_sayma",
        11: "ileri_fonksiyonlar_ve_trigonometri_oncesi",
        12: "analiz_ve_uygulamalar",
    }
    for grade, example in number_ranges.items():
        seeds.append(
            PropertySeed(
                defined_at_path=f"root/grade-{grade}/{grade}-matematik",
                property_key="number_range",
                canonical_path="math.number_range",
                label="Sayı aralığı",
                description=f"{grade}. sınıf matematik sorularında kullanılacak tipik sayı veya nicelik aralığı.",
                data_type="text",
                constraints={"example": example},
            )
        )

    countable_examples = {
        1: ["elma", "kalem", "top", "boncuk"],
        2: ["kitap", "silgi", "balon", "kutu"],
        3: ["bilye", "meyve", "oyuncak", "etiket"],
        4: ["para", "paket", "bardak", "kart"],
    }
    for grade, example in countable_examples.items():
        seeds.append(
            PropertySeed(
                defined_at_path=f"root/grade-{grade}/{grade}-matematik",
                property_key="countable_object_types",
                canonical_path="visual.countable_object_types",
                label="Sayılabilir nesne türleri",
                description=f"{grade}. sınıf matematik görsellerinde sayma amacıyla kullanılabilecek nesne aileleri.",
                data_type="array",
                parent_ref=(f"root/grade-{grade}", "visual.allowed_shapes"),
                constraints={"example": example},
            )
        )

    turkce_text_types = {
        1: ["kisa_oyku", "diyalog", "gunluk_yasam"],
        2: ["hikaye", "bilgilendirici_metin", "diyalog"],
        3: ["hikaye", "bilimsel_populer_metin", "bilgilendirici_metin"],
        4: ["hikaye", "bilgilendirici_metin", "şiir_uyarlamasi"],
        5: ["hikaye", "makale_parcasi", "bilgilendirici_metin"],
        6: ["hikaye", "deneme_parcasi", "bilgilendirici_metin"],
        7: ["makale_parcasi", "soylesi", "bilgilendirici_metin"],
        8: ["makale_parcasi", "deneme_parcasi", "bilgilendirici_metin"],
        9: ["edebi_parca", "dusunce_yazisi", "bilgilendirici_metin"],
        10: ["edebi_parca", "elestiri_parcasi", "bilgilendirici_metin"],
        11: ["edebi_parca", "fikir_yazisi", "yorumlayici_metin"],
        12: ["edebi_parca", "yorumlayici_metin", "sinav_tipi_metin"],
    }
    for grade, example in turkce_text_types.items():
        seeds.append(
            PropertySeed(
                defined_at_path=f"root/grade-{grade}/{grade}-turkce",
                property_key="text_types",
                canonical_path="turkce.text_types",
                label="Metin türleri",
                description=f"{grade}. sınıf Türkçe/Türk dili dersinde soru kökü veya bağlam için tercih edilebilecek metin türleri.",
                data_type="array",
                constraints={"example": example},
            )
        )

    for grade in _grade_range(1, 4):
        seeds.append(
            PropertySeed(
                defined_at_path=f"root/grade-{grade}/{grade}-turkce",
                property_key="character_scene_allowed",
                canonical_path="visual.character_scene_allowed",
                label="Karakter odaklı sahne kullanılabilir",
                description=f"{grade}. sınıf Türkçe sorularında karakter ve hikâye sahnesi temelli görsel kuruluma izin verir.",
                data_type="bool",
                parent_ref=("root", "visual"),
                constraints={"example": True},
            )
        )

    science_subject_paths = []
    for grade in _grade_range(3, 8):
        science_subject_paths.append(f"root/grade-{grade}/{grade}-fen")
    for grade in _grade_range(9, 12):
        science_subject_paths.extend(
            [
                f"root/grade-{grade}/{grade}-fizik",
                f"root/grade-{grade}/{grade}-kimya",
                f"root/grade-{grade}/{grade}-biyoloji",
            ]
        )

    for path in science_subject_paths:
        label_prefix = path.split("/")[-1]
        seeds.append(
            PropertySeed(
                defined_at_path=path,
                property_key="diagram_allowed",
                canonical_path="visual.diagram_allowed",
                label="Diyagram kullanılabilir",
                description=f"{label_prefix} bağlamındaki sorularda şematik, deneysel veya açıklayıcı diyagram kullanımına izin verir.",
                data_type="bool",
                parent_ref=("root", "visual"),
                constraints={"example": True},
            )
        )
        seeds.append(
            PropertySeed(
                defined_at_path=path,
                property_key="experiment_context_allowed",
                canonical_path="science.experiment_context_allowed",
                label="Deney bağlamı kullanılabilir",
                description=f"{label_prefix} sorularında deney düzeneği, laboratuvar veya gözlem bağlamı kurulabilir.",
                data_type="bool",
                constraints={"example": True},
            )
        )

    history_paths = [
        "root/grade-8/8-tarih",
        "root/grade-9/9-tarih",
        "root/grade-10/10-tarih",
        "root/grade-11/11-tarih",
        "root/grade-12/12-tarih",
    ]
    for path in history_paths:
        seeds.append(
            PropertySeed(
                defined_at_path=path,
                property_key="timeline_allowed",
                canonical_path="visual.timeline_allowed",
                label="Zaman çizelgesi kullanılabilir",
                description="Tarih odaklı sorularda kronolojik akış veya olay sıralama görselleri kullanılabilir.",
                data_type="bool",
                parent_ref=("root", "visual"),
                constraints={"example": True},
            )
        )

    map_paths = [f"root/grade-{grade}/{grade}-sosyal" for grade in _grade_range(4, 7)] + [
        f"root/grade-{grade}/{grade}-cografya" for grade in _grade_range(9, 12)
    ]
    for path in map_paths:
        seeds.append(
            PropertySeed(
                defined_at_path=path,
                property_key="map_allowed",
                canonical_path="visual.map_allowed",
                label="Harita kullanılabilir",
                description="Mekânsal yorum, yön bulma veya bölgesel ilişki kurma için harita temelli görsel kullanılabilir.",
                data_type="bool",
                parent_ref=("root", "visual"),
                constraints={"example": True},
            )
        )

    for grade in _grade_range(10, 11):
        seeds.append(
            PropertySeed(
                defined_at_path=f"root/grade-{grade}/{grade}-felsefe",
                property_key="concept_pairs",
                canonical_path="felsefe.concept_pairs",
                label="Kavram çiftleri",
                description=f"{grade}. sınıf felsefe sorularında birlikte işlenebilecek kavramsal gerilim veya karşıtlık çiftleri.",
                data_type="array",
                constraints={"example": ["adalet-ozgurluk", "bilgi-inanc", "erdem-mutluluk"]},
            )
        )

    for grade in _grade_range(9, 12):
        base_path = f"root/grade-{grade}/{grade}-geometri"
        seeds.append(
            PropertySeed(
                defined_at_path=base_path,
                property_key="drawing_style",
                canonical_path="visual.drawing_style",
                label="Çizim stili",
                description=f"{grade}. sınıf geometri sorularında tercih edilecek diyagram ve çizim dili.",
                data_type="enum",
                parent_ref=("root", "visual"),
                constraints={"allowed_values": ["duz_cizim", "analitik", "sematik"], "example": "duz_cizim"},
            )
        )
        seeds.append(
            PropertySeed(
                defined_at_path=base_path,
                property_key="proof_required",
                canonical_path="geometry.proof_required",
                label="İspat zorunlu mu",
                description=f"{grade}. sınıf geometri sorularında biçimsel ispat beklentisinin devreye girip girmediğini belirtir.",
                data_type="bool",
                constraints={"example": grade >= 10},
            )
        )

    return seeds


def _build_theme_property_seeds(theme_rows: list[models.CurriculumConstantNode]) -> list[PropertySeed]:
    seeds: list[PropertySeed] = []
    for row in theme_rows:
        seeds.append(
            PropertySeed(
                defined_at_path=row.path,
                property_key="focus",
                canonical_path="content.focus",
                label="İçerik odağı",
                description=f'"{row.name}" temasında korunması gereken ana kavramsal odak veya kapsam notu.',
                data_type="text",
                constraints={"example": row.name},
            )
        )
        seeds.append(
            PropertySeed(
                defined_at_path=row.path,
                property_key="recommended_motifs",
                canonical_path="visual.recommended_motifs",
                label="Önerilen görsel motifler",
                description=f'"{row.name}" temasında kullanılabilecek sahne, nesne veya sembol ailelerini tanımlar.',
                data_type="array",
                parent_ref=("root", "visual"),
                constraints={"example": []},
            )
        )
    return seeds


def _load_theme_nodes() -> list[models.CurriculumConstantNode]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(models.CurriculumConstantNode)
                .where(models.CurriculumConstantNode.node_type == "theme")
                .order_by(models.CurriculumConstantNode.path.asc())
            ).all()
        )


def build_property_seed_list() -> list[PropertySeed]:
    theme_rows = _load_theme_nodes()
    return (
        _build_root_property_seeds()
        + _build_grade_property_seeds()
        + _build_subject_property_seeds()
        + _build_theme_property_seeds(theme_rows)
    )


def seed_property_definitions() -> dict[str, int]:
    seeds = build_property_seed_list()

    with SessionLocal() as db:
        nodes_by_path = {
            row.path: row.id
            for row in db.scalars(select(models.CurriculumConstantNode)).all()
        }
        existing_rows = list(db.scalars(select(models.PropertyDefinition)).all())
        existing_by_key = {
            (row.defined_at_curriculum_node_id, row.canonical_path): row
            for row in existing_rows
        }

        created = 0
        updated = 0

        for seed in seeds:
            node_id = nodes_by_path.get(seed.defined_at_path)
            if node_id is None:
                continue

            key = (node_id, seed.canonical_path)
            row = existing_by_key.get(key)
            if row is None:
                row = models.PropertyDefinition(
                    id=str(uuid4()),
                    defined_at_curriculum_node_id=node_id,
                    parent_property_id=None,
                    label=seed.label,
                    description=seed.description,
                    property_key=seed.property_key,
                    canonical_path=seed.canonical_path,
                    data_type=seed.data_type,
                    constraints_json=_to_json_text(seed.constraints),
                    is_required=seed.is_required,
                    is_active=True,
                )
                db.add(row)
                existing_by_key[key] = row
                created += 1
            else:
                row.label = seed.label
                row.description = seed.description
                row.property_key = seed.property_key
                row.canonical_path = seed.canonical_path
                row.data_type = seed.data_type
                row.constraints_json = _to_json_text(seed.constraints)
                row.is_required = seed.is_required
                row.is_active = True
                updated += 1

        db.flush()

        for seed in seeds:
            node_id = nodes_by_path.get(seed.defined_at_path)
            if node_id is None:
                continue
            row = existing_by_key.get((node_id, seed.canonical_path))
            if row is None:
                continue

            parent_id = None
            if seed.parent_ref is not None:
                parent_node_id = nodes_by_path.get(seed.parent_ref[0])
                parent_row = existing_by_key.get((parent_node_id, seed.parent_ref[1])) if parent_node_id else None
                parent_id = parent_row.id if parent_row is not None else None
            row.parent_property_id = parent_id

        db.commit()

    return {"total_seed_specs": len(seeds), "created": created, "updated": updated}


if __name__ == "__main__":
    result = seed_property_definitions()
    print(result)
