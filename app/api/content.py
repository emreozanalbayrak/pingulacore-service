from __future__ import annotations

from typing import Any

import yaml
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.db import repository
from app.db.database import get_db
from app.schemas.content import (
    ArtifactFavoriteRequest,
    ArtifactResponse,
    PropertyCreateRequest,
    PropertyResponse,
    PropertyUpdateRequest,
    CurriculumNodeCreateRequest,
    CurriculumNodeResponse,
    CurriculumNodeUpdateRequest,
    YamlInstanceCreateRequest,
    YamlInstanceResponse,
    YamlInstanceUpdateRequest,
    YamlRenderResponse,
    YamlTemplateCreateRequest,
    YamlTemplateResponse,
    YamlTemplateUpdateRequest,
)
from app.services.object_storage_service import ObjectStorageService

router = APIRouter(prefix="/v1", tags=["content"])


def _json(value: str | None) -> Any:
    return repository.parse_json(value)


def _dt(value: Any) -> str:
    return value.isoformat() if value is not None else ""


def _curriculum_response(row: Any, children: list[CurriculumNodeResponse] | None = None) -> CurriculumNodeResponse:
    return CurriculumNodeResponse(
        id=row.id,
        parent_id=row.parent_id,
        node_type=row.node_type,
        scope=row.scope,
        name=row.name,
        slug=row.slug,
        code=row.code,
        grade=row.grade,
        subject=row.subject,
        theme=row.theme,
        sort_order=row.sort_order,
        depth=row.depth,
        path=row.path,
        is_active=row.is_active,
        children=children or [],
    )


def _property_response(row: Any) -> PropertyResponse:
    return PropertyResponse(
        id=row.id,
        defined_at_curriculum_node_id=row.defined_at_curriculum_node_id,
        parent_property_id=row.parent_property_id,
        label=row.label,
        description=row.description,
        property_key=row.property_key,
        canonical_path=row.canonical_path,
        data_type=row.data_type,
        default_value=row.default_value,
        constraints=_json(row.constraints_json),
        is_required=row.is_required,
        is_active=row.is_active,
    )


def _template_response(row: Any) -> YamlTemplateResponse:
    return YamlTemplateResponse(
        id=row.id,
        curriculum_folder_node_id=row.curriculum_folder_node_id,
        template_code=row.template_code,
        title=row.title,
        description=row.description,
        field_schema=_json(row.field_schema_json) or {},
        schema_version=row.schema_version,
        status=row.status,
        created_by=row.created_by,
    )


def _instance_response(row: Any) -> YamlInstanceResponse:
    return YamlInstanceResponse(
        id=row.id,
        template_id=row.template_id,
        instance_name=row.instance_name,
        status=row.status,
        values=_json(row.values_json) or {},
        rendered_yaml_text=row.rendered_yaml_text,
        created_by=row.created_by,
    )


def _artifact_response(row: Any) -> ArtifactResponse:
    return ArtifactResponse(
        id=row.id,
        kind=row.kind,
        content_json=_json(row.content_json),
        content_text=row.content_text,
        object_bucket=row.object_bucket,
        object_key=row.object_key,
        mime_type=row.mime_type,
        is_favorite=row.is_favorite,
        source_pipeline_id=row.source_pipeline_id,
        source_sub_pipeline_id=row.source_sub_pipeline_id,
        source_agent_name=row.source_agent_name,
        source_agent_run_id=row.source_agent_run_id,
        created_at=_dt(row.created_at),
        updated_at=_dt(row.updated_at),
    )


