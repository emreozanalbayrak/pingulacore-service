from __future__ import annotations

import json
from datetime import datetime, timezone
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


def parse_json(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except Exception:
        return value
