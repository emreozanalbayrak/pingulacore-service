"""Yapisal kontroller: Solid3DScene icin hizli invariant dogrulamasi."""
from __future__ import annotations

from dataclasses import dataclass, field

from pomodoro.solid3d_scene import Solid3DScene


@dataclass
class Solid3DValidationResult:
    ok: bool
    issues: list[str] = field(default_factory=list)

    def as_feedback(self) -> str:
        return "\n".join(f"- {issue}" for issue in self.issues)


def validate_solid3d_scene(
    scene: Solid3DScene,
    *,
    expected_labels: set[str] | None = None,
) -> Solid3DValidationResult:
    issues: list[str] = []

    labels = [panel.label for panel in scene.panels if panel.label]
    if len(labels) != len(set(labels)):
        issues.append(f"Panel etiketleri tekrar ediyor: {labels}")

    if expected_labels:
        actual = set(labels)
        if actual != expected_labels:
            issues.append(
                "Panel etiketleri soru secenekleriyle birebir ayni olmali. "
                f"Beklenen={sorted(expected_labels)}, mevcut={sorted(actual)}"
            )

    for panel_index, panel in enumerate(scene.panels):
        if not panel.solids:
            issues.append(f"Panel {panel_index}: en az bir cisim icermeli.")
            continue

        if panel.layout == "vertical_stack" and len(panel.solids) > 6:
            issues.append(
                f"Panel {panel.label or panel_index}: dikey yigin 6 cisimden fazla olmamali."
            )

        for solid_index, solid in enumerate(panel.solids):
            if solid.kind == "sphere" and panel.layout == "vertical_stack":
                issues.append(
                    f"Panel {panel.label or panel_index}, cisim {solid_index}: "
                    "kure dikey yigin icin kararsiz/yaniltici olabilir; loose_group kullan."
                )
            if panel.layout == "vertical_stack" and abs(solid.x_offset_units) > 0.75:
                issues.append(
                    f"Panel {panel.label or panel_index}, cisim {solid_index}: "
                    "dikey yiginda cisimler panel merkezinden cok uzaklasmamalidir."
                )
            if panel.layout in {"side_by_side", "loose_group"} and abs(solid.x_offset_units) > 1.1:
                issues.append(
                    f"Panel {panel.label or panel_index}, cisim {solid_index}: "
                    "cisim yatayda asiri uca kaymis; daha merkezli yerlestir."
                )

        if panel.layout == "vertical_stack":
            for upper_index in range(1, len(panel.solids)):
                lower = panel.solids[upper_index - 1]
                upper = panel.solids[upper_index]
                shift = abs(upper.x_offset_units - lower.x_offset_units)
                max_supported_shift = max(0.35, min(lower.width_units * 0.42, 0.7))
                if shift > max_supported_shift:
                    issues.append(
                        f"Panel {panel.label or panel_index}, katman {upper_index}: "
                        "ustteki cisim alttaki cisim tarafindan gercekci bicimde desteklenmiyor."
                    )

    return Solid3DValidationResult(ok=not issues, issues=issues)
