from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.config import get_agent_settings
from app.core.config import get_settings
from app.db import repository
from app.db.database import get_db
from app.schemas.api import (
    FullPipelineRunRequest,
    FullPipelineRunResponse,
    LayoutToHtmlRunRequest,
    LayoutToHtmlRunResponse,
    PipelineAgentLinkResponse,
    PipelineGetResponse,
    PipelineLogEntryResponse,
    QuestionToLayoutRunRequest,
    QuestionToLayoutRunResponse,
    RuntimeInfoResponse,
    SubPipelineGetResponse,
    YamlToQuestionRunRequest,
    YamlToQuestionRunResponse,
)
from app.services.pipeline_service import PipelineService

router = APIRouter(prefix="/v1", tags=["pipeline"])


def _dt(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat()


@router.post("/pipelines/full/run", response_model=FullPipelineRunResponse)
async def run_full_pipeline(req: FullPipelineRunRequest, db: Session = Depends(get_db)) -> FullPipelineRunResponse:
    service = PipelineService(db)
    return await service.run_full_pipeline(req.yaml_instance_id, req.retry_config, stream_key=req.stream_key)


@router.get("/runtime-info", response_model=RuntimeInfoResponse)
def get_runtime_info() -> RuntimeInfoResponse:
    import os

    settings = get_settings()
    agent_cfg = get_agent_settings()
    return RuntimeInfoResponse(
        use_stub_agents=settings.use_stub_agents,
        text_model=agent_cfg.generate_question.primary_model,
        light_model=agent_cfg.extract_rules.primary_model,
        image_model=agent_cfg.generate_image.primary_model,
        has_google_api_key=bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")),
        has_anthropic_api_key=bool(os.getenv("ANTHROPIC_API_KEY")),
    )


@router.post("/pipelines/sub/yaml-to-question/run", response_model=YamlToQuestionRunResponse)
async def run_sub_yaml_to_question(req: YamlToQuestionRunRequest, db: Session = Depends(get_db)) -> YamlToQuestionRunResponse:
    service = PipelineService(db)
    return await service.run_sub_yaml_to_question(req.yaml_instance_id, req.retry_config, stream_key=req.stream_key)


@router.post("/pipelines/sub/question-to-layout/run", response_model=QuestionToLayoutRunResponse)
async def run_sub_question_to_layout(req: QuestionToLayoutRunRequest, db: Session = Depends(get_db)) -> QuestionToLayoutRunResponse:
    service = PipelineService(db)
    return await service.run_sub_question_to_layout(req.question_artifact_id, req.retry_config, stream_key=req.stream_key)


@router.post("/pipelines/sub/layout-to-html/run", response_model=LayoutToHtmlRunResponse)
async def run_sub_layout_to_html(req: LayoutToHtmlRunRequest, db: Session = Depends(get_db)) -> LayoutToHtmlRunResponse:
    service = PipelineService(db)
    return await service.run_sub_layout_to_html(
        req.question_artifact_id,
        req.layout_artifact_id,
        req.retry_config,
        stream_key=req.stream_key,
    )


@router.get("/pipelines/{pipeline_id}", response_model=PipelineGetResponse)
def get_pipeline(pipeline_id: str, db: Session = Depends(get_db)) -> PipelineGetResponse:
    row = repository.get_pipeline(db, pipeline_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Pipeline bulunamadı")
    return PipelineGetResponse(
        id=row.id,
        mode=row.mode,
        yaml_instance_id=row.yaml_instance_id,
        status=row.status,
        retry_config=repository.parse_json(row.retry_config_json),
        error=row.error,
        created_at=_dt(row.created_at) or "",
        finished_at=_dt(row.finished_at),
    )


@router.get("/pipelines/{pipeline_id}/agent-runs", response_model=list[PipelineAgentLinkResponse])
def get_pipeline_runs(pipeline_id: str, db: Session = Depends(get_db)) -> list[PipelineAgentLinkResponse]:
    rows = repository.list_pipeline_links(db, pipeline_id)
    return [
        PipelineAgentLinkResponse(
            id=row.id,
            pipeline_id=row.pipeline_id,
            sub_pipeline_id=row.sub_pipeline_id,
            agent_name=row.agent_name,
            agent_table=row.agent_table,
            agent_run_id=row.agent_run_id,
            created_at=_dt(row.created_at) or "",
        )
        for row in rows
    ]


@router.get("/pipelines/{pipeline_id}/logs", response_model=list[PipelineLogEntryResponse])
def get_pipeline_logs(pipeline_id: str, db: Session = Depends(get_db)) -> list[PipelineLogEntryResponse]:
    rows = repository.list_pipeline_logs(db, pipeline_id)
    return [
        PipelineLogEntryResponse(
            id=row.id,
            pipeline_id=row.pipeline_id,
            sub_pipeline_id=row.sub_pipeline_id,
            mode=row.mode,
            level=row.level,
            component=row.component,
            message=row.message,
            details=repository.parse_json(row.details_json),
            created_at=_dt(row.created_at) or "",
        )
        for row in rows
    ]


@router.get("/sub-pipelines/{sub_pipeline_id}", response_model=SubPipelineGetResponse)
def get_sub_pipeline(sub_pipeline_id: str, db: Session = Depends(get_db)) -> SubPipelineGetResponse:
    row = repository.get_sub_pipeline(db, sub_pipeline_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Sub-pipeline bulunamadı")
    return SubPipelineGetResponse(
        id=row.id,
        pipeline_id=row.pipeline_id,
        mode=row.mode,
        kind=row.kind,
        status=row.status,
        input_json=repository.parse_json(row.input_json),
        output_json=repository.parse_json(row.output_json),
        error=row.error,
        created_at=_dt(row.created_at) or "",
        finished_at=_dt(row.finished_at),
    )


@router.get("/sub-pipelines/{sub_pipeline_id}/agent-runs", response_model=list[PipelineAgentLinkResponse])
def get_sub_pipeline_runs(sub_pipeline_id: str, db: Session = Depends(get_db)) -> list[PipelineAgentLinkResponse]:
    rows = repository.list_sub_pipeline_links(db, sub_pipeline_id)
    return [
        PipelineAgentLinkResponse(
            id=row.id,
            pipeline_id=row.pipeline_id,
            sub_pipeline_id=row.sub_pipeline_id,
            agent_name=row.agent_name,
            agent_table=row.agent_table,
            agent_run_id=row.agent_run_id,
            created_at=_dt(row.created_at) or "",
        )
        for row in rows
    ]


@router.get("/sub-pipelines/{sub_pipeline_id}/logs", response_model=list[PipelineLogEntryResponse])
def get_sub_pipeline_logs(sub_pipeline_id: str, db: Session = Depends(get_db)) -> list[PipelineLogEntryResponse]:
    rows = repository.list_sub_pipeline_logs(db, sub_pipeline_id)
    return [
        PipelineLogEntryResponse(
            id=row.id,
            pipeline_id=row.pipeline_id,
            sub_pipeline_id=row.sub_pipeline_id,
            mode=row.mode,
            level=row.level,
            component=row.component,
            message=row.message,
            details=repository.parse_json(row.details_json),
            created_at=_dt(row.created_at) or "",
        )
        for row in rows
    ]
