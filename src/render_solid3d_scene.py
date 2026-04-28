"""Solid3DScene'i deterministik SVG/PNG olarak render eder."""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from pomodoro.solid3d_scene import Solid3DObject, Solid3DPanel, Solid3DScene


PANEL_WIDTH = 235
PANEL_HEIGHT = 280
PANEL_GAP = 22
PADDING = 28
UNIT = 54


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    raw = color.strip().lstrip("#")
    if len(raw) != 6:
        return (96, 165, 250)
    try:
        return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
    except ValueError:
        return (96, 165, 250)


def _shift_color(color: str, factor: float) -> str:
    r, g, b = _hex_to_rgb(color)
    if factor >= 1:
        r = int(r + (255 - r) * (factor - 1))
        g = int(g + (255 - g) * (factor - 1))
        b = int(b + (255 - b) * (factor - 1))
    else:
        r = int(r * factor)
        g = int(g * factor)
        b = int(b * factor)
    return f"#{max(0, min(255, r)):02X}{max(0, min(255, g)):02X}{max(0, min(255, b)):02X}"


def _stroke(color: str) -> str:
    return _shift_color(color, 0.55)


def _draw_prism(solid: Solid3DObject, cx: float, base_y: float) -> tuple[str, float]:
    w = UNIT * solid.width_units
    h = UNIT * solid.height_units
    d = UNIT * solid.depth_units
    dx = d * 0.46
    dy = d * 0.30
    x0 = cx - w / 2
    x1 = cx + w / 2
    y0 = base_y - h
    y1 = base_y

    top = f"{x0:.1f},{y0:.1f} {x0+dx:.1f},{y0-dy:.1f} {x1+dx:.1f},{y0-dy:.1f} {x1:.1f},{y0:.1f}"
    side = f"{x1:.1f},{y0:.1f} {x1+dx:.1f},{y0-dy:.1f} {x1+dx:.1f},{y1-dy:.1f} {x1:.1f},{y1:.1f}"
    front = f"{x0:.1f},{y0:.1f} {x1:.1f},{y0:.1f} {x1:.1f},{y1:.1f} {x0:.1f},{y1:.1f}"
    color = solid.color
    stroke = _stroke(color)
    svg = f"""
<g stroke="{stroke}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round">
  <polygon points="{side}" fill="{_shift_color(color, 0.93)}"/>
  <polygon points="{top}" fill="{_shift_color(color, 1.06)}"/>
  <polygon points="{front}" fill="{color}"/>
</g>"""
    return svg, h + dy


def _draw_triangular_prism(solid: Solid3DObject, cx: float, base_y: float) -> tuple[str, float]:
    w = UNIT * solid.width_units
    h = UNIT * solid.height_units
    d = UNIT * solid.depth_units
    dx = d * 0.48
    dy = d * 0.30
    p1 = (cx - w / 2, base_y)
    p2 = (cx + w / 2, base_y)
    p3 = (cx, base_y - h)
    p1b = (p1[0] + dx, p1[1] - dy)
    p2b = (p2[0] + dx, p2[1] - dy)
    p3b = (p3[0] + dx, p3[1] - dy)

    def pts(*points: tuple[float, float]) -> str:
        return " ".join(f"{x:.1f},{y:.1f}" for x, y in points)

    color = solid.color
    stroke = _stroke(color)
    svg = f"""
<g stroke="{stroke}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round">
  <polygon points="{pts(p2, p2b, p3b, p3)}" fill="{_shift_color(color, 0.93)}"/>
  <polygon points="{pts(p1, p1b, p3b, p3)}" fill="{_shift_color(color, 1.04)}"/>
  <polygon points="{pts(p1, p2, p3)}" fill="{color}"/>
</g>"""
    return svg, h + dy


def _draw_cylinder(solid: Solid3DObject, cx: float, base_y: float) -> tuple[str, float]:
    w = UNIT * solid.width_units
    h = UNIT * solid.height_units
    rx = w / 2
    ry = max(10, UNIT * solid.depth_units * 0.18)
    y0 = base_y - h
    y1 = base_y
    color = solid.color
    stroke = _stroke(color)
    svg = f"""
<g stroke="{stroke}" stroke-width="2" stroke-linejoin="round">
  <path d="M {cx-rx:.1f} {y0:.1f} L {cx-rx:.1f} {y1:.1f} A {rx:.1f} {ry:.1f} 0 0 0 {cx+rx:.1f} {y1:.1f} L {cx+rx:.1f} {y0:.1f} Z" fill="{color}"/>
  <ellipse cx="{cx:.1f}" cy="{y0:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" fill="{_shift_color(color, 1.04)}"/>
</g>"""
    return svg, h + ry


