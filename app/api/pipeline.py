from __future__ import annotations

from typing import Any
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.agents.config import get_agent_settings
from app.api.deps import get_current_user
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
    FavoriteCreateRequest,
    FavoriteResponse,
    SpFileFavoriteRequest,
    SpFileItemResponse,
    SpFilesResponse,
    SpHtmlFileResponse,
    SpJsonFileResponse,
    SubPipelineGetResponse,
    YamlFileContentResponse,
    YamlFilesResponse,
    YamlToQuestionRunRequest,
    YamlToQuestionRunResponse,
)
from app.services.pipeline_service import PipelineService
from app.services import sub_pipeline_files_service as sp_files
from app.services.yaml_service import load_yaml_file

router = APIRouter(prefix="/v1", tags=["pipeline"], dependencies=[Depends(get_current_user)])


def _dt(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _favorite_response(row: Any) -> FavoriteResponse:
    data = repository.parse_json(getattr(row, "content_json", None))
    if not isinstance(data, dict):
        data = {}
    return FavoriteResponse(
        id=row.id,
        name=row.name,
        kind=row.kind,
        data=data,
        source_sub_pipeline_id=row.source_sub_pipeline_id,
        created_at=_dt(row.created_at) or "",
    )


def _sp_file_item_response(row: Any) -> SpFileItemResponse:
    return SpFileItemResponse(
        filename=row.filename,
        is_favorite=bool(getattr(row, "is_favorite", False)),
    )


def _sync_stored_json_outputs(db: Session, kind: str) -> None:
    for filename in sp_files.list_files(kind):  # type: ignore[arg-type]
        row = repository.get_stored_json_output(db, kind=kind, filename=filename)
        if row is None:
            try:
                data = sp_files.read_json_file(kind, filename)  # type: ignore[arg-type]
            except Exception:
                continue
            try:
                row = repository.upsert_stored_json_output(
                    db,
                    kind=kind,
                    filename=filename,
                    content=data,
                    source_sub_pipeline_id=None,
                )
            except Exception:
                continue

        if row is not None and not bool(getattr(row, "is_favorite", False)):
            try:
                fs_favorite = sp_files.get_stored_json_favorite(kind, filename)  # type: ignore[arg-type]
            except Exception:
                fs_favorite = False
            if fs_favorite:
                try:
                    repository.set_stored_json_output_favorite(
                        db,
                        kind=kind,
                        filename=filename,
                        is_favorite=True,
                    )
                except Exception:
                    continue


def _ensure_stored_json_output(db: Session, *, kind: str, filename: str) -> Any:
    row = repository.get_stored_json_output(db, kind=kind, filename=filename)
    if row is None:
        try:
            data = sp_files.read_json_file(kind, filename)  # type: ignore[arg-type]
        except ValueError:
            raise HTTPException(status_code=400, detail="Geçersiz dosya adı")
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Dosya bulunamadı")

        try:
            row = repository.upsert_stored_json_output(
                db,
                kind=kind,
                filename=filename,
                content=data,
                source_sub_pipeline_id=None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    if row is not None and not bool(getattr(row, "is_favorite", False)):
        try:
            fs_favorite = sp_files.get_stored_json_favorite(kind, filename)  # type: ignore[arg-type]
        except Exception:
            fs_favorite = False
        if fs_favorite:
            updated = repository.set_stored_json_output_favorite(
                db,
                kind=kind,
                filename=filename,
                is_favorite=True,
            )
            if updated is not None:
                row = updated
    return row


@router.post("/pipelines/full/run", response_model=FullPipelineRunResponse)
async def run_full_pipeline(req: FullPipelineRunRequest, db: Session = Depends(get_db)) -> FullPipelineRunResponse:
    service = PipelineService(db)
    return await service.run_full_pipeline(req.yaml_filename, req.retry_config, stream_key=req.stream_key)


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


@router.get("/yaml-files", response_model=YamlFilesResponse)
def list_yaml_files() -> YamlFilesResponse:
    settings = get_settings()
    names: set[str] = set()

    for directory in [settings.yaml_primary_dir, settings.yaml_fallback_dir]:
        if not directory.exists() or not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.is_file() and path.suffix.lower() in {".yaml", ".yml"}:
                names.add(path.name)

    return YamlFilesResponse(files=sorted(names))


@router.get("/yaml-files/{filename}", response_model=YamlFileContentResponse)
def get_yaml_file_content(filename: str) -> YamlFileContentResponse:
    token = Path(filename)
    if token.name != filename or token.is_absolute() or ".." in token.parts:
        raise HTTPException(status_code=400, detail="Geçersiz dosya adı")
    try:
        data = load_yaml_file(filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="YAML bulunamadı")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return YamlFileContentResponse(filename=filename, data=data)


@router.get("/sp-files/q_json", response_model=SpFilesResponse)
def list_sp_question_files(
    favorites_only: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> SpFilesResponse:
    _sync_stored_json_outputs(db, "q_json")
    rows = repository.list_stored_json_outputs(db, kind="q_json", favorites_only=favorites_only)
    items = [_sp_file_item_response(row) for row in rows]
    return SpFilesResponse(files=[item.filename for item in items], items=items)


@router.get("/sp-files/layout", response_model=SpFilesResponse)
def list_sp_layout_files(
    favorites_only: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> SpFilesResponse:
    _sync_stored_json_outputs(db, "layout")
    rows = repository.list_stored_json_outputs(db, kind="layout", favorites_only=favorites_only)
    items = [_sp_file_item_response(row) for row in rows]
    return SpFilesResponse(files=[item.filename for item in items], items=items)


@router.get("/sp-files/q_html", response_model=SpFilesResponse)
def list_sp_html_files() -> SpFilesResponse:
    files = sp_files.list_files("q_html")
    return SpFilesResponse(
        files=files,
        items=[SpFileItemResponse(filename=filename, is_favorite=False) for filename in files],
    )


@router.get("/sp-files/q_json/{filename}", response_model=SpJsonFileResponse)
def get_sp_question_file(filename: str) -> SpJsonFileResponse:
    try:
        data = sp_files.read_json_file("q_json", filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="Geçersiz dosya adı")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dosya bulunamadı")
    return SpJsonFileResponse(filename=filename, data=data)


@router.get("/sp-files/layout/{filename}", response_model=SpJsonFileResponse)
def get_sp_layout_file(filename: str) -> SpJsonFileResponse:
    try:
        data = sp_files.read_json_file("layout", filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="Geçersiz dosya adı")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dosya bulunamadı")
    return SpJsonFileResponse(filename=filename, data=data)


@router.patch("/sp-files/q_json/{filename}/favorite", response_model=SpFileItemResponse)
def set_sp_question_file_favorite(
    filename: str,
    req: SpFileFavoriteRequest,
    db: Session = Depends(get_db),
) -> SpFileItemResponse:
    _ensure_stored_json_output(db, kind="q_json", filename=filename)
    row = repository.set_stored_json_output_favorite(
        db,
        kind="q_json",
        filename=filename,
        is_favorite=req.is_favorite,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Dosya bulunamadı")
    sp_files.set_stored_json_favorite("q_json", filename, req.is_favorite)
    return _sp_file_item_response(row)


@router.patch("/sp-files/layout/{filename}/favorite", response_model=SpFileItemResponse)
def set_sp_layout_file_favorite(
    filename: str,
    req: SpFileFavoriteRequest,
    db: Session = Depends(get_db),
) -> SpFileItemResponse:
    _ensure_stored_json_output(db, kind="layout", filename=filename)
    row = repository.set_stored_json_output_favorite(
        db,
        kind="layout",
        filename=filename,
        is_favorite=req.is_favorite,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Dosya bulunamadı")
    sp_files.set_stored_json_favorite("layout", filename, req.is_favorite)
    return _sp_file_item_response(row)


@router.get("/sp-files/q_html/{filename}", response_model=SpHtmlFileResponse)
def get_sp_html_file(filename: str) -> SpHtmlFileResponse:
    try:
        html_content = sp_files.read_html_file(filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="Geçersiz dosya adı")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dosya bulunamadı")
    return SpHtmlFileResponse(filename=filename, html_content=html_content)


@router.post("/favorites", response_model=FavoriteResponse, status_code=201)
def create_favorite(req: FavoriteCreateRequest, db: Session = Depends(get_db)) -> FavoriteResponse:
    try:
        row = repository.create_favorite_output(
            db,
            name=req.name,
            kind=req.kind,
            content=req.data,
            source_sub_pipeline_id=req.source_sub_pipeline_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _favorite_response(row)


@router.get("/favorites", response_model=list[FavoriteResponse])
def list_favorites(
    kind: str | None = Query(default=None, description="question|layout"),
    db: Session = Depends(get_db),
) -> list[FavoriteResponse]:
    try:
        rows = repository.list_favorite_outputs(db, kind=kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return [_favorite_response(row) for row in rows]


@router.get("/favorites/{favorite_id}", response_model=FavoriteResponse)
def get_favorite(favorite_id: int, db: Session = Depends(get_db)) -> FavoriteResponse:
    row = repository.get_favorite_output(db, favorite_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Favori bulunamadı")
    return _favorite_response(row)


@router.delete("/favorites/{favorite_id}", status_code=204, response_class=Response)
def delete_favorite(favorite_id: int, db: Session = Depends(get_db)) -> Response:
    ok = repository.delete_favorite_output(db, favorite_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Favori bulunamadı")
    return Response(status_code=204)


@router.get("/assets/{filename:path}")
def get_generated_asset(filename: str) -> FileResponse:
    settings = get_settings()
    token = Path(filename)

    # Reject path traversal regardless of serving mode
    if token.is_absolute() or ".." in token.parts:
        raise HTTPException(status_code=400, detail="Geçersiz asset yolu")

    # New structured runs path: runs/{kind}/{name}/...
    if token.parts and token.parts[0] == "runs":
        runs_dir_resolved = settings.runs_dir.resolve()
        # Reconstruct path relative to root_dir (runs_dir's parent)
        candidate = (settings.runs_dir.parent / token).resolve()
        if runs_dir_resolved not in candidate.parents:
            raise HTTPException(status_code=400, detail="Geçersiz asset yolu")
        if candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        raise HTTPException(status_code=404, detail="Asset bulunamadı")

    # Legacy flat filename: must be a bare name with no directory separators
    if token.name != filename:
        raise HTTPException(status_code=400, detail="Geçersiz asset yolu")

    roots = [settings.output_dir.resolve(), settings.catalog_dir.resolve()]
    for root in roots:
        candidate = (root / token.name).resolve()
        if root not in candidate.parents:
            continue
        if candidate.exists() and candidate.is_file():
            return FileResponse(candidate)

    raise HTTPException(status_code=404, detail="Asset bulunamadı")


@router.post("/pipelines/sub/yaml-to-question/run", response_model=YamlToQuestionRunResponse)
async def run_sub_yaml_to_question(req: YamlToQuestionRunRequest, db: Session = Depends(get_db)) -> YamlToQuestionRunResponse:
    service = PipelineService(db)
    return await service.run_sub_yaml_to_question(req.yaml_filename, req.retry_config, stream_key=req.stream_key)


@router.post("/pipelines/sub/question-to-layout/run", response_model=QuestionToLayoutRunResponse)
async def run_sub_question_to_layout(req: QuestionToLayoutRunRequest, db: Session = Depends(get_db)) -> QuestionToLayoutRunResponse:
    service = PipelineService(db)
    return await service.run_sub_question_to_layout(req.question_json, req.retry_config, stream_key=req.stream_key)


@router.post("/pipelines/sub/layout-to-html/run", response_model=LayoutToHtmlRunResponse)
async def run_sub_layout_to_html(req: LayoutToHtmlRunRequest, db: Session = Depends(get_db)) -> LayoutToHtmlRunResponse:
    service = PipelineService(db)
    return await service.run_sub_layout_to_html(req.question_json, req.layout_plan_json, req.retry_config, stream_key=req.stream_key)


@router.get("/pipelines/{pipeline_id}", response_model=PipelineGetResponse)
def get_pipeline(pipeline_id: str, db: Session = Depends(get_db)) -> PipelineGetResponse:
    row = repository.get_pipeline(db, pipeline_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Pipeline bulunamadı")
    return PipelineGetResponse(
        id=row.id,
        mode=row.mode,
        yaml_filename=row.yaml_filename,
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