@router.post("/curriculum/nodes", response_model=CurriculumNodeResponse, status_code=201)
def create_curriculum_node(req: CurriculumNodeCreateRequest, db: Session = Depends(get_db)) -> CurriculumNodeResponse:
    try:
        row = repository.create_curriculum_node(db, **req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    view = repository.get_curriculum_node(db, row.id)
    if view is None:
        raise HTTPException(status_code=500, detail="Curriculum node oluşturuldu ancak okunamadı")
    return _curriculum_response(view)


@router.patch("/curriculum/nodes/{node_id}", response_model=CurriculumNodeResponse)
def update_curriculum_node(
    node_id: str,
    req: CurriculumNodeUpdateRequest,
    db: Session = Depends(get_db),
) -> CurriculumNodeResponse:
    row = repository.update_curriculum_node(db, node_id, **req.model_dump(exclude_unset=True))
    if row is None:
        existing = repository.get_curriculum_node(db, node_id)
        if existing is not None and existing.scope == "constant":
            raise HTTPException(status_code=400, detail="Constant curriculum node güncellenemez")
        raise HTTPException(status_code=404, detail="Curriculum node bulunamadı")
    view = repository.get_curriculum_node(db, row.id)
    if view is None:
        raise HTTPException(status_code=500, detail="Curriculum node güncellendi ancak okunamadı")
    return _curriculum_response(view)


@router.get("/curriculum/tree", response_model=list[CurriculumNodeResponse])
def get_curriculum_tree(db: Session = Depends(get_db)) -> list[CurriculumNodeResponse]:
    rows = repository.list_curriculum_nodes(db)
    children: dict[str | None, list[Any]] = {}
    for row in rows:
        children.setdefault(row.parent_id, []).append(row)

    def build(parent_id: str | None) -> list[CurriculumNodeResponse]:
        return [_curriculum_response(row, build(row.id)) for row in children.get(parent_id, [])]

    return build(None)


@router.get("/curriculum/nodes/{node_id}", response_model=CurriculumNodeResponse)
def get_curriculum_node(node_id: str, db: Session = Depends(get_db)) -> CurriculumNodeResponse:
    row = repository.get_curriculum_node(db, node_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Curriculum node bulunamadı")
    return _curriculum_response(row)


@router.delete("/curriculum/nodes/{node_id}", status_code=204, response_class=Response)
def delete_curriculum_node(node_id: str, db: Session = Depends(get_db)) -> Response:
    if not repository.delete_curriculum_node(db, node_id):
        existing = repository.get_curriculum_node(db, node_id)
        if existing is not None and existing.scope == "constant":
            raise HTTPException(status_code=400, detail="Constant curriculum node silinemez")
        raise HTTPException(status_code=404, detail="Curriculum node bulunamadı")
    return Response(status_code=204)


@router.post("/properties", response_model=PropertyResponse, status_code=201)
def create_property(req: PropertyCreateRequest, db: Session = Depends(get_db)) -> PropertyResponse:
    try:
        row = repository.create_property_definition(db, **req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _property_response(row)


@router.get("/properties", response_model=list[PropertyResponse])
def list_properties(
    defined_at_curriculum_node_id: str | None = Query(default=None),
    parent_property_id: str | None = Query(default=None),
    active_only: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> list[PropertyResponse]:
    rows = repository.list_property_definitions(
        db,
        defined_at_curriculum_node_id=defined_at_curriculum_node_id,
        parent_property_id=parent_property_id,
        active_only=active_only,
    )
    return [_property_response(row) for row in rows]


@router.patch("/properties/{property_id}", response_model=PropertyResponse)
def update_property(
    property_id: str,
    req: PropertyUpdateRequest,
    db: Session = Depends(get_db),
) -> PropertyResponse:
    row = repository.update_property_definition(db, property_id, **req.model_dump(exclude_unset=True))
    if row is None:
        raise HTTPException(status_code=404, detail="Property bulunamadı")
    return _property_response(row)


@router.get("/properties/effective/{curriculum_node_id}", response_model=list[PropertyResponse])
def get_effective_properties(curriculum_node_id: str, db: Session = Depends(get_db)) -> list[PropertyResponse]:
    try:
        rows = repository.list_effective_properties(db, curriculum_node_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return [_property_response(row) for row in rows]


@router.get("/properties/{property_id}", response_model=PropertyResponse)
def get_property(property_id: str, db: Session = Depends(get_db)) -> PropertyResponse:
    row = repository.get_property_definition(db, property_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Property bulunamadı")
    return _property_response(row)


@router.delete("/properties/{property_id}", status_code=204, response_class=Response)
def delete_property(property_id: str, db: Session = Depends(get_db)) -> Response:
    try:
        deleted = repository.delete_property_definition(db, property_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not deleted:
        raise HTTPException(status_code=404, detail="Property bulunamadı")
    return Response(status_code=204)


@router.post("/yaml-templates", response_model=YamlTemplateResponse, status_code=201)
def create_yaml_template(req: YamlTemplateCreateRequest, db: Session = Depends(get_db)) -> YamlTemplateResponse:
    try:
        row = repository.create_yaml_template(db, **req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _template_response(row)


@router.patch("/yaml-templates/{template_id}", response_model=YamlTemplateResponse)
def update_yaml_template(
    template_id: str,
    req: YamlTemplateUpdateRequest,
    db: Session = Depends(get_db),
) -> YamlTemplateResponse:
    row = repository.update_yaml_template(db, template_id, **req.model_dump(exclude_unset=True))
    if row is None:
        raise HTTPException(status_code=404, detail="YAML template bulunamadı")
    return _template_response(row)


@router.get("/yaml-templates", response_model=list[YamlTemplateResponse])
def list_yaml_templates(
    curriculum_folder_node_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[YamlTemplateResponse]:
    return [_template_response(row) for row in repository.list_yaml_templates(db, curriculum_folder_node_id)]


@router.get("/yaml-templates/{template_id}", response_model=YamlTemplateResponse)
def get_yaml_template(template_id: str, db: Session = Depends(get_db)) -> YamlTemplateResponse:
    row = repository.get_yaml_template(db, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="YAML template bulunamadı")
    return _template_response(row)


@router.delete("/yaml-templates/{template_id}", status_code=204, response_class=Response)
def delete_yaml_template(template_id: str, db: Session = Depends(get_db)) -> Response:
    try:
        deleted = repository.delete_yaml_template(db, template_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not deleted:
        raise HTTPException(status_code=404, detail="YAML template bulunamadı")
    return Response(status_code=204)


@router.post("/yaml-instances", response_model=YamlInstanceResponse, status_code=201)
def create_yaml_instance(req: YamlInstanceCreateRequest, db: Session = Depends(get_db)) -> YamlInstanceResponse:
    try:
        row = repository.create_yaml_instance(db, **req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _instance_response(row)


@router.patch("/yaml-instances/{instance_id}", response_model=YamlInstanceResponse)
def update_yaml_instance(
    instance_id: str,
    req: YamlInstanceUpdateRequest,
    db: Session = Depends(get_db),
) -> YamlInstanceResponse:
    row = repository.update_yaml_instance(db, instance_id, **req.model_dump(exclude_unset=True))
    if row is None:
        raise HTTPException(status_code=404, detail="YAML instance bulunamadı")
    return _instance_response(row)


@router.get("/yaml-instances", response_model=list[YamlInstanceResponse])
def list_yaml_instances(
    template_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[YamlInstanceResponse]:
    return [_instance_response(row) for row in repository.list_yaml_instances(db, template_id)]


@router.get("/yaml-instances/{instance_id}", response_model=YamlInstanceResponse)
def get_yaml_instance(instance_id: str, db: Session = Depends(get_db)) -> YamlInstanceResponse:
    row = repository.get_yaml_instance(db, instance_id)
    if row is None:
        raise HTTPException(status_code=404, detail="YAML instance bulunamadı")
    return _instance_response(row)


@router.delete("/yaml-instances/{instance_id}", status_code=204, response_class=Response)
def delete_yaml_instance(instance_id: str, db: Session = Depends(get_db)) -> Response:
    if not repository.delete_yaml_instance(db, instance_id):
        raise HTTPException(status_code=404, detail="YAML instance bulunamadı")
    return Response(status_code=204)


@router.post("/yaml-instances/{instance_id}/render", response_model=YamlRenderResponse)
def render_yaml_instance(instance_id: str, db: Session = Depends(get_db)) -> YamlRenderResponse:
    row = repository.get_yaml_instance(db, instance_id)
    if row is None:
        raise HTTPException(status_code=404, detail="YAML instance bulunamadı")
    values = _json(row.values_json) or {}
    rendered = yaml.safe_dump(values, allow_unicode=True, sort_keys=False)
    row = repository.update_yaml_instance(db, instance_id, rendered_yaml_text=rendered)
    artifact = repository.create_artifact(
        db,
        kind="yaml_rendered",
        content_json=values,
        content_text=rendered,
    )
    return YamlRenderResponse(
        instance_id=instance_id,
        artifact_id=artifact.id,
        yaml_content=values,
        rendered_yaml_text=rendered,
    )


@router.get("/artifacts", response_model=list[ArtifactResponse])
def list_artifacts(
    kind: str | None = Query(default=None),
    favorites_only: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> list[ArtifactResponse]:
    try:
        rows = repository.list_artifacts(db, kind=kind, favorites_only=favorites_only)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return [_artifact_response(row) for row in rows]


@router.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(artifact_id: str, db: Session = Depends(get_db)) -> ArtifactResponse:
    row = repository.get_artifact(db, artifact_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Artifact bulunamadı")
    return _artifact_response(row)


@router.patch("/artifacts/{artifact_id}/favorite", response_model=ArtifactResponse)
def set_artifact_favorite(
    artifact_id: str,
    req: ArtifactFavoriteRequest,
    db: Session = Depends(get_db),
) -> ArtifactResponse:
    row = repository.set_artifact_favorite(db, artifact_id, req.is_favorite)
    if row is None:
        raise HTTPException(status_code=404, detail="Artifact bulunamadı")
    return _artifact_response(row)


@router.delete("/artifacts/{artifact_id}", status_code=204, response_class=Response)
def delete_artifact(artifact_id: str, db: Session = Depends(get_db)) -> Response:
    if not repository.delete_artifact(db, artifact_id):
        raise HTTPException(status_code=404, detail="Artifact bulunamadı")
    return Response(status_code=204)


@router.get("/assets/{artifact_id}")
def get_asset(artifact_id: str, db: Session = Depends(get_db)) -> Response:
    row = repository.get_artifact(db, artifact_id)
    if row is None or not row.object_bucket or not row.object_key:
        raise HTTPException(status_code=404, detail="Asset bulunamadı")
    try:
        data, content_type = ObjectStorageService().get_object(bucket=row.object_bucket, key=row.object_key)
    except ClientError:
        raise HTTPException(status_code=404, detail="Asset bulunamadı")
    return Response(content=data, media_type=content_type or row.mime_type or "application/octet-stream")
