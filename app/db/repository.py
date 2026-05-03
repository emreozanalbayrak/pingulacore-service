from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


AGENT_TABLES: dict[str, type[models.Base]] = {
    "main_generate_question": models.AgentMainQuestionRun,
    "main_generate_layout": models.AgentMainLayoutRun,
    "main_generate_html": models.AgentMainHtmlRun,
    "validation_extract_rules": models.AgentRuleExtractionRun,
    "validation_evaluate_rule": models.AgentRuleEvaluationRun,
    "validation_question_layout": models.AgentQuestionLayoutValidationRun,
    "validation_layout_html": models.AgentLayoutHtmlValidationRun,
    "helper_generate_composite_image": models.AgentCompositeImageRun,
}

FAVORITE_KINDS = {"question", "layout"}
STORED_JSON_KINDS = {"q_json", "layout"}
ARTIFACT_KINDS = {
    "yaml_rendered",
    "question",
    "layout",
    "html",
    "generated_asset",
    "catalog_asset",
    "rendered_image",
}


def _to_json_text(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _extract_question_meta(input_payload: Any, output_payload: Any) -> tuple[str | None, str | None]:
    candidates = [output_payload, input_payload]
    for payload in candidates:
        if not isinstance(payload, dict):
            continue

        question_id = payload.get("question_id")
        schema_version = payload.get("schema_version")
        if question_id or schema_version:
            return (
                str(question_id) if question_id is not None else None,
                str(schema_version) if schema_version is not None else None,
            )

        q = payload.get("question") or payload.get("question_json")
        if isinstance(q, dict):
            qid = q.get("question_id")
            qschema = q.get("schema_version")
            if qid or qschema:
                return (
                    str(qid) if qid is not None else None,
                    str(qschema) if qschema is not None else None,
                )

    return None, None


def create_pipeline(
    db: Session,
    yaml_filename: str,
    retry_config: dict[str, Any],
    yaml_instance_id: str | None = None,
) -> models.Pipeline:
    row = models.Pipeline(
        id=str(uuid4()),
        mode="full",
        yaml_filename=yaml_filename,
        yaml_instance_id=yaml_instance_id,
        status="running",
        retry_config_json=_to_json_text(retry_config),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def finish_pipeline(db: Session, pipeline_id: str, status: str, error: str | None = None) -> None:
    row = db.get(models.Pipeline, pipeline_id)
    if row is None:
        return
    row.status = status
    row.error = error
    row.finished_at = utcnow()
    db.add(row)
    db.commit()


def create_sub_pipeline(
    db: Session,
    *,
    kind: str,
    mode: str,
    pipeline_id: str | None,
    input_payload: Any,
) -> models.SubPipeline:
    row = models.SubPipeline(
        id=str(uuid4()),
        pipeline_id=pipeline_id,
        kind=kind,
        mode=mode,
        status="running",
        input_json=_to_json_text(input_payload),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def finish_sub_pipeline(
    db: Session,
    sub_pipeline_id: str,
    *,
    status: str,
    output_payload: Any | None = None,
    error: str | None = None,
) -> None:
    row = db.get(models.SubPipeline, sub_pipeline_id)
    if row is None:
        return
    row.status = status
    row.output_json = _to_json_text(output_payload) if output_payload is not None else None
    row.error = error
    row.finished_at = utcnow()
    db.add(row)
    db.commit()


def record_agent_run(
    db: Session,
    *,
    agent_name: str,
    mode: str,
    attempt_no: int,
    status: str,
    input_payload: Any,
    output_payload: Any | None,
    feedback_text: str | None,
    error: str | None,
    model_name: str,
    pipeline_id: str | None,
    sub_pipeline_id: str | None,
) -> str:
    table = AGENT_TABLES[agent_name]
    run_id = str(uuid4())
    question_id, schema_version = _extract_question_meta(input_payload, output_payload)

    row = table(
        id=run_id,
        mode=mode,
        pipeline_id=pipeline_id,
        sub_pipeline_id=sub_pipeline_id,
        attempt_no=attempt_no,
        status=status,
        input_json=_to_json_text(input_payload),
        output_json=_to_json_text(output_payload) if output_payload is not None else None,
        feedback_text=feedback_text,
        error=error,
        model_name=model_name,
        question_id=question_id,
        schema_version=schema_version,
        started_at=utcnow(),
        finished_at=utcnow(),
    )
    db.add(row)

    link = models.PipelineAgentLink(
        pipeline_id=pipeline_id,
        sub_pipeline_id=sub_pipeline_id,
        agent_name=agent_name,
        agent_table=table.__tablename__,
        agent_run_id=run_id,
    )
    db.add(link)
    db.commit()
    return run_id


def record_pipeline_log(
    db: Session,
    *,
    mode: str,
    level: str,
    component: str,
    message: str,
    pipeline_id: str | None,
    sub_pipeline_id: str | None,
    details: Any | None = None,
) -> int:
    row = models.PipelineLog(
        pipeline_id=pipeline_id,
        sub_pipeline_id=sub_pipeline_id,
        mode=mode,
        level=level,
        component=component,
        message=message,
        details_json=_to_json_text(details) if details is not None else None,
        created_at=utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


def list_pipeline_logs(db: Session, pipeline_id: str) -> list[models.PipelineLog]:
    stmt = (
        select(models.PipelineLog)
        .where(models.PipelineLog.pipeline_id == pipeline_id)
        .order_by(models.PipelineLog.id.asc())
    )
    return list(db.scalars(stmt).all())


def list_sub_pipeline_logs(db: Session, sub_pipeline_id: str) -> list[models.PipelineLog]:
    stmt = (
        select(models.PipelineLog)
        .where(models.PipelineLog.sub_pipeline_id == sub_pipeline_id)
        .order_by(models.PipelineLog.id.asc())
    )
    return list(db.scalars(stmt).all())


def get_pipeline(db: Session, pipeline_id: str) -> models.Pipeline | None:
    return db.get(models.Pipeline, pipeline_id)


def get_sub_pipeline(db: Session, sub_pipeline_id: str) -> models.SubPipeline | None:
    return db.get(models.SubPipeline, sub_pipeline_id)


def list_pipeline_links(db: Session, pipeline_id: str) -> list[models.PipelineAgentLink]:
    stmt = (
        select(models.PipelineAgentLink)
        .where(models.PipelineAgentLink.pipeline_id == pipeline_id)
        .order_by(models.PipelineAgentLink.id.asc())
    )
    return list(db.scalars(stmt).all())


def list_sub_pipeline_links(db: Session, sub_pipeline_id: str) -> list[models.PipelineAgentLink]:
    stmt = (
        select(models.PipelineAgentLink)
        .where(models.PipelineAgentLink.sub_pipeline_id == sub_pipeline_id)
        .order_by(models.PipelineAgentLink.id.asc())
    )
    return list(db.scalars(stmt).all())


def get_agent_run(db: Session, agent_name: str, run_id: str) -> Any | None:
    table = AGENT_TABLES.get(agent_name)
    if table is None:
        return None
    return db.get(table, run_id)


def _clean_text(value: str | None) -> str:
    return (value or "").strip()


def _normalize_property_default_value(data_type: str, default_value: Any | None) -> str | None:
    safe_type = _clean_text(data_type)
    if safe_type == "object":
        return None
    if default_value is None:
        return None
    if isinstance(default_value, list):
        if safe_type != "array":
            raise ValueError("default_value yalnızca array tipinde liste olarak verilebilir")
        return ";".join(_clean_text(str(item)) for item in default_value if _clean_text(str(item)))
    text = _clean_text(str(default_value))
    return text or None


@dataclass
class CurriculumNodeView:
    id: str
    parent_id: str | None
    node_type: str
    name: str
    slug: str
    code: str | None
    sort_order: int
    depth: int
    path: str
    is_active: bool
    scope: str
    grade: str | None = None
    subject: str | None = None
    theme: str | None = None


def _constant_to_view(row: models.CurriculumConstantNode) -> CurriculumNodeView:
    return CurriculumNodeView(
        id=row.id,
        parent_id=row.parent_id,
        node_type=row.node_type,
        name=row.name,
        slug=row.slug,
        code=row.code,
        sort_order=row.sort_order,
        depth=row.depth,
        path=row.path,
        is_active=row.is_active,
        scope="constant",
    )


def _folder_to_view(row: models.CurriculumFolderNode, parent_id: str | None) -> CurriculumNodeView:
    return CurriculumNodeView(
        id=row.id,
        parent_id=parent_id,
        node_type=row.node_type,
        name=row.name,
        slug=row.slug,
        code=row.code,
        sort_order=row.sort_order,
        depth=row.depth,
        path=row.path,
        is_active=row.is_active,
        scope="folder",
        grade=row.grade,
        subject=row.subject,
        theme=row.theme,
    )


def _get_constant_theme_node(
    db: Session,
    *,
    grade: str,
    subject: str,
    theme: str,
) -> models.CurriculumConstantNode | None:
    safe_grade = _clean_text(grade)
    safe_subject = _clean_text(subject)
    safe_theme = _clean_text(theme)
    if not safe_grade or not safe_subject or not safe_theme:
        return None
    target_path = f"root/{safe_grade}/{safe_subject}/{safe_theme}"
    stmt = select(models.CurriculumConstantNode).where(
        models.CurriculumConstantNode.path == target_path,
        models.CurriculumConstantNode.node_type == "theme",
    )
    return db.scalar(stmt)


def _resolve_curriculum_node_scope(db: Session, node_id: str) -> str | None:
    if db.get(models.CurriculumConstantNode, node_id) is not None:
        return "constant"
    if db.get(models.CurriculumFolderNode, node_id) is not None:
        return "folder"
    return None


def create_curriculum_node(
    db: Session,
    *,
    parent_id: str | None,
    node_type: str,
    name: str,
    slug: str,
    grade: str | None = None,
    subject: str | None = None,
    theme: str | None = None,
    code: str | None = None,
    sort_order: int = 0,
) -> models.CurriculumFolderNode:
    safe_slug = _clean_text(slug)
    if not safe_slug:
        raise ValueError("slug boş olamaz")

    safe_node_type = _clean_text(node_type) or "folder"
    if safe_node_type != "folder":
        raise ValueError("Yeni curriculum node yalnızca folder tipinde oluşturulabilir")

    raw_grade = _clean_text(grade)
    raw_subject = _clean_text(subject)
    raw_theme = _clean_text(theme)

    parent = db.get(models.CurriculumFolderNode, parent_id) if parent_id else None
    if parent_id and parent is None:
        raise ValueError("Parent folder node bulunamadı")

    if parent is not None:
        node_grade = parent.grade
        node_subject = parent.subject
        node_theme = parent.theme
        depth = parent.depth + 1
        path = f"{parent.path}/{safe_slug}"
    else:
        if not raw_grade or not raw_subject or not raw_theme:
            raise ValueError("Top-level folder için grade, subject ve theme zorunludur")
        theme_node = _get_constant_theme_node(
            db,
            grade=raw_grade,
            subject=raw_subject,
            theme=raw_theme,
        )
        if theme_node is None:
            raise ValueError("Belirtilen grade/subject/theme constant theme node bulunamadı")
        node_grade = raw_grade
        node_subject = raw_subject
        node_theme = raw_theme
        depth = theme_node.depth + 1
        path = f"{theme_node.path}/{safe_slug}"

    row = models.CurriculumFolderNode(
        id=str(uuid4()),
        parent_id=parent_id,
        node_type="folder",
        name=_clean_text(name),
        slug=safe_slug,
        code=_clean_text(code) or None,
        sort_order=sort_order,
        depth=depth,
        path=path,
        grade=node_grade,
        subject=node_subject,
        theme=node_theme,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_curriculum_node(db: Session, node_id: str, **values: Any) -> models.CurriculumFolderNode | None:
    row = db.get(models.CurriculumFolderNode, node_id)
    if row is None:
        return None
    for field in ("name", "code", "sort_order", "is_active"):
        if field in values and values[field] is not None:
            setattr(row, field, values[field])
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_curriculum_node(db: Session, node_id: str) -> CurriculumNodeView | None:
    constant_row = db.get(models.CurriculumConstantNode, node_id)
    if constant_row is not None:
        return _constant_to_view(constant_row)

    folder_row = db.get(models.CurriculumFolderNode, node_id)
    if folder_row is None:
        return None

    synthetic_parent_id = folder_row.parent_id
    if synthetic_parent_id is None:
        theme_node = _get_constant_theme_node(
            db,
            grade=folder_row.grade,
            subject=folder_row.subject,
            theme=folder_row.theme,
        )
        synthetic_parent_id = theme_node.id if theme_node else None
    return _folder_to_view(folder_row, synthetic_parent_id)


def list_curriculum_nodes(db: Session) -> list[CurriculumNodeView]:
    constant_rows = list(
        db.scalars(
            select(models.CurriculumConstantNode).order_by(
                models.CurriculumConstantNode.depth.asc(),
                models.CurriculumConstantNode.sort_order.asc(),
                models.CurriculumConstantNode.name.asc(),
            )
        ).all()
    )
    folder_rows = list(
        db.scalars(
            select(models.CurriculumFolderNode).order_by(
                models.CurriculumFolderNode.depth.asc(),
                models.CurriculumFolderNode.sort_order.asc(),
                models.CurriculumFolderNode.name.asc(),
            )
        ).all()
    )

    constant_theme_id_by_key = {
        (row.path): row.id
        for row in constant_rows
        if row.node_type == "theme"
    }
    views: list[CurriculumNodeView] = [_constant_to_view(row) for row in constant_rows]
    for row in folder_rows:
        synthetic_parent_id = row.parent_id
        if synthetic_parent_id is None:
            key_path = f"root/{row.grade}/{row.subject}/{row.theme}"
            synthetic_parent_id = constant_theme_id_by_key.get(key_path)
        views.append(_folder_to_view(row, synthetic_parent_id))
    return views


def delete_curriculum_node(db: Session, node_id: str) -> bool:
    row = db.get(models.CurriculumFolderNode, node_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def create_property_definition(
    db: Session,
    *,
    defined_at_curriculum_node_id: str,
    parent_property_id: str | None,
    label: str,
    description: str | None = None,
    property_key: str,
    canonical_path: str,
    data_type: str,
    default_value: str | None = None,
    constraints: Any | None = None,
    is_required: bool = False,
) -> models.PropertyDefinition:
    safe_data_type = _clean_text(data_type)
    if _resolve_curriculum_node_scope(db, defined_at_curriculum_node_id) is None:
        raise ValueError("Property için curriculum node bulunamadı")
    if parent_property_id and db.get(models.PropertyDefinition, parent_property_id) is None:
        raise ValueError("Parent property bulunamadı")
    normalized_default = _normalize_property_default_value(safe_data_type, default_value)
    row = models.PropertyDefinition(
        id=str(uuid4()),
        defined_at_curriculum_node_id=defined_at_curriculum_node_id,
        parent_property_id=parent_property_id,
        label=_clean_text(label),
        description=_clean_text(description) or None,
        property_key=_clean_text(property_key),
        canonical_path=_clean_text(canonical_path),
        data_type=safe_data_type,
        default_value=normalized_default,
        constraints_json=_to_json_text(constraints) if constraints is not None else None,
        is_required=is_required,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_property_definition(db: Session, property_id: str, **values: Any) -> models.PropertyDefinition | None:
    row = db.get(models.PropertyDefinition, property_id)
    if row is None:
        return None
    text_fields = {"label", "description", "property_key", "canonical_path", "data_type"}
    for field in ("label", "description", "property_key", "canonical_path", "data_type", "is_required", "is_active"):
        if field in values and values[field] is not None:
            value = _clean_text(values[field]) if field in text_fields else values[field]
            setattr(row, field, value or None if field == "description" else value)
    if "default_value" in values:
        row.default_value = _normalize_property_default_value(row.data_type, values["default_value"])
    elif "data_type" in values:
        row.default_value = _normalize_property_default_value(row.data_type, row.default_value)
    if "constraints" in values:
        row.constraints_json = _to_json_text(values["constraints"]) if values["constraints"] is not None else None
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_property_definition(db: Session, property_id: str) -> models.PropertyDefinition | None:
    return db.get(models.PropertyDefinition, property_id)


def list_property_definitions(
    db: Session,
    *,
    defined_at_curriculum_node_id: str | None = None,
    parent_property_id: str | None = None,
    active_only: bool = False,
) -> list[models.PropertyDefinition]:
    stmt = select(models.PropertyDefinition).order_by(
        models.PropertyDefinition.canonical_path.asc(),
        models.PropertyDefinition.created_at.asc(),
    )
    if defined_at_curriculum_node_id:
        stmt = stmt.where(models.PropertyDefinition.defined_at_curriculum_node_id == defined_at_curriculum_node_id)
    if parent_property_id:
        stmt = stmt.where(models.PropertyDefinition.parent_property_id == parent_property_id)
    if active_only:
        stmt = stmt.where(models.PropertyDefinition.is_active.is_(True))
    return list(db.scalars(stmt).all())


def delete_property_definition(db: Session, property_id: str) -> bool:
    row = db.get(models.PropertyDefinition, property_id)
    if row is None:
        return False
    subtree_ids = [property_id]
    frontier = [property_id]
    while frontier:
        child_ids = list(
            db.scalars(
                select(models.PropertyDefinition.id).where(
                    models.PropertyDefinition.parent_property_id.in_(frontier)
                )
            ).all()
        )
        if not child_ids:
            break
        subtree_ids.extend(child_ids)
        frontier = child_ids
    in_use = db.scalar(
        select(models.YamlInstancePropertyValue.id)
        .where(models.YamlInstancePropertyValue.property_definition_id.in_(subtree_ids))
        .limit(1)
    )
    if in_use is not None:
        raise ValueError("Bu property veya alt property'leri YAML instance değerleri tarafından kullanılıyor; önce ilgili değerleri silin")
    db.delete(row)
    db.commit()
    return True


def list_effective_properties(db: Session, curriculum_node_id: str) -> list[models.PropertyDefinition]:
    scope = _resolve_curriculum_node_scope(db, curriculum_node_id)
    if scope is None:
        raise ValueError("curriculum node bulunamadı")

    ancestor_ids: list[str] = []
    if scope == "constant":
        current = db.get(models.CurriculumConstantNode, curriculum_node_id)
        chain: list[str] = []
        while current is not None:
            chain.append(current.id)
            current = current.parent
        ancestor_ids.extend(reversed(chain))
    else:
        folder = db.get(models.CurriculumFolderNode, curriculum_node_id)
        if folder is None:
            raise ValueError("curriculum node bulunamadı")

        theme_node = _get_constant_theme_node(
            db,
            grade=folder.grade,
            subject=folder.subject,
            theme=folder.theme,
        )
        if theme_node is not None:
            current_constant = theme_node
            constant_chain: list[str] = []
            while current_constant is not None:
                constant_chain.append(current_constant.id)
                current_constant = current_constant.parent
            ancestor_ids.extend(reversed(constant_chain))

        current_folder: models.CurriculumFolderNode | None = folder
        folder_chain: list[str] = []
        while current_folder is not None:
            folder_chain.append(current_folder.id)
            current_folder = current_folder.parent
        ancestor_ids.extend(reversed(folder_chain))

    stmt = (
        select(models.PropertyDefinition)
        .where(models.PropertyDefinition.defined_at_curriculum_node_id.in_(ancestor_ids))
        .where(models.PropertyDefinition.is_active.is_(True))
        .order_by(models.PropertyDefinition.created_at.asc())
    )
    by_path: dict[str, models.PropertyDefinition] = {}
    for row in db.scalars(stmt).all():
        by_path[row.canonical_path] = row
    return sorted(by_path.values(), key=lambda item: item.canonical_path)


def create_yaml_template(
    db: Session,
    *,
    curriculum_folder_node_id: str,
    template_code: str,
    title: str,
    description: str | None,
    field_schema: Any,
    schema_version: str = "v1",
    created_by: str | None = None,
) -> models.YamlTemplate:
    node = db.get(models.CurriculumFolderNode, curriculum_folder_node_id)
    if node is None:
        raise ValueError("curriculum folder node bulunamadı")
    row = models.YamlTemplate(
        id=str(uuid4()),
        curriculum_folder_node_id=curriculum_folder_node_id,
        template_code=_clean_text(template_code),
        title=_clean_text(title),
        description=description,
        field_schema_json=_to_json_text(field_schema),
        schema_version=schema_version,
        created_by=created_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_yaml_template(db: Session, template_id: str, **values: Any) -> models.YamlTemplate | None:
    row = db.get(models.YamlTemplate, template_id)
    if row is None:
        return None
    for field in ("template_code", "title", "description", "schema_version", "status"):
        if field in values and values[field] is not None:
            setattr(row, field, values[field])
    if "field_schema" in values and values["field_schema"] is not None:
        row.field_schema_json = _to_json_text(values["field_schema"])
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_yaml_templates(db: Session, curriculum_folder_node_id: str | None = None) -> list[models.YamlTemplate]:
    stmt = select(models.YamlTemplate).order_by(models.YamlTemplate.created_at.desc())
    if curriculum_folder_node_id:
        stmt = stmt.where(models.YamlTemplate.curriculum_folder_node_id == curriculum_folder_node_id)
    return list(db.scalars(stmt).all())


def get_yaml_template(db: Session, template_id: str) -> models.YamlTemplate | None:
    return db.get(models.YamlTemplate, template_id)


def delete_yaml_template(db: Session, template_id: str) -> bool:
    row = db.get(models.YamlTemplate, template_id)
    if row is None:
        return False
    has_instances = db.scalar(
        select(models.YamlInstance.id)
        .where(models.YamlInstance.template_id == template_id)
        .limit(1)
    )
    if has_instances is not None:
        raise ValueError("Bu YAML template'e bağlı instance kayıtları var; önce instance'ları silin")
    db.delete(row)
    db.commit()
    return True


def create_yaml_instance(
    db: Session,
    *,
    template_id: str,
    instance_name: str,
    values: Any,
    rendered_yaml_text: str | None = None,
    status: str = "draft",
    created_by: str | None = None,
) -> models.YamlInstance:
    if db.get(models.YamlTemplate, template_id) is None:
        raise ValueError("YAML template bulunamadı")
    row = models.YamlInstance(
        id=str(uuid4()),
        template_id=template_id,
        instance_name=_clean_text(instance_name),
        status=status,
        values_json=_to_json_text(values),
        rendered_yaml_text=rendered_yaml_text,
        created_by=created_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_yaml_instance(db: Session, instance_id: str, **values: Any) -> models.YamlInstance | None:
    row = db.get(models.YamlInstance, instance_id)
    if row is None:
        return None
    for field in ("instance_name", "status", "rendered_yaml_text"):
        if field in values and values[field] is not None:
            setattr(row, field, values[field])
    if "values" in values and values["values"] is not None:
        row.values_json = _to_json_text(values["values"])
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_yaml_instances(db: Session, template_id: str | None = None) -> list[models.YamlInstance]:
    stmt = select(models.YamlInstance).order_by(models.YamlInstance.created_at.desc())
    if template_id:
        stmt = stmt.where(models.YamlInstance.template_id == template_id)
    return list(db.scalars(stmt).all())


def get_yaml_instance(db: Session, instance_id: str) -> models.YamlInstance | None:
    return db.get(models.YamlInstance, instance_id)


def delete_yaml_instance(db: Session, instance_id: str) -> bool:
    row = db.get(models.YamlInstance, instance_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def create_artifact(
    db: Session,
    *,
    kind: str,
    content_json: Any | None = None,
    content_text: str | None = None,
    object_bucket: str | None = None,
    object_key: str | None = None,
    mime_type: str | None = None,
    source_pipeline_id: str | None = None,
    source_sub_pipeline_id: str | None = None,
    source_agent_name: str | None = None,
    source_agent_run_id: str | None = None,
) -> models.Artifact:
    safe_kind = _clean_text(kind)
    if safe_kind not in ARTIFACT_KINDS:
        raise ValueError("Geçersiz artifact türü")
    row = models.Artifact(
        id=str(uuid4()),
        kind=safe_kind,
        content_json=_to_json_text(content_json) if content_json is not None else None,
        content_text=content_text,
        object_bucket=object_bucket,
        object_key=object_key,
        mime_type=mime_type,
        source_pipeline_id=source_pipeline_id,
        source_sub_pipeline_id=source_sub_pipeline_id,
        source_agent_name=source_agent_name,
        source_agent_run_id=source_agent_run_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_artifact(db: Session, artifact_id: str) -> models.Artifact | None:
    return db.get(models.Artifact, artifact_id)


def get_artifact_by_object(db: Session, *, bucket: str, key: str) -> models.Artifact | None:
    stmt = select(models.Artifact).where(
        models.Artifact.object_bucket == bucket,
        models.Artifact.object_key == key,
    )
    return db.scalar(stmt)


def list_artifacts(db: Session, *, kind: str | None = None, favorites_only: bool = False) -> list[models.Artifact]:
    stmt = select(models.Artifact).order_by(models.Artifact.created_at.desc())
    if kind:
        safe_kind = _clean_text(kind)
        if safe_kind not in ARTIFACT_KINDS:
            raise ValueError("Geçersiz artifact türü")
        stmt = stmt.where(models.Artifact.kind == safe_kind)
    if favorites_only:
        stmt = stmt.where(models.Artifact.is_favorite.is_(True))
    return list(db.scalars(stmt).all())


def set_artifact_favorite(db: Session, artifact_id: str, is_favorite: bool) -> models.Artifact | None:
    row = db.get(models.Artifact, artifact_id)
    if row is None:
        return None
    row.is_favorite = bool(is_favorite)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_artifact(db: Session, artifact_id: str) -> bool:
    row = db.get(models.Artifact, artifact_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def create_favorite_output(
    db: Session,
    *,
    name: str,
    kind: str,
    content: Any,
    source_sub_pipeline_id: str | None = None,
) -> models.FavoriteOutput:
    safe_name = (name or "").strip()
    safe_kind = (kind or "").strip().lower()
    if not safe_name:
        raise ValueError("Favori adı boş olamaz")
    if safe_kind not in FAVORITE_KINDS:
        raise ValueError("Geçersiz favori türü")
    if content is None:
        raise ValueError("Favori içeriği boş olamaz")

    row = models.FavoriteOutput(
        name=safe_name,
        kind=safe_kind,
        content_json=_to_json_text(content),
        source_sub_pipeline_id=source_sub_pipeline_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_favorite_outputs(db: Session, kind: str | None = None) -> list[models.FavoriteOutput]:
    stmt = select(models.FavoriteOutput)
    if kind is not None:
        safe_kind = (kind or "").strip().lower()
        if safe_kind not in FAVORITE_KINDS:
            raise ValueError("Geçersiz favori türü")
        stmt = stmt.where(models.FavoriteOutput.kind == safe_kind)
    stmt = stmt.order_by(models.FavoriteOutput.created_at.desc(), models.FavoriteOutput.id.desc())
    return list(db.scalars(stmt).all())


def get_favorite_output(db: Session, favorite_id: int) -> models.FavoriteOutput | None:
    return db.get(models.FavoriteOutput, favorite_id)


def delete_favorite_output(db: Session, favorite_id: int) -> bool:
    row = db.get(models.FavoriteOutput, favorite_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def _validate_stored_kind(kind: str) -> str:
    safe_kind = (kind or "").strip().lower()
    if safe_kind not in STORED_JSON_KINDS:
        raise ValueError("Geçersiz stored json türü")
    return safe_kind


def _validate_filename(filename: str) -> str:
    token = Path(filename)
    if token.is_absolute() or ".." in token.parts or token.name != filename:
        raise ValueError("Geçersiz dosya adı")
    return token.name


def upsert_stored_json_output(
    db: Session,
    *,
    kind: str,
    filename: str,
    content: Any,
    source_sub_pipeline_id: str | None = None,
) -> models.StoredJsonOutput:
    safe_kind = _validate_stored_kind(kind)
    safe_filename = _validate_filename(filename)
    if content is None:
        raise ValueError("Stored JSON içeriği boş olamaz")
    if not isinstance(content, dict):
        raise ValueError("Stored JSON üst seviye dict olmalı")

    stmt = select(models.StoredJsonOutput).where(
        models.StoredJsonOutput.kind == safe_kind,
        models.StoredJsonOutput.filename == safe_filename,
    )
    row = db.scalar(stmt)
    if row is None:
        row = models.StoredJsonOutput(
            kind=safe_kind,
            filename=safe_filename,
            content_json=_to_json_text(content),
            source_sub_pipeline_id=source_sub_pipeline_id,
        )
    else:
        row.content_json = _to_json_text(content)
        if source_sub_pipeline_id is not None:
            row.source_sub_pipeline_id = source_sub_pipeline_id

    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_stored_json_outputs(
    db: Session,
    *,
    kind: str,
    favorites_only: bool = False,
) -> list[models.StoredJsonOutput]:
    safe_kind = _validate_stored_kind(kind)
    stmt = (
        select(models.StoredJsonOutput)
        .where(models.StoredJsonOutput.kind == safe_kind)
        .order_by(models.StoredJsonOutput.created_at.desc(), models.StoredJsonOutput.id.desc())
    )
    if favorites_only:
        stmt = stmt.where(models.StoredJsonOutput.is_favorite.is_(True))
    return list(db.scalars(stmt).all())


def get_stored_json_output(db: Session, *, kind: str, filename: str) -> models.StoredJsonOutput | None:
    safe_kind = _validate_stored_kind(kind)
    safe_filename = _validate_filename(filename)
    stmt = select(models.StoredJsonOutput).where(
        models.StoredJsonOutput.kind == safe_kind,
        models.StoredJsonOutput.filename == safe_filename,
    )
    return db.scalar(stmt)


def set_stored_json_output_favorite(
    db: Session,
    *,
    kind: str,
    filename: str,
    is_favorite: bool,
) -> models.StoredJsonOutput | None:
    row = get_stored_json_output(db, kind=kind, filename=filename)
    if row is None:
        return None
    row.is_favorite = bool(is_favorite)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_stored_json_output(db: Session, *, kind: str, filename: str) -> bool:
    row = get_stored_json_output(db, kind=kind, filename=filename)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def parse_json(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except Exception:
        return value
