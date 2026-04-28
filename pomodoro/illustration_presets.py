"""
LLM scene prompt'u icin ipuclari:
- Tematik renk paleti onerileri (paper/grid/polygon renkleri)
- Cismi andiran polygon silueti ornekleri

ESKI SVG illustration fragment'leri KALDIRILDI (Katman 4). Atmosfer arka plani
Katman 5'te Gemini Image raster uretimi ile saglanacak — scene.ambient_image_prompt
alani uzerinden.

Bu dosya sadece LLM'in prompt'a bakarak tutarli palet ve siluet sec kolayligi
icin referans verisi tutar. Renderer bu dosyaya DOKUNMAZ.
"""
from __future__ import annotations

from typing import TypedDict


class PaletteSuggestion(TypedDict):
    theme_label: str
    paper_colors: list[str]
    grid_colors: list[str]
    polygon_fills: list[str]
    polygon_strokes: list[str]
    silhouette_examples: list[dict]


PALETTES: dict[str, PaletteSuggestion] = {
    "workshop": {
        "theme_label": "Tamir Atolyesi / Aletler",
        "paper_colors": ["#FEF7ED", "#FEE4BD", "#FFF7E1"],
        "grid_colors": ["#9A5A2D", "#78350F", "#A16207"],
        "polygon_fills": ["#FED7AA", "#FECACA", "#FDE68A"],
        "polygon_strokes": ["#7C2D12", "#991B1B", "#A16207"],
        "silhouette_examples": [
            {"name": "tornavida", "desc": "Dikey ince gövde + üst sap",
             "vertices": [[3,1],[4,1],[4,5],[5,5],[5,7],[2,7],[2,5],[3,5]]},
            {"name": "cekic", "desc": "Uzun sap + üst T-kafa",
             "vertices": [[3,1],[4,1],[4,5],[6,5],[6,7],[1,7],[1,5],[3,5]]},
            {"name": "anahtar", "desc": "Uzun somun anahtar silueti",
             "vertices": [[1,3],[6,3],[6,4],[7,4],[7,5],[6,5],[6,6],[1,6]]},
        ],
    },
    "kitchen": {
        "theme_label": "Mutfak / Yemek",
        "paper_colors": ["#FEF9E7", "#FFF4E6", "#F5E6D3"],
        "grid_colors": ["#C2410C", "#92400E"],
        "polygon_fills": ["#FECACA", "#FDE68A", "#FED7AA"],
        "polygon_strokes": ["#991B1B", "#78350F"],
        "silhouette_examples": [
            {"name": "tepsi", "desc": "Genis dikdortgen",
             "vertices": [[1,2],[8,2],[8,5],[1,5]]},
            {"name": "tencere", "desc": "Geniş alt + iki kulak cikinti",
             "vertices": [[1,4],[2,4],[2,5],[1,5],[1,6],[7,6],[7,5],[6,5],[6,4],[7,4],[7,1],[1,1]]},
        ],
    },
    "garden": {
        "theme_label": "Bahce / Park",
        "paper_colors": ["#F0FDF4", "#ECFCCB", "#F7FEE7"],
        "grid_colors": ["#15803D", "#65A30D", "#84CC16"],
        "polygon_fills": ["#BBF7D0", "#D9F99D", "#FEF08A"],
        "polygon_strokes": ["#166534", "#3F6212", "#854D0E"],
        "silhouette_examples": [
            {"name": "duz_parsel", "desc": "Dikdortgen bahce parseli",
             "vertices": [[2,1],[8,1],[8,5],[2,5]]},
            {"name": "L_parsel", "desc": "L-sekilli bahce",
             "vertices": [[1,1],[6,1],[6,3],[4,3],[4,5],[1,5]]},
            {"name": "yaprak_5gen", "desc": "Yaprak benzeri 5-gen",
             "vertices": [[2,1],[6,1],[7,3],[5,5],[3,5],[1,3]]},
        ],
    },
    "classroom": {
        "theme_label": "Sinif / Okul",
        "paper_colors": ["#EFF6FF", "#F0F9FF", "#F8FAFC"],
        "grid_colors": ["#1E40AF", "#0369A1", "#475569"],
        "polygon_fills": ["#BFDBFE", "#DBEAFE", "#E0E7FF"],
        "polygon_strokes": ["#1E40AF", "#312E81"],
        "silhouette_examples": [
            {"name": "kitap", "desc": "Kitap silueti",
             "vertices": [[1,1],[7,1],[7,5],[1,5]]},
            {"name": "cetvel", "desc": "Uzun yatay dikdortgen",
             "vertices": [[1,3],[9,3],[9,4],[1,4]]},
        ],
    },
    "ocean": {
        "theme_label": "Deniz / Havuz / Göl",
        "paper_colors": ["#F0F9FF", "#ECFEFF", "#E0F2FE"],
        "grid_colors": ["#0369A1", "#0E7490", "#1E40AF"],
        "polygon_fills": ["#BAE6FD", "#A5F3FC", "#BFDBFE"],
        "polygon_strokes": ["#075985", "#155E75"],
        "silhouette_examples": [
            {"name": "havuz", "desc": "Dikdortgen havuz",
             "vertices": [[2,2],[8,2],[8,5],[2,5]]},
            {"name": "gemi_alt", "desc": "Gemi tabani trapezoid",
             "vertices": [[2,1],[8,1],[7,3],[3,3]]},
        ],
    },
    "forest": {
        "theme_label": "Orman / Dag",
        "paper_colors": ["#F0FDF4", "#ECFDF5", "#F7FEE7"],
        "grid_colors": ["#166534", "#15803D", "#3F6212"],
        "polygon_fills": ["#BBF7D0", "#D9F99D", "#A7F3D0"],
        "polygon_strokes": ["#14532D", "#166534"],
        "silhouette_examples": [
            {"name": "kamp_alani", "desc": "5-gen arazi",
             "vertices": [[1,1],[7,1],[8,3],[6,5],[2,5]]},
            {"name": "yaprak", "desc": "Yaprak silueti",
             "vertices": [[3,1],[5,1],[6,3],[5,5],[3,5],[2,3]]},
        ],
    },
    "sports_field": {
        "theme_label": "Spor Sahasi",
        "paper_colors": ["#F0FDF4", "#ECFDF5"],
        "grid_colors": ["#FFFFFF", "#E5E7EB"],
        "polygon_fills": ["#BBF7D0", "#FEF3C7"],
        "polygon_strokes": ["#166534", "#92400E"],
        "silhouette_examples": [
            {"name": "saha_dikdortgen", "desc": "Dikdortgen saha",
             "vertices": [[1,1],[9,1],[9,5],[1,5]]},
        ],
    },
    "neutral": {
        "theme_label": "Notrel / Sade",
        "paper_colors": ["#F8FAFC", "#FAFAF9"],
        "grid_colors": ["#94A3B8", "#64748B"],
        "polygon_fills": ["#BFDBFE", "#BBF7D0", "#FECACA", "#FDE68A"],
        "polygon_strokes": ["#1E3A8A", "#166534", "#991B1B", "#854D0E"],
        "silhouette_examples": [],
    },
}


def palette_summary_for_prompt() -> str:
    lines = ["Tematik palet onerileri (senaryoya gore sec):"]
    for key, pal in PALETTES.items():
        papers = ",".join(pal["paper_colors"][:2])
        fills = ",".join(pal["polygon_fills"][:2])
        lines.append(f"- {key} ({pal['theme_label']}): paper={papers}; polygon_fill={fills}")
    return "\n".join(lines)


def silhouette_examples_for_prompt() -> str:
    lines = ["Polygon silueti ornekleri (senaryo cismini andiran vertex dizileri):"]
    for key, pal in PALETTES.items():
        sils = pal.get("silhouette_examples") or []
        if not sils:
            continue
        lines.append(f"### {pal['theme_label']} ({key}):")
        for s in sils:
            lines.append(f"  - {s['name']}: {s['desc']} → vertices={s['vertices']}")
    return "\n".join(lines)
