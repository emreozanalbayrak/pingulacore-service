"""
3D geometrik cisim sorulari icin deterministik sahne modeli.

Bu model 2D geometri motorundaki polygon/grid temsilinden ayridir. Amac,
ilkokul duzeyindeki kup, prizma, silindir ve kure gibi cisimleri tek ana gorsel
icinde net, sayilabilir ve secenek panelleri halinde render etmektir.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


SolidKind = Literal[
    "cube",
    "rectangular_prism",
    "square_prism",
    "triangular_prism",
    "cylinder",
    "sphere",
]

PanelLayout = Literal["vertical_stack", "side_by_side", "loose_group"]


class Solid3DObject(BaseModel):
    """Tek bir 3D cisim temsilidir.

    Boyutlar soyut birimdir; renderer bunlari cocuk dostu izometrik SVG
    formlarina cevirir.
    """

    kind: SolidKind
    color: str = Field(default="#60A5FA", description="Ana govde rengi")
    width_units: float = Field(default=1.0, ge=0.6, le=2.8)
    height_units: float = Field(default=1.0, ge=0.6, le=2.8)
    depth_units: float = Field(default=1.0, ge=0.5, le=2.4)
    x_offset_units: float = Field(
        default=0.0,
        ge=-2.0,
        le=2.0,
        description="Panel merkezine gore yatay kaydirma",
    )


class Solid3DPanel(BaseModel):
    """Ana gorseldeki bir secenek veya tek yapi paneli."""

    label: str = Field(default="", max_length=3)
    layout: PanelLayout = "vertical_stack"
    solids: list[Solid3DObject] = Field(default_factory=list, min_length=1, max_length=8)

    @field_validator("label")
    @classmethod
    def _normalize_label(cls, value: str) -> str:
        return (value or "").strip().upper()


class Solid3DScene(BaseModel):
    """Deterministik 3D cisim sahnesi.

    `panels` secenekleri tek ana gorselde gostermek icin kullanilir. Ayrik sik
    gorselleri bu motorda uretilmez.
    """

    background_color: str = "#F8FAFC"
    paper_color: str = "#FFFFFF"
    accent_color: str = "#CBD5E1"
    panels: list[Solid3DPanel] = Field(default_factory=list, min_length=1, max_length=5)
    theme_object: Optional[str] = Field(
        default=None,
        max_length=80,
        description="Soru baglamindaki ana nesne/urun. Final estetikte hafif tema ipucu icin kullanilir.",
    )
    place_hint: Optional[str] = Field(
        default=None,
        max_length=80,
        description="Sahnenin gectigi mekan hissi: masaustu, atolye, sinif, sergileme alani vb.",
    )
    material_hint: Optional[str] = Field(
        default=None,
        max_length=80,
        description="Cisimlerin hissi: ahsap blok, plastik materyal, karton maket vb.",
    )
    scenario_hint: Optional[str] = Field(default=None, max_length=80)
    notes: Optional[str] = Field(default=None, max_length=160)

    @field_validator("scenario_hint", mode="before")
    @classmethod
    def _shorten_scenario_hint(cls, value: object) -> object:
        if value is None:
            return None
        text = " ".join(str(value).split()).strip()
        if len(text) <= 80:
            return text

        shortened = text[:80].rstrip(" ,;:-")
        last_stop = max(shortened.rfind("."), shortened.rfind(","), shortened.rfind(";"))
        if last_stop >= 40:
            shortened = shortened[:last_stop].rstrip(" ,;:-")
        return shortened
