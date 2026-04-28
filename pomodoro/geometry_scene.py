"""
Geometri sorulari icin deterministik sahne grafi modelleri.

LLM'den pixel-level gorsel istemek yerine, yapilandirilmis scene graph istiyoruz.
Scene graph -> SVG renderer tarafindan pixel-perfect cizilir. Boylece:
- Birimkareler esit aralikli ve tam hizali
- Noktalar gride snap'li
- Sekil kenarlari grid cizgilerine birebir oturur
- Opaklik, stroke genisligi, renk deterministik
- Sekil - grid - etiket hepsi TEK koordinat sisteminde

Koordinat sistemi:
- (0,0): grid'in sol-alt kosesi
- +x: saga (sutun yonu)
- +y: yukari (satir yonu)
- Birim: 1 birim = 1 birimkare (hucre)
- Renderer SVG'de y'yi flip eder (SVG top-left origin)

NOT:
SVG primitive'lerle yapilan emoji/scenery/semantic overlay mekanigi kaldirildi.
Raster ambient arka plan kapali; hiz ve netlik icin geometri gorselleri SVG
katmanlariyla uretilir.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Arka plan (grid / noktalı / kesik / yumusak / dusuz)
# ---------------------------------------------------------------------------

class GeometryBackground(BaseModel):
    """Arka plan ızgarasi: kareli, noktali, kesik cizgi, yumusak veya dusuz."""

    type: Literal[
        "unit_square",    # duz surekli cizgi kareli
        "dotted",         # nokta deseni
        "dashed_grid",    # kesik cizgi kareli
        "soft_grid",      # cok acik pastel grid (dusuk opakli)
        "plain",          # grid yok, sadece renkli zemin
    ] = Field(
        description="Grid tipi; grid varsa polygon vertex'leri tam sayi olmali."
    )
    cols: int = Field(ge=1, le=40, description="Yatay hucre sayisi")
    rows: int = Field(ge=1, le=40, description="Dikey hucre sayisi")
    cell_size_px: int = Field(
        default=48, ge=16, le=120,
        description="Bir birimkarenin piksel boyutu"
    )
    grid_color: str = Field(default="#94A3B8", description="Izgara cizgi rengi")
    grid_opacity: float = Field(
        default=0.45, ge=0.1, le=1.0,
        description="Izgara opakligi (sekli kapatmamali)"
    )
    grid_stroke_width: float = Field(
        default=1.0, ge=0.3, le=3.0,
        description="Izgara cizgi kalinligi (px)"
    )
    dot_radius_px: float = Field(
        default=2.2, ge=0.8, le=6.0,
        description="Noktali zeminde nokta yaricapi (px)"
    )
    dot_color: str = Field(default="#64748B")
    dash_pattern: str = Field(
        default="4,3",
        description="dashed_grid icin SVG dasharray deseni"
    )

    paper_color: str = Field(
        default="#FFFFFF",
        description="Acik kagit rengi; beyaz yerine senaryoya uygun hafif ton."
    )

    margin_cells: float = Field(
        default=0.5, ge=0.0, le=2.0,
        description="Izgara disindaki kenar boslugu (hucre cinsinden)"
    )


# ---------------------------------------------------------------------------
# Sekiller (polygon ana primitif)
# ---------------------------------------------------------------------------

class GeometryPolygon(BaseModel):
    """Kapali cokgen. Koseler grid koordinatlarinda (hucre birimli) olmali.

    LLM polygon vertex'lerini senaryodaki cismin SILUETINI andiracak sekilde
    secmelidir (tornavida, cekic, kitap, yaprak vb.).
    """

    vertices: list[tuple[float, float]] = Field(
        description="Sirali koseler; grid varsa tam sayi, en az 3 vertex."
    )
    fill: str = Field(default="#BFDBFE", description="Ic dolgu rengi")
    fill_opacity: float = Field(
        default=0.35, ge=0.0, le=1.0,
        description="Dolgu opakligi; grid gorunur kalsin."
    )
    stroke: str = Field(default="#1E3A8A", description="Kenar rengi")
    stroke_width: float = Field(
        default=2.0, ge=0.5, le=6.0,
        description="Kenar kalinligi (px). 1.5-2.5 onerilir."
    )
    stroke_opacity: float = Field(
        default=1.0, ge=0.2, le=1.0,
        description="Kenar opakligi."
    )
    closed: bool = Field(default=True)

    @field_validator("vertices")
    @classmethod
    def _check_min_vertices(cls, v):
        if len(v) < 3:
            raise ValueError("Polygon en az 3 vertex icermelidir")
        return v


class GeometryLineSegment(BaseModel):
    """Tek bir dogru parcasi (ekseni, olcu cizgisi, bolumlendirme icin)."""

    start: tuple[float, float]
    end: tuple[float, float]
    color: str = "#0F172A"
    stroke_width: float = Field(default=1.5, ge=0.5, le=4.0)
    stroke_opacity: float = Field(default=1.0, ge=0.2, le=1.0)
    dashed: bool = False
    arrow: Literal["none", "start", "end", "both"] = "none"


# ---------------------------------------------------------------------------
# Etiketler
# ---------------------------------------------------------------------------

class GeometryLabel(BaseModel):
    """Grid uzerine konan metin etiketi (harf, sayi, kisa kelime)."""

    pos: tuple[float, float] = Field(description="Grid koordinati")
    text: str = Field(max_length=20)
    color: str = Field(default="#111827")
    font_size_px: int = Field(default=14, ge=8, le=32)
    font_weight: Literal["normal", "bold"] = "normal"

    offset_x_px: int = Field(default=0, ge=-40, le=40)
    offset_y_px: int = Field(default=0, ge=-40, le=40)

    anchor: Literal["start", "middle", "end"] = "middle"


# ---------------------------------------------------------------------------
# Ana sahne
# ---------------------------------------------------------------------------

class GeometryScene(BaseModel):
    """Bir geometri gorselinin tam sahne tanimi.

    Matematik katmani SVG primitive'lerle cizilir. Raster ambient varsayilan
    olarak kapali tutulur.
    """

    background: GeometryBackground
    polygons: list[GeometryPolygon] = Field(default_factory=list)
    segments: list[GeometryLineSegment] = Field(default_factory=list)
    labels: list[GeometryLabel] = Field(default_factory=list)

    # Eski Katman 5 alani. Hiz ve netlik icin null tutulur.
    ambient_image_prompt: Optional[str] = Field(
        default=None,
        description="Raster ambient kapali; null kullan."
    )
    ambient_opacity: float = Field(
        default=0.28,
        ge=0.10,
        le=0.50,
        description="Raster ambient kapaliyken onemsiz.",
    )

    # Meta
    expected_area: Optional[float] = Field(
        default=None,
        description="Cokgenin beklenen alani (birimkare cinsinden). Dogrulama kontrolu."
    )
    scenario_hint: Optional[str] = Field(
        default=None,
        description="Gorseli olusturan senaryo ozeti (orn. 'tamir atolyesi', 'bahce citi')"
    )
    color_theme: Optional[str] = Field(
        default=None,
        description="Kisa renk temasi adi.",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Serbest not (LLM'in niyetini aciklayan kisa yorum)"
    )
