from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.agent_service import AgentService
from app.core.config import get_settings
from app.db import repository
from app.db.database import get_db
from app.schemas.api import (
    AgentRunGetResponse,
    StandaloneAgentResponse,
    StandaloneEvaluateRuleRequest,
    StandaloneExtractRulesRequest,
    StandaloneGenerateCompositeImageRequest,
    StandaloneGenerateHtmlRequest,
    StandaloneGenerateLayoutRequest,
    StandaloneGenerateQuestionRequest,
    StandaloneLayoutHtmlValidationRequest,
    StandaloneQuestionLayoutValidationRequest,
)
from app.schemas.domain import AssetSpec
from app.services.pipeline_log_service import write_pipeline_log

router = APIRouter(prefix="/v1", tags=["agent"])


def _dt(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _log_standalone(
    db: Session,
    *,
    component: str,
    message: str,
    level: str = "info",
    details: Any | None = None,
) -> None:
    write_pipeline_log(
        db,
        mode="standalone",
        component=component,
        message=message,
        pipeline_id=None,
        sub_pipeline_id=None,
        level=level,
        details=details,
    )


@router.post("/agents/main/generate-question/run", response_model=StandaloneAgentResponse)
def standalone_generate_question(
    req: StandaloneGenerateQuestionRequest,
    db: Session = Depends(get_db),
) -> StandaloneAgentResponse:
    settings = get_settings()
    agents = AgentService(settings)
    component = "standalone.main_generate_question"
    _log_standalone(db, component=component, message="Run başlatıldı.")
    try:
        result = agents.generate_question(req.yaml_content, req.feedback)
        run_id = repository.record_agent_run(
            db,
            agent_name="main_generate_question",
            mode="standalone",
            attempt_no=1,
            status="success",
            input_payload=req.model_dump(),
            output_payload=result.model_dump(),
            feedback_text=req.feedback,
            error=None,
            model_name=settings.gemini_text_model if not settings.use_stub_agents else "stub",
            pipeline_id=None,
            sub_pipeline_id=None,
        )
        _log_standalone(
            db,
            component=component,
            message=f"Run tamamlandı: success (run_id={run_id})",
            details={"run_id": run_id},
        )
        return StandaloneAgentResponse(run_id=run_id, result=result)
    except Exception as exc:
        _log_standalone(db, component=component, message=f"Run hata ile sonlandı: {exc}", level="error")
        raise


@router.post("/agents/main/generate-layout/run", response_model=StandaloneAgentResponse)
def standalone_generate_layout(req: StandaloneGenerateLayoutRequest, db: Session = Depends(get_db)) -> StandaloneAgentResponse:
    settings = get_settings()
    agents = AgentService(settings)
    component = "standalone.main_generate_layout"
    _log_standalone(db, component=component, message="Run başlatıldı.")
    try:
        result = agents.generate_layout(req.question_json, req.feedback)
        run_id = repository.record_agent_run(
            db,
            agent_name="main_generate_layout",
            mode="standalone",
            attempt_no=1,
            status="success",
            input_payload=req.model_dump(),
            output_payload=result.model_dump(),
            feedback_text=req.feedback,
            error=None,
            model_name=settings.gemini_text_model if not settings.use_stub_agents else "stub",
            pipeline_id=None,
            sub_pipeline_id=None,
        )
        _log_standalone(
            db,
            component=component,
            message=f"Run tamamlandı: success (run_id={run_id})",
            details={"run_id": run_id},
        )
        return StandaloneAgentResponse(run_id=run_id, result=result)
    except Exception as exc:
        _log_standalone(db, component=component, message=f"Run hata ile sonlandı: {exc}", level="error")
        raise


@router.post("/agents/main/generate-html/run", response_model=StandaloneAgentResponse)
def standalone_generate_html(req: StandaloneGenerateHtmlRequest, db: Session = Depends(get_db)) -> StandaloneAgentResponse:
    settings = get_settings()
    agents = AgentService(settings)
    component = "standalone.main_generate_html"
    _log_standalone(db, component=component, message="Run başlatıldı.")
    try:
        result = agents.generate_html(req.question_json, req.layout_plan_json, req.asset_map, req.feedback)
        result.html_content = agents.post_process_html_asset_paths(
            result.html_content,
            req.layout_plan_json,
            req.asset_map,
        )
        run_id = repository.record_agent_run(
            db,
            agent_name="main_generate_html",
            mode="standalone",
            attempt_no=1,
            status="success",
            input_payload=req.model_dump(),
            output_payload=result.model_dump(),
            feedback_text=req.feedback,
            error=None,
            model_name=settings.gemini_text_model if not settings.use_stub_agents else "stub",
            pipeline_id=None,
            sub_pipeline_id=None,
        )
        _log_standalone(
            db,
            component=component,
            message=f"Run tamamlandı: success (run_id={run_id})",
            details={"run_id": run_id},
        )
        return StandaloneAgentResponse(run_id=run_id, result=result)
    except Exception as exc:
        _log_standalone(db, component=component, message=f"Run hata ile sonlandı: {exc}", level="error")
        raise


@router.post("/agents/validation/extract-rules/run", response_model=StandaloneAgentResponse)
def standalone_extract_rules(req: StandaloneExtractRulesRequest, db: Session = Depends(get_db)) -> StandaloneAgentResponse:
    settings = get_settings()
    agents = AgentService(settings)
    component = "standalone.validation_extract_rules"
    _log_standalone(db, component=component, message="Run başlatıldı.")
    try:
        result = agents.extract_rules(req.yaml_content)
        run_id = repository.record_agent_run(
            db,
            agent_name="validation_extract_rules",
            mode="standalone",
            attempt_no=1,
            status="success",
            input_payload=req.model_dump(),
            output_payload=result.model_dump(),
            feedback_text=None,
            error=None,
            model_name=settings.gemini_light_model if not settings.use_stub_agents else "stub",
            pipeline_id=None,
            sub_pipeline_id=None,
        )
        _log_standalone(
            db,
            component=component,
            message=f"Run tamamlandı: success (run_id={run_id})",
            details={"run_id": run_id},
        )
        return StandaloneAgentResponse(run_id=run_id, result=result)
    except Exception as exc:
        _log_standalone(db, component=component, message=f"Run hata ile sonlandı: {exc}", level="error")
        raise


@router.post("/agents/validation/evaluate-rule/run", response_model=StandaloneAgentResponse)
def standalone_evaluate_rule(req: StandaloneEvaluateRuleRequest, db: Session = Depends(get_db)) -> StandaloneAgentResponse:
    settings = get_settings()
    agents = AgentService(settings)
    component = "standalone.validation_evaluate_rule"
    _log_standalone(db, component=component, message="Run başlatıldı.")
    try:
        result = agents.evaluate_rule(req.rule, req.question_json)
        run_status = "success" if result.status != "fail" else "failed"
        run_id = repository.record_agent_run(
            db,
            agent_name="validation_evaluate_rule",
            mode="standalone",
            attempt_no=1,
            status=run_status,
            input_payload=req.model_dump(),
            output_payload=result.model_dump(),
            feedback_text=result.rationale,
            error=None,
            model_name=settings.gemini_light_model if not settings.use_stub_agents else "stub",
            pipeline_id=None,
            sub_pipeline_id=None,
        )
        _log_standalone(
            db,
            component=component,
            message=f"Run tamamlandı: {run_status} (run_id={run_id})",
            level="warning" if run_status == "failed" else "info",
            details={"run_id": run_id},
        )
        return StandaloneAgentResponse(run_id=run_id, result=result)
    except Exception as exc:
        _log_standalone(db, component=component, message=f"Run hata ile sonlandı: {exc}", level="error")
        raise


@router.post("/agents/validation/validate-question-layout/run", response_model=StandaloneAgentResponse)
def standalone_validate_question_layout(
    req: StandaloneQuestionLayoutValidationRequest,
    db: Session = Depends(get_db),
) -> StandaloneAgentResponse:
    settings = get_settings()
    agents = AgentService(settings)
    component = "standalone.validation_question_layout"
    _log_standalone(db, component=component, message="Run başlatıldı.")
    try:
        result = agents.validate_question_layout(req.question_json, req.layout_plan_json)
        run_status = "success" if result.overall_status == "pass" else "failed"
        run_id = repository.record_agent_run(
            db,
            agent_name="validation_question_layout",
            mode="standalone",
            attempt_no=1,
            status=run_status,
            input_payload=req.model_dump(),
            output_payload=result.model_dump(),
            feedback_text=result.feedback,
            error=None,
            model_name=settings.gemini_text_model if not settings.use_stub_agents else "stub",
            pipeline_id=None,
            sub_pipeline_id=None,
        )
        _log_standalone(
            db,
            component=component,
            message=f"Run tamamlandı: {run_status} (run_id={run_id})",
            level="warning" if run_status == "failed" else "info",
            details={"run_id": run_id},
        )
        return StandaloneAgentResponse(run_id=run_id, result=result)
    except Exception as exc:
        _log_standalone(db, component=component, message=f"Run hata ile sonlandı: {exc}", level="error")
        raise


@router.post("/agents/validation/validate-layout-html/run", response_model=StandaloneAgentResponse)
def standalone_validate_layout_html(
    req: StandaloneLayoutHtmlValidationRequest,
    db: Session = Depends(get_db),
) -> StandaloneAgentResponse:
    settings = get_settings()
    agents = AgentService(settings)
    component = "standalone.validation_layout_html"
    _log_standalone(db, component=component, message="Run başlatıldı.")
    try:
        asset_map = dict(req.asset_map)
        if req.layout_plan_json is not None:
            for asset in req.layout_plan_json.asset_library.values():
                if asset.asset_type.value == "catalog_component":
                    asset_map.setdefault(asset.slug, asset.source_filename or asset.output_filename)
                else:
                    asset_map.setdefault(asset.slug, asset.output_filename)

        rendered_image_path = req.rendered_image_path
        if not rendered_image_path:
            rendered_image_path = agents.render_html_to_image(
                req.html_content,
                asset_map=asset_map,
                question_id=req.layout_plan_json.question_id if req.layout_plan_json else None,
            )

        result = agents.validate_html(req.html_content, rendered_image_path)
        run_status = "success" if result.overall_status == "pass" else "failed"
        run_id = repository.record_agent_run(
            db,
            agent_name="validation_layout_html",
            mode="standalone",
            attempt_no=1,
            status=run_status,
            input_payload={
                "html_content": req.html_content,
                "rendered_image_path": rendered_image_path,
                "asset_map": asset_map,
            },
            output_payload=result.model_dump(),
            feedback_text=result.feedback,
            error=None,
            model_name=settings.gemini_text_model if not settings.use_stub_agents else "stub",
            pipeline_id=None,
            sub_pipeline_id=None,
        )
        _log_standalone(
            db,
            component=component,
            message=f"Run tamamlandı: {run_status} (run_id={run_id})",
            level="warning" if run_status == "failed" else "info",
            details={"run_id": run_id},
        )
        return StandaloneAgentResponse(run_id=run_id, result=result)
    except Exception as exc:
        _log_standalone(db, component=component, message=f"Run hata ile sonlandı: {exc}", level="error")
        raise


@router.post("/agents/helper/generate-composite-image/run", response_model=StandaloneAgentResponse)
def standalone_generate_composite_image(
    req: StandaloneGenerateCompositeImageRequest,
    db: Session = Depends(get_db),
) -> StandaloneAgentResponse:
    settings = get_settings()
    agents = AgentService(settings)
    component = "standalone.helper_generate_composite_image"
    _log_standalone(db, component=component, message="Run başlatıldı.")
    try:
        asset = AssetSpec(**req.asset)
        result = agents.generate_composite_image(asset, settings.image_max_retries)
        run_id = repository.record_agent_run(
            db,
            agent_name="helper_generate_composite_image",
            mode="standalone",
            attempt_no=1,
            status="success",
            input_payload=req.model_dump(),
            output_payload=result.model_dump(),
            feedback_text=result.note,
            error=None,
            model_name=settings.gemini_image_model if not settings.use_stub_agents else "stub",
            pipeline_id=None,
            sub_pipeline_id=None,
        )
        _log_standalone(
            db,
            component=component,
            message=f"Run tamamlandı: success (run_id={run_id})",
            details={"run_id": run_id},
        )
        return StandaloneAgentResponse(run_id=run_id, result=result)
    except Exception as exc:
        _log_standalone(db, component=component, message=f"Run hata ile sonlandı: {exc}", level="error")
        raise


@router.get("/agent-runs/{agent_name}/{run_id}", response_model=AgentRunGetResponse)
def get_agent_run(agent_name: str, run_id: str, db: Session = Depends(get_db)) -> AgentRunGetResponse:
    row = repository.get_agent_run(db, agent_name, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Agent run bulunamadı")

    return AgentRunGetResponse(
        id=row.id,
        mode=row.mode,
        pipeline_id=row.pipeline_id,
        sub_pipeline_id=row.sub_pipeline_id,
        attempt_no=row.attempt_no,
        status=row.status,
        input_json=repository.parse_json(row.input_json),
        output_json=repository.parse_json(row.output_json),
        feedback_text=row.feedback_text,
        error=row.error,
        model_name=row.model_name,
        question_id=row.question_id,
        schema_version=row.schema_version,
        started_at=_dt(row.started_at) or "",
        finished_at=_dt(row.finished_at),
    )
