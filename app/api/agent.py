from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.agent_service import AgentService
from app.agents.config import get_agent_settings
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
from app.services.log_stream_service import publish_done
from app.services.pipeline_log_service import write_pipeline_log
from app.services.run_dir_service import create_standalone_run_dir, write_manifest

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
    log_path: Path | None = None,
    stream_key: str | None = None,
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
        log_path=log_path,
        stream_key=stream_key,
    )


@router.post("/agents/main/generate-question/run", response_model=StandaloneAgentResponse)
def standalone_generate_question(
    req: StandaloneGenerateQuestionRequest,
    db: Session = Depends(get_db),
) -> StandaloneAgentResponse:
    settings = get_settings()
    agents = AgentService(settings)
    component = "standalone.main_generate_question"
    stream_key = req.stream_key
    _log_standalone(db, component=component, message="Run başlatıldı.", stream_key=stream_key)
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
            model_name=get_agent_settings().generate_question.primary_model if not settings.use_stub_agents else "stub",
            pipeline_id=None,
            sub_pipeline_id=None,
        )
        _log_standalone(
            db,
            component=component,
            message=f"Run tamamlandı: success (run_id={run_id})",
            details={"run_id": run_id},
            stream_key=stream_key,
        )
        return StandaloneAgentResponse(run_id=run_id, result=result)
    except Exception as exc:
        _log_standalone(db, component=component, message=f"Run hata ile sonlandı: {exc}", level="error", stream_key=stream_key)
        raise
    finally:
        publish_done(stream_key or "")


@router.post("/agents/main/generate-layout/run", response_model=StandaloneAgentResponse)
def standalone_generate_layout(req: StandaloneGenerateLayoutRequest, db: Session = Depends(get_db)) -> StandaloneAgentResponse:
    settings = get_settings()
    agents = AgentService(settings)
    component = "standalone.main_generate_layout"
    stream_key = req.stream_key
    _log_standalone(db, component=component, message="Run başlatıldı.", stream_key=stream_key)
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
            model_name=get_agent_settings().generate_layout.primary_model if not settings.use_stub_agents else "stub",
            pipeline_id=None,
            sub_pipeline_id=None,
        )
        _log_standalone(
            db,
            component=component,
            message=f"Run tamamlandı: success (run_id={run_id})",
            details={"run_id": run_id},
            stream_key=stream_key,
        )
        return StandaloneAgentResponse(run_id=run_id, result=result)
    except Exception as exc:
        _log_standalone(db, component=component, message=f"Run hata ile sonlandı: {exc}", level="error", stream_key=stream_key)
        raise
    finally:
        publish_done(stream_key or "")


@router.post("/agents/main/generate-html/run", response_model=StandaloneAgentResponse)
def standalone_generate_html(req: StandaloneGenerateHtmlRequest, db: Session = Depends(get_db)) -> StandaloneAgentResponse:
    settings = get_settings()
    agents = AgentService(settings)
    component = "standalone.main_generate_html"
    stream_key = req.stream_key
    _log_standalone(db, component=component, message="Run başlatıldı.", stream_key=stream_key)
    try:
        result = agents.generate_html(req.question_json, req.layout_plan_json, req.asset_map, req.feedback)
        result.html_content = agents.post_process_html_asset_paths(
            result.html_content,
            req.layout_plan_json,
            req.asset_map,
        )
        safe_input_payload = req.model_dump()
        safe_input_payload["question_json"] = agents.question_payload_for_generate_html(req.question_json)
        run_id = repository.record_agent_run(
            db,
            agent_name="main_generate_html",
            mode="standalone",
            attempt_no=1,
            status="success",
            input_payload=safe_input_payload,
            output_payload=result.model_dump(),
            feedback_text=req.feedback,
            error=None,
            model_name=get_agent_settings().generate_html.primary_model if not settings.use_stub_agents else "stub",
            pipeline_id=None,
            sub_pipeline_id=None,
        )
        _log_standalone(
            db,
            component=component,
            message=f"Run tamamlandı: success (run_id={run_id})",
            details={"run_id": run_id},
            stream_key=stream_key,
        )
        return StandaloneAgentResponse(run_id=run_id, result=result)
    except Exception as exc:
        _log_standalone(db, component=component, message=f"Run hata ile sonlandı: {exc}", level="error", stream_key=stream_key)
        raise
    finally:
        publish_done(stream_key or "")


@router.post("/agents/validation/extract-rules/run", response_model=StandaloneAgentResponse)
def standalone_extract_rules(req: StandaloneExtractRulesRequest, db: Session = Depends(get_db)) -> StandaloneAgentResponse:
    settings = get_settings()
    agents = AgentService(settings)
    component = "standalone.validation_extract_rules"
    stream_key = req.stream_key
    _log_standalone(db, component=component, message="Run başlatıldı.", stream_key=stream_key)
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
            model_name=get_agent_settings().extract_rules.primary_model if not settings.use_stub_agents else "stub",
            pipeline_id=None,
            sub_pipeline_id=None,
        )
        _log_standalone(
            db,
            component=component,
            message=f"Run tamamlandı: success (run_id={run_id})",
            details={"run_id": run_id},
            stream_key=stream_key,
        )
        return StandaloneAgentResponse(run_id=run_id, result=result)
    except Exception as exc:
        _log_standalone(db, component=component, message=f"Run hata ile sonlandı: {exc}", level="error", stream_key=stream_key)
        raise
    finally:
        publish_done(stream_key or "")


