from __future__ import annotations

import json
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


def create_pipeline(db: Session, yaml_filename: str, retry_config: dict[str, Any]) -> models.Pipeline:
    row = models.Pipeline(
        id=str(uuid4()),
        mode="full",
        yaml_filename=yaml_filename,
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
