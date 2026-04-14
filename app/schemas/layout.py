from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class AssetType(str, Enum):
    CATALOG_COMPONENT = "catalog_component"
    GENERATED_COMPOSITE = "generated_composite"


class AssetSpec(BaseModel):
    slug: str
    asset_type: AssetType
    description: str
    prompt: str = ""
    source_filename: str | None = None
    output_filename: str
    kind: str = "object"
    transparent_background: bool = False
    render_shape: Literal["rectangle", "square", "free"] = "free"

    @model_validator(mode="after")
    def _validate_asset_constraints(self) -> "AssetSpec":
        # AI-generated images are treated as opaque rectangular/square layers.
        if self.asset_type == AssetType.GENERATED_COMPOSITE:
            if self.transparent_background:
                raise ValueError("generated_composite assets cannot be transparent")
            if self.render_shape not in {"rectangle", "square"}:
                raise ValueError("generated_composite assets must use rectangle or square render_shape")
        return self


class PlacementFrame(BaseModel):
    x_pct: float = Field(default=0, ge=0, le=100)
    y_pct: float = Field(default=0, ge=0, le=100)
    width_pct: float = Field(default=100, gt=0, le=100)
    height_pct: float = Field(default=100, gt=0, le=100)


class AssetBinding(BaseModel):
    asset_slug: str
    repeat: int = 1
    placement_hint: str = ""
    layer: Literal["background", "content", "foreground", "overlay"] = "content"
    z_index: int = 0
    must_remain_visible: bool = False
    allow_occlusion: bool = True
    frame: PlacementFrame | None = None

    @model_validator(mode="after")
    def _normalize_visibility_flags(self) -> "AssetBinding":
        if self.must_remain_visible:
            self.allow_occlusion = False
        return self


class HtmlLayoutNode(BaseModel):
    slug: str
    node_type: str = "container"
    bindings: list[AssetBinding] = Field(default_factory=list)
    children: list["HtmlLayoutNode"] = Field(default_factory=list)


class LayoutPlan(BaseModel):
    schema_version: str = "layout-plan.v2"
    question_id: str | None = None
    asset_library: dict[str, AssetSpec]
    html_layout: HtmlLayoutNode

    @model_validator(mode="after")
    def _validate_bindings(self) -> "LayoutPlan":
        known = set(self.asset_library.keys())
        opaque_ai_bindings: list[AssetBinding] = []
        critical_bindings: list[AssetBinding] = []

        def walk(node: HtmlLayoutNode) -> None:
            for binding in node.bindings:
                if binding.asset_slug not in known:
                    raise ValueError(f"Unknown asset slug: {binding.asset_slug}")
                asset = self.asset_library[binding.asset_slug]
                if asset.asset_type == AssetType.GENERATED_COMPOSITE and not asset.transparent_background:
                    opaque_ai_bindings.append(binding)
                    if binding.layer == "overlay":
                        raise ValueError(f"Opaque AI asset cannot be in overlay layer: {binding.asset_slug}")
                if binding.must_remain_visible:
                    critical_bindings.append(binding)
            for child in node.children:
                walk(child)

        walk(self.html_layout)

        if opaque_ai_bindings and critical_bindings:
            max_ai_z = max(item.z_index for item in opaque_ai_bindings)
            min_critical_z = min(item.z_index for item in critical_bindings)
            if max_ai_z >= min_critical_z:
                raise ValueError(
                    "must_remain_visible assets should render above opaque AI assets (z_index must be higher)"
                )
        return self


HtmlLayoutNode.model_rebuild()
