"""
Geometri sahne grafinin yapisal (kod seviyesi) dogrulamasi.

LLM dogrulamasina GEREK YOK — bu kontroller sayisal invariantlardir ve
Python'da hizlica yapilabilir. Hata bulunursa scene chain'ine feedback verilir.

Kontroller:
  1. Polygon vertex sayisi (>=3)
  2. Grid-snap: kareli/noktali zeminde TAM SAYI vertex zorunlu
  3. Bounds: tum vertex'ler [0, cols] x [0, rows] icinde
  4. Simple polygon: kendi kenarlarina kesismemeli
  5. Area (shoelace): expected_area verilmisse bire bir esit
  6. Closed: en az 3 vertex ve siralama kapali polygon olusturmali
  7. Opacity saglık kontrolu: fill_opacity <= 0.6 (grid'i yutmasin)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from pomodoro.geometry_scene import (
    GeometryBackground,
    GeometryPolygon,
    GeometryScene,
)


EPSILON = 1e-6


@dataclass
class ValidationResult:
    ok: bool
    issues: list[str] = field(default_factory=list)

    def as_feedback(self) -> str:
        if self.ok:
            return ""
        return "\n".join(f"- {msg}" for msg in self.issues)


# ---------------------------------------------------------------------------
# Temel geometri yardimcilari
# ---------------------------------------------------------------------------

def shoelace_area(vertices: list[tuple[float, float]]) -> float:
    """Shoelace formulu ile polygon alani (mutlak deger, birimkare cinsinden)."""
    n = len(vertices)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = vertices[i]
        x2, y2 = vertices[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _segments_properly_intersect(a, b, c, d) -> bool:
    """(a,b) ve (c,d) dogru parcalari gercekten kesisiyor mu (ortak kose haric)?"""
    def ccw(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    # Paylasilan endpoint varsa kesisme sayma
    if a == c or a == d or b == c or b == d:
        return False

    d1 = ccw(c, d, a)
    d2 = ccw(c, d, b)
    d3 = ccw(a, b, c)
    d4 = ccw(a, b, d)

    if ((d1 > EPSILON and d2 < -EPSILON) or (d1 < -EPSILON and d2 > EPSILON)) and \
       ((d3 > EPSILON and d4 < -EPSILON) or (d3 < -EPSILON and d4 > EPSILON)):
        return True
    return False


def is_simple_polygon(vertices: list[tuple[float, float]]) -> bool:
    """Polygon kenarlari birbirine kesismiyor mu?"""
    n = len(vertices)
    if n < 3:
        return False
    edges = [(vertices[i], vertices[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            # Komsu edge'leri atla (ortak vertex'ten otesi kesisim sayilmaz)
            if j == i + 1 or (i == 0 and j == n - 1):
                continue
            if _segments_properly_intersect(*edges[i], *edges[j]):
                return False
    return True


def _is_integer(v: float) -> bool:
    return abs(v - round(v)) < EPSILON


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def validate_polygon(
    poly: GeometryPolygon,
    bg: GeometryBackground,
    expected_area: float | None,
    *,
    require_integer_vertices: bool,
) -> list[str]:
    """Tek bir polygon icin kontroller. Hatalari list[str] olarak dondurur."""
    issues: list[str] = []
    verts = poly.vertices

    if len(verts) < 3:
        issues.append(f"Polygon en az 3 vertex icermeli (mevcut: {len(verts)}).")
        return issues  # Devam etmek anlamsiz

    # 1. Grid snap
    if require_integer_vertices:
        non_int = [(i, v) for i, v in enumerate(verts) if not (_is_integer(v[0]) and _is_integer(v[1]))]
        if non_int:
            sample = non_int[:3]
            issues.append(
                "Kareli/noktali zeminde TUM vertex'ler TAM SAYI olmali. "
                f"Ihlal ornekleri (index, deger): {sample}"
            )

    # 2. Bounds
    out_of_bounds = [
        (i, v) for i, v in enumerate(verts)
        if v[0] < -EPSILON or v[0] > bg.cols + EPSILON
        or v[1] < -EPSILON or v[1] > bg.rows + EPSILON
    ]
    if out_of_bounds:
        sample = out_of_bounds[:3]
        issues.append(
            f"Vertex'ler grid sinirlari [0,{bg.cols}]x[0,{bg.rows}] icinde olmali. "
            f"Disari tasan ornekler: {sample}"
        )

    # 3. Simple polygon
    if not is_simple_polygon(verts):
        issues.append("Polygon kenarlari birbirine kesisiyor — basit (simple) olmali.")

    # 4. Area
    if expected_area is not None:
        actual = shoelace_area(verts)
        if abs(actual - expected_area) > 0.5:  # yarim birimkare tolerans
            issues.append(
                f"Polygon alani {actual:.2f} birimkare, beklenen {expected_area}. "
                "Vertex'leri dogru cevabi yansitacak sekilde degistir."
            )

    # 5. Ardisik ayni vertex
    dup = [
        i for i in range(len(verts))
        if verts[i] == verts[(i + 1) % len(verts)]
    ]
    if dup:
        issues.append(f"Ardisik ayni vertex var (index {dup[:3]}). Tekrari kaldir.")

    # 6. Opaklik — ic dolgu grid'i yutmamali
    if poly.fill_opacity > 0.6:
        issues.append(
            f"fill_opacity={poly.fill_opacity:.2f} cok yuksek; grid arkadan gorunmez. "
            "0.25-0.45 araligina cek."
        )

    return issues


def validate_scene(scene: GeometryScene) -> ValidationResult:
    """Tum sahneyi dogrular."""
    issues: list[str] = []
    bg = scene.background

    # Kareli varyantlari + noktali: integer vertex zorunlu
    require_int = bg.type in ("unit_square", "dotted", "dashed_grid", "soft_grid")

    if not scene.polygons and not scene.segments:
        issues.append("Sahnede hic polygon veya segment yok — ana geometri gerekli.")
    else:
        for i, poly in enumerate(scene.polygons):
            poly_issues = validate_polygon(
                poly, bg, scene.expected_area if i == 0 else None,
                require_integer_vertices=require_int,
            )
            for msg in poly_issues:
                issues.append(f"Polygon {i}: {msg}")

    # Grid opacity saglik
    if bg.grid_opacity > 0.75:
        issues.append(
            f"Grid opacity cok yuksek ({bg.grid_opacity:.2f}); sekli yutabilir. 0.35-0.55 onerilir."
        )

    # Etiketler grid icinde mi?
    for k, label in enumerate(scene.labels):
        x, y = label.pos
        if x < -EPSILON or x > bg.cols + EPSILON or y < -EPSILON or y > bg.rows + EPSILON:
            issues.append(
                f"Etiket {k} ('{label.text}') grid disinda: pos={label.pos}."
            )

    return ValidationResult(ok=len(issues) == 0, issues=issues)


# ---------------------------------------------------------------------------
# Otomatik duzeltmeler (kucuk sapmalar icin)
# ---------------------------------------------------------------------------

def snap_polygon_to_grid(poly: GeometryPolygon) -> GeometryPolygon:
    """Polygon vertex'lerini en yakin tam sayiya yuvarlar (kucuk sapmalar icin)."""
    snapped = [(round(v[0]), round(v[1])) for v in poly.vertices]
    # Ardisik cift vertex'leri temizle
    cleaned: list[tuple[float, float]] = []
    for v in snapped:
        if not cleaned or cleaned[-1] != v:
            cleaned.append(v)
    if len(cleaned) > 1 and cleaned[0] == cleaned[-1]:
        cleaned.pop()
    return poly.model_copy(update={"vertices": cleaned})


def auto_snap_scene(scene: GeometryScene) -> GeometryScene:
    """Kareli/noktali zeminde kucuk floating-point sapmalari duzeltir."""
    if scene.background.type not in ("unit_square", "dotted"):
        return scene
    new_polys = [snap_polygon_to_grid(p) for p in scene.polygons]
    return scene.model_copy(update={"polygons": new_polys})