@router.post("/agents/validation/evaluate-rule/run", response_model=StandaloneAgentResponse)
def standalone_evaluate_rule(req: StandaloneEvaluateRuleRequest, db: Session = Depends(get_db)) -> StandaloneAgentResponse:
    settings = get_settings()
    agents = AgentService(settings)
    component = "standalone.validation_evaluate_rule"
    stream_key = req.stream_key
    _log_standalone(db, component=component, message="Run başlatıldı.", stream_key=stream_key)
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
            model_name=get_agent_settings().evaluate_rule.primary_model if not settings.use_stub_agents else "stub",
            pipeline_id=None,
            sub_pipeline_id=None,
        )
        _log_standalone(
            db,
            component=component,
            message=f"Run tamamlandı: {run_status} (run_id={run_id})",
            level="warning" if run_status == "failed" else "info",
            details={"run_id": run_id},
            stream_key=stream_key,
        )
        return StandaloneAgentResponse(run_id=run_id, result=result)
    except Exception as exc:
        _log_standalone(db, component=component, message=f"Run hata ile sonlandı: {exc}", level="error", stream_key=stream_key)
        raise
    finally:
        publish_done(stream_key or "")


@router.post("/agents/validation/validate-question-layout/run", response_model=StandaloneAgentResponse)
def standalone_validate_question_layout(
    req: StandaloneQuestionLayoutValidationRequest,
    db: Session = Depends(get_db),
) -> StandaloneAgentResponse:
    settings = get_settings()
    agents = AgentService(settings)
    component = "standalone.validation_question_layout"
    stream_key = req.stream_key
    _log_standalone(db, component=component, message="Run başlatıldı.", stream_key=stream_key)
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
            model_name=get_agent_settings().validate_question_layout.primary_model if not settings.use_stub_agents else "stub",
            pipeline_id=None,
            sub_pipeline_id=None,
        )
        _log_standalone(
            db,
            component=component,
            message=f"Run tamamlandı: {run_status} (run_id={run_id})",
            level="warning" if run_status == "failed" else "info",
            details={"run_id": run_id},
            stream_key=stream_key,
        )
        return StandaloneAgentResponse(run_id=run_id, result=result)
    except Exception as exc:
        _log_standalone(db, component=component, message=f"Run hata ile sonlandı: {exc}", level="error", stream_key=stream_key)
        raise
    finally:
        publish_done(stream_key or "")


@router.post("/agents/validation/validate-layout-html/run", response_model=StandaloneAgentResponse)
def standalone_validate_layout_html(
    req: StandaloneLayoutHtmlValidationRequest,
    db: Session = Depends(get_db),
) -> StandaloneAgentResponse:
    settings = get_settings()
    agents = AgentService(settings)
    component = "standalone.validation_layout_html"
    stream_key = req.stream_key
    _log_standalone(db, component=component, message="Run başlatıldı.", stream_key=stream_key)
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
            model_name=get_agent_settings().validate_html.primary_model if not settings.use_stub_agents else "stub",
            pipeline_id=None,
            sub_pipeline_id=None,
        )
        _log_standalone(
            db,
            component=component,
            message=f"Run tamamlandı: {run_status} (run_id={run_id})",
            level="warning" if run_status == "failed" else "info",
            details={"run_id": run_id},
            stream_key=stream_key,
        )
        return StandaloneAgentResponse(run_id=run_id, result=result)
    except Exception as exc:
        _log_standalone(db, component=component, message=f"Run hata ile sonlandı: {exc}", level="error", stream_key=stream_key)
        raise
    finally:
        publish_done(stream_key or "")


@router.post("/agents/helper/generate-composite-image/run", response_model=StandaloneAgentResponse)
def standalone_generate_composite_image(
    req: StandaloneGenerateCompositeImageRequest,
    db: Session = Depends(get_db),
) -> StandaloneAgentResponse:
    settings = get_settings()
    agents = AgentService(settings)
    component = "standalone.helper_generate_composite_image"
    log_path: Path | None = None
    stream_key = req.stream_key
    try:
        asset = AssetSpec(**req.asset)
        run_dir = create_standalone_run_dir(settings.runs_dir, agent_name="generate_composite_image")
        log_path = run_dir / "log.txt"
        _log_standalone(db, component=component, message="Run başlatıldı.", log_path=log_path, stream_key=stream_key)
        write_manifest(
            run_dir,
            run_type="standalone",
            yaml_filename=None,
            agent_name="generate_composite_image",
            pipeline_id=None,
            sub_pipeline_id=None,
            sub_kind=None,
        )
        img_output_path = run_dir / f"{asset.slug}.png"
        result = agents.generate_composite_image(
            asset, settings.image_max_retries, output_path=img_output_path
        )
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
            model_name=get_agent_settings().generate_image.primary_model if not settings.use_stub_agents else "stub",
            pipeline_id=None,
            sub_pipeline_id=None,
        )
        result_dict: Any = result.model_dump()
        result_dict["run_path"] = str(run_dir.relative_to(settings.root_dir))
        _log_standalone(
            db,
            component=component,
            message=f"Run tamamlandı: success (run_id={run_id})",
            details={"run_id": run_id},
            log_path=log_path,
            stream_key=stream_key,
        )
        return StandaloneAgentResponse(run_id=run_id, result=result_dict)
    except Exception as exc:
        _log_standalone(db, component=component, message=f"Run hata ile sonlandı: {exc}", level="error", log_path=log_path, stream_key=stream_key)
        raise
    finally:
        publish_done(stream_key or "")


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
