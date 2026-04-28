"""
Deterministik SVG renderer — GeometryScene'i pixel-perfect SVG olarak cizer.

Renderer sadece matematiksel referans katmanini cizer:
- paper_color zemini
- grid (kareli / noktali / kesik / yumusak / dusuz)
- polygons (shoelace-tutarli, grid-snap vertex)
- line segments (olcu cizgileri)
- labels (metin etiketleri)

Dekorasyon yoktur. Nihai estetik PNG, bu referans gorsel image modeline
girdi verilerek chain_generate_geometry_image tarafindan uretilir.
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from pomodoro.geometry_scene import (
    GeometryBackground,
    GeometryLineSegment,
    GeometryPolygon,
    GeometryScene,
)


# ---------------------------------------------------------------------------
# Koordinat donusumu
# ---------------------------------------------------------------------------

def _make_transform(bg: GeometryBackground):
    """Grid koordinatindan SVG piksel koordinatina donusturen fonksiyon uretir.

    SVG origin'i sol-ust, y asagi. Grid origin'i sol-alt, y yukari.
    Donusum: flip y + offset (margin).

    Returns:
        (transform_fn, width_px, height_px)
    """
    cs = bg.cell_size_px
    mx = bg.margin_cells * cs
    my = bg.margin_cells * cs
    grid_w = bg.cols * cs
    grid_h = bg.rows * cs
    width = grid_w + 2 * mx
    height = grid_h + 2 * my

    def to_px(gx: float, gy: float) -> tuple[float, float]:
        return (mx + gx * cs, my + (bg.rows - gy) * cs)

    return to_px, width, height


# ---------------------------------------------------------------------------
# Background uretimi
# ---------------------------------------------------------------------------

def _render_background(bg: GeometryBackground, to_px) -> str:
    """Kareli / noktali / kesik / yumusak / dusuz zemin SVG fragmenti uretir."""
    if bg.type == "plain":
        return ""

    is_line_grid = bg.type in ("unit_square", "dashed_grid", "soft_grid")
    is_dotted = bg.type == "dotted"

    effective_opacity = bg.grid_opacity
    if bg.type == "soft_grid":
        effective_opacity = min(effective_opacity, 0.25)

    parts = [f'<g class="bg" opacity="{effective_opacity:.3f}">']

    if is_line_grid:
        dash_attr = ""
        stroke_w = bg.grid_stroke_width
        if bg.type == "dashed_grid":
            dash_attr = f' stroke-dasharray="{bg.dash_pattern}"'
        elif bg.type == "soft_grid":
            stroke_w = max(0.6, bg.grid_stroke_width * 0.75)

        stroke_attrs = (
            f'stroke="{bg.grid_color}" stroke-width="{stroke_w}" '
            f'fill="none" shape-rendering="crispEdges"{dash_attr}'
        )
        for c in range(bg.cols + 1):
            x1, y1 = to_px(c, 0)
            x2, y2 = to_px(c, bg.rows)
            parts.append(
                f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" {stroke_attrs}/>'
            )
        for r in range(bg.rows + 1):
            x1, y1 = to_px(0, r)
            x2, y2 = to_px(bg.cols, r)
            parts.append(
                f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" {stroke_attrs}/>'
            )

    elif is_dotted:
        fill_attrs = f'fill="{bg.dot_color}"'
        for c in range(bg.cols + 1):
            for r in range(bg.rows + 1):
                cx, cy = to_px(c, r)
                parts.append(
                    f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{bg.dot_radius_px}" {fill_attrs}/>'
                )

    parts.append('</g>')
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Sekiller
# ---------------------------------------------------------------------------

def _render_polygon(poly: GeometryPolygon, to_px) -> str:
    pts = [to_px(x, y) for (x, y) in poly.vertices]
    pts_str = " ".join(f"{x:.2f},{y:.2f}" for (x, y) in pts)
    tag = "polygon" if poly.closed else "polyline"
    return (
        f'<{tag} points="{pts_str}" '
        f'fill="{poly.fill}" fill-opacity="{poly.fill_opacity:.3f}" '
        f'stroke="{poly.stroke}" stroke-width="{poly.stroke_width}" '
        f'stroke-opacity="{poly.stroke_opacity:.3f}" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
    )


def _render_segment(seg: GeometryLineSegment, to_px) -> str:
    x1, y1 = to_px(*seg.start)
    x2, y2 = to_px(*seg.end)
    dash = ' stroke-dasharray="6,4"' if seg.dashed else ""
    marker_start = ' marker-start="url(#arrowhead)"' if seg.arrow in ("start", "both") else ""
    marker_end = ' marker-end="url(#arrowhead)"' if seg.arrow in ("end", "both") else ""
    return (
        f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
        f'stroke="{seg.color}" stroke-width="{seg.stroke_width}" '
        f'stroke-opacity="{seg.stroke_opacity:.3f}"{dash}{marker_start}{marker_end}/>'
    )


def _render_label(label, to_px) -> str:
    x, y = to_px(*label.pos)
    x += label.offset_x_px
    y += label.offset_y_px
    text = escape(label.text)
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" '
        f'fill="{label.color}" font-size="{label.font_size_px}" '
        f'font-family="Inter, Arial, sans-serif" '
        f'font-weight="{label.font_weight}" '
        f'text-anchor="{label.anchor}" dominant-baseline="middle">{text}</text>'
    )


def _is_int_coord(value: float) -> bool:
    return abs(value - round(value)) < 1e-6


# ---------------------------------------------------------------------------
# Ok ucu marker tanimi
# ---------------------------------------------------------------------------

_ARROW_MARKER = """<defs>
  <marker id="arrowhead" viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="6" markerHeight="6" orient="auto-start-reverse">
    <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor"/>
  </marker>