def _draw_sphere(solid: Solid3DObject, cx: float, base_y: float, gradient_id: str) -> tuple[str, float]:
    r = UNIT * max(solid.width_units, solid.height_units) * 0.42
    cy = base_y - r
    color = solid.color
    stroke = _stroke(color)
    svg = f"""
<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{color}" stroke="{stroke}" stroke-width="2"/>"""
    return svg, r * 2


def _draw_solid(solid: Solid3DObject, cx: float, base_y: float, gid: str) -> tuple[str, float]:
    if solid.kind in {"cube", "rectangular_prism", "square_prism"}:
        if solid.kind == "cube":
            solid = solid.model_copy(update={"width_units": 1.0, "height_units": 1.0, "depth_units": 1.0})
        if solid.kind == "square_prism":
            solid = solid.model_copy(update={"width_units": 1.0, "depth_units": 1.0})
        return _draw_prism(solid, cx, base_y)
    if solid.kind == "triangular_prism":
        return _draw_triangular_prism(solid, cx, base_y)
    if solid.kind == "cylinder":
        return _draw_cylinder(solid, cx, base_y)
    return _draw_sphere(solid, cx, base_y, gid)


def _render_panel(panel: Solid3DPanel, x: float, y: float, index: int, scene: Solid3DScene) -> str:
    parts: list[str] = []
    if panel.label:
        parts.append(
            f'<text x="{x+18:.1f}" y="{y+28:.1f}" font-family="Inter, Arial, sans-serif" '
            f'font-size="24" font-weight="700" fill="#0F172A">{escape(panel.label)})</text>'
        )

    floor_y = y + PANEL_HEIGHT - 40
    center_x = x + PANEL_WIDTH / 2

    if panel.layout == "side_by_side":
        count = len(panel.solids)
        step = min(74, PANEL_WIDTH / max(1, count))
        start_x = center_x - step * (count - 1) / 2
        for i, solid in enumerate(panel.solids):
            sx = start_x + i * step + solid.x_offset_units * 12
            svg, _ = _draw_solid(solid, sx, floor_y, f"sg{index}_{i}")
            parts.append(svg)
    elif panel.layout == "loose_group":
        offsets = [(-28, 0), (28, -2), (0, -52), (-16, 24), (36, -42), (-36, -44)]
        for i, solid in enumerate(panel.solids):
            ox, oy = offsets[i % len(offsets)]
            sx = center_x + ox + solid.x_offset_units * 12
            svg, _ = _draw_solid(solid, sx, floor_y + oy, f"sg{index}_{i}")
            parts.append(svg)
    else:
        base_y = floor_y
        for i, solid in enumerate(panel.solids):
            sx = center_x + solid.x_offset_units * 14
            svg, occupied_h = _draw_solid(solid, sx, base_y, f"sg{index}_{i}")
            parts.append(svg)
            base_y -= max(38, occupied_h * 0.74)

    return "\n".join(parts)


def render_solid3d_scene_to_svg(scene: Solid3DScene) -> str:
    panel_count = len(scene.panels)
    width = PADDING * 2 + panel_count * PANEL_WIDTH + max(0, panel_count - 1) * PANEL_GAP
    height = PADDING * 2 + PANEL_HEIGHT

    body: list[str] = [
        f'<rect width="100%" height="100%" fill="{scene.background_color}"/>',
    ]
    for i, panel in enumerate(scene.panels):
        x = PADDING + i * (PANEL_WIDTH + PANEL_GAP)
        body.append(_render_panel(panel, x, PADDING, i, scene))

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}" height="{height:.0f}">
  {' '.join(body)}
</svg>
"""


def render_solid3d_scene_to_file(scene: Solid3DScene, output_path: str | Path) -> str:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_solid3d_scene_to_svg(scene), encoding="utf-8")
    return str(output_path)


def render_solid3d_scene_to_png(
    scene: Solid3DScene,
    output_path: str | Path,
    *,
    scale: float = 2.0,
) -> str:
    from playwright.sync_api import sync_playwright

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    svg = render_solid3d_scene_to_svg(scene)

    panel_count = len(scene.panels)
    width = int(PADDING * 2 + panel_count * PANEL_WIDTH + max(0, panel_count - 1) * PANEL_GAP)
    height = int(PADDING * 2 + PANEL_HEIGHT)
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<style>html,body{{margin:0;padding:0;background:#fff}}</style></head>
<body>{svg}</body></html>"""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(
                viewport={"width": width, "height": height},
                device_scale_factor=scale,
            )
            try:
                page.set_content(html, wait_until="load")
                page.locator("svg").screenshot(path=str(output_path), omit_background=False)
            finally:
                page.close()
        finally:
            browser.close()

    return str(output_path)
