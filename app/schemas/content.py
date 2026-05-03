from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class CurriculumNodeCreateRequest(BaseModel):
    parent_id: str | None = None
    node_type: Literal["folder"] = "folder"
    name: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    grade: str | None = None
    subject: str | None = None
    theme: str | None = None
    code: str | None = None
    sort_order: int = 0


class CurriculumNodeUpdateRequest(BaseModel):
    name: str | None = None
    code: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class CurriculumNodeResponse(BaseModel):
    id: str
    parent_id: str | None
    node_type: str
    scope: Literal["constant", "folder"]
    name: str
    slug: str
    code: str | None
    grade: str | None = None
    subject: str | None = None
    theme: str | None = None
    sort_order: int
    depth: int
    path: str
    is_active: bool
    children: list["CurriculumNodeResponse"] = Field(default_factory=list)


class PropertyCreateRequest(BaseModel):
    defined_at_curriculum_node_id: str
    parent_property_id: str | None = None
    label: str = Field(min_length=1)
    description: str | None = None
    property_key: str = Field(min_length=1)
    canonical_path: str = Field(min_length=1)
    data_type: Literal["text", "bool", "number", "json", "array", "enum", "object"]
    default_value: str | None = None
    constraints: Any | None = None
    is_required: bool = False


class PropertyUpdateRequest(BaseModel):
    label: str | None = None
    description: str | None = None
    property_key: str | None = None
    canonical_path: str | None = None
    data_type: Literal["text", "bool", "number", "json", "array", "enum", "object"] | None = None
    default_value: str | None = None
    constraints: Any | None = None
    is_required: bool | None = None
    is_active: bool | None = None


class PropertyResponse(BaseModel):
    id: str
    defined_at_curriculum_node_id: str
    parent_property_id: str | None
    label: str
    description: str | None = None
    property_key: str
    canonical_path: str
    data_type: str
    default_value: str | None = None
    constraints: Any | None = None
    is_required: bool
    is_active: bool


class YamlTemplateCreateRequest(BaseModel):
    curriculum_folder_node_id: str
    template_code: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str | None = None
    field_schema: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "v1"
    created_by: str | None = None


class YamlTemplateUpdateRequest(BaseModel):
    template_code: str | None = None
    title: str | None = None
    description: str | None = None
    field_schema: dict[str, Any] | None = None
    schema_version: str | None = None
    status: Literal["active", "archived"] | None = None


class YamlTemplateResponse(BaseModel):
    id: str
    curriculum_folder_node_id: str
    template_code: str
    title: str
    description: str | None
    field_schema: dict[str, Any]
    schema_version: str
    status: str
    created_by: str | None


class YamlInstanceCreateRequest(BaseModel):
    template_id: str
    instance_name: str = Field(min_length=1)
    values: dict[str, Any] = Field(default_factory=dict)
    status: Literal["draft", "final", "archived"] = "draft"
    created_by: str | None = None


class YamlInstanceUpdateRequest(BaseModel):
    instance_name: str | None = None
    values: dict[str, Any] | None = None
    status: Literal["draft", "final", "archived"] | None = None


class YamlInstanceResponse(BaseModel):
    id: str
    template_id: str
    instance_name: str
    status: str
    values: dict[str, Any]
    rendered_yaml_text: str | None
    created_by: str | None


class YamlRenderResponse(BaseModel):
    instance_id: str
    artifact_id: str
    yaml_content: dict[str, Any]
    rendered_yaml_text: str


class ArtifactFavoriteRequest(BaseModel):
    is_favorite: bool


class ArtifactResponse(BaseModel):
    id: str
    kind: str
    content_json: Any | None = None
    content_text: str | None = None
    object_bucket: str | None = None
    object_key: str | None = None
    mime_type: str | None = None
    is_favorite: bool
    source_pipeline_id: str | None = None
    source_sub_pipeline_id: str | None = None
    source_agent_name: str | None = None
    source_agent_run_id: str | None = None
    created_at: str
    updated_at: str | None = None


CurriculumNodeResponse.model_rebuild()