</defs>"""


# ---------------------------------------------------------------------------
# Ambient raster embed (legacy; yeni hybrid akista kullanilmaz)
# ---------------------------------------------------------------------------

_AMBIENT_OPACITY_MULTIPLIER = 1.40  # kullanici istegi: +%40


def _embed_ambient_raster(
    image_path: str | Path | None,
    opacity: float,
    width: float,
    height: float,
) -> str:
    """Ambient raster PNG'sini SVG icine base64 data URI olarak gomer.

    Scene'deki ambient_opacity degeri x1.40 carpanla yukseltilir (kullanici istegi).
    Ust sinir 0.85 — paper ve grid tamamen yutulmasin.
    """
    if not image_path:
        return ""
    p = Path(image_path)
    if not p.exists():
        return ""

    import base64
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    effective_opacity = min(0.85, max(0.05, opacity * _AMBIENT_OPACITY_MULTIPLIER))
    return (
        f'<image href="data:{mime};base64,{data}" x="0" y="0" '
        f'width="{width:.0f}" height="{height:.0f}" '
        f'opacity="{effective_opacity:.3f}" preserveAspectRatio="xMidYMid slice"/>'
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_scene_to_svg(
    scene: GeometryScene,
    ambient_image_path: str | Path | None = None,
) -> str:
    """Scene graph'tan tam SVG belgesi uretir.

    Katman sirasi (alttan uste):
      1. paper_color (kagit zemini)
      2. ambient raster (legacy, normalde yok)
      3. background grid/nokta
      4. polygons
      5. segments (olcu cizgileri)
      6. labels
    """
    bg = scene.background
    to_px, width, height = _make_transform(bg)

    body_parts: list[str] = []

    # 1. Ambient raster — legacy; yeni akista None gelir
    ambient_svg = _embed_ambient_raster(
        ambient_image_path, scene.ambient_opacity, width, height,
    )
    if ambient_svg:
        body_parts.append(ambient_svg)

    # 2. Background grid/nokta
    body_parts.append(_render_background(bg, to_px))

    # 3. Polygons
    for poly in scene.polygons:
        body_parts.append(_render_polygon(poly, to_px))

    # 4. Segments
    for seg in scene.segments:
        body_parts.append(_render_segment(seg, to_px))

    # 5. Labels
    for label in scene.labels:
        body_parts.append(_render_label(label, to_px))

    body = "\n  ".join(p for p in body_parts if p)

    needs_arrows = any(s.arrow != "none" for s in scene.segments)
    defs = _ARROW_MARKER if needs_arrows else ""

    paper = bg.paper_color or "#FFFFFF"

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}" height="{height:.0f}">
  {defs}
  <rect width="100%" height="100%" fill="{paper}"/>
  {body}
</svg>
"""


def render_scene_to_file(
    scene: GeometryScene,
    output_path: str | Path,
    ambient_image_path: str | Path | None = None,
) -> str:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    svg = render_scene_to_svg(scene, ambient_image_path=ambient_image_path)
    output_path.write_text(svg, encoding="utf-8")
    return str(output_path)


def render_scene_to_png(
    scene: GeometryScene,
    output_path: str | Path,
    *,
    scale: float = 2.0,
    ambient_image_path: str | Path | None = None,
) -> str:
    """Scene'i PNG olarak diske yazar (Playwright ile SVG'yi rasterize eder)."""
    from playwright.sync_api import sync_playwright

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    svg = render_scene_to_svg(scene, ambient_image_path=ambient_image_path)

    _, width, height = _make_transform(scene.background)
    width_i = int(round(width))
    height_i = int(round(height))

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<style>html,body{{margin:0;padding:0;background:#fff}}</style></head>
<body>{svg}</body></html>"""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(
                viewport={"width": width_i, "height": height_i},
                device_scale_factor=scale,
            )
            try:
                page.set_content(html, wait_until="load")
                svg_elem = page.locator("svg")
                svg_elem.screenshot(path=str(output_path), omit_background=False)
            finally:
                page.close()
        finally:
            browser.close()

    return str(output_path)
