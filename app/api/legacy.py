from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db import repository
from app.db.database import get_db
from app.schemas.api import (
    LegacyBatchDetailResponse,
    LegacyBatchRunRequest,
    LegacyBatchRunResponse,
    LegacyOutputNode,
    LegacyPipelineDescriptor,
    LegacyPipelineKind,
    LegacyPipelinesResponse,
    LegacyRunDetail,
    LegacyRunDetailResponse,
    LegacyYamlContentResponse,
    LegacyYamlContentUpdateRequest,
    LegacyYamlFilesResponse,
    LegacyYamlInfoResponse,
    LegacyYamlUploadResponse,
    PipelineLogEntryResponse,
)
from app.services import legacy_pipeline_service as legacy_svc


router = APIRouter(prefix="/v1/legacy", tags=["legacy"])


def _dt(value) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _ensure_kind(kind: LegacyPipelineKind) -> None:
    if kind not in legacy_svc.LEGACY_PIPELINES:
        raise HTTPException(status_code=400, detail="Bilinmeyen pipeline türü")


@router.get("/pipelines", response_model=LegacyPipelinesResponse)
def list_legacy_pipelines() -> LegacyPipelinesResponse:
    items = legacy_svc.list_pipelines()
    return LegacyPipelinesResponse(
        pipelines=[LegacyPipelineDescriptor(**item) for item in items]
    )


@router.get("/pipelines/{kind}/yaml-files", response_model=LegacyYamlFilesResponse)
def list_legacy_yaml_files(kind: LegacyPipelineKind) -> LegacyYamlFilesResponse:
    _ensure_kind(kind)
    files = legacy_svc.list_yaml_files(kind)
    return LegacyYamlFilesResponse(kind=kind, files=files)


@router.get("/pipelines/{kind}/yaml-info", response_model=LegacyYamlInfoResponse)
def get_legacy_yaml_info(
    kind: LegacyPipelineKind,
    yaml_path: str = Query(..., description="YAML kök veya uploads/ prefix'li yol"),
) -> LegacyYamlInfoResponse:
    _ensure_kind(kind)
    try:
        info = legacy_svc.inspect_yaml(kind, yaml_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return LegacyYamlInfoResponse(**info)


@router.get("/pipelines/{kind}/yaml-content", response_model=LegacyYamlContentResponse)
def get_legacy_yaml_content(
    kind: LegacyPipelineKind,
    yaml_path: str = Query(...),
) -> LegacyYamlContentResponse:
    _ensure_kind(kind)
    try:
        payload = legacy_svc.read_yaml_content(kind, yaml_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return LegacyYamlContentResponse(**payload)


@router.put("/pipelines/{kind}/yaml-content", response_model=LegacyYamlContentResponse)
def put_legacy_yaml_content(
    kind: LegacyPipelineKind,
    req: LegacyYamlContentUpdateRequest,
) -> LegacyYamlContentResponse:
    _ensure_kind(kind)
    try:
        payload = legacy_svc.write_yaml_content(kind, req.yaml_path, req.content)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return LegacyYamlContentResponse(**payload)


@router.post("/pipelines/{kind}/yaml-upload", response_model=LegacyYamlUploadResponse)
async def upload_legacy_yaml(
    kind: LegacyPipelineKind,
    file: UploadFile = File(...),
) -> LegacyYamlUploadResponse:
    _ensure_kind(kind)
    content = await file.read()
    try:
        yaml_path = legacy_svc.save_uploaded_yaml(
            kind, filename=file.filename or "uploaded.yaml", content=content
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return LegacyYamlUploadResponse(kind=kind, yaml_path=yaml_path)


@router.post("/pipelines/{kind}/batch-run", response_model=LegacyBatchRunResponse)
async def run_legacy_batch(
    kind: LegacyPipelineKind,
    req: LegacyBatchRunRequest,
    db: Session = Depends(get_db),
) -> LegacyBatchRunResponse:
    _ensure_kind(kind)
    service = legacy_svc.LegacyPipelineService(db)
    items = [item.model_dump() for item in req.items]
    try:
        result = await service.run_batch(
            kind=kind,
            items=items,
            parallelism=req.parallelism,
            stream_key=req.stream_key,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return LegacyBatchRunResponse(**result)


@router.get("/runs/{run_id}", response_model=LegacyRunDetailResponse)
def get_legacy_run(run_id: str, db: Session = Depends(get_db)) -> LegacyRunDetailResponse:
    service = legacy_svc.LegacyPipelineService(db)
    detail = service.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Legacy run bulunamadı")
    detail = dict(detail)
    detail["outputs"] = [LegacyOutputNode(**item) for item in detail.get("outputs", [])]
    return LegacyRunDetailResponse(**detail)


@router.get("/runs/{batch_id}/batch", response_model=LegacyBatchDetailResponse)
def get_legacy_batch(batch_id: str, db: Session = Depends(get_db)) -> LegacyBatchDetailResponse:
    service = legacy_svc.LegacyPipelineService(db)
    detail = service.get_batch_detail(batch_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Legacy batch bulunamadı")
    runs = [
        LegacyRunDetail(
            **{**r, "outputs": [LegacyOutputNode(**n) for n in r.get("outputs", [])]}
        )
        for r in detail["runs"]
    ]
    return LegacyBatchDetailResponse(batch_id=detail["batch_id"], kind=detail["kind"], runs=runs)


@router.get("/runs/{run_id}/download")
def download_legacy_run(
    run_id: str,
    subdir: str | None = Query(None),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    service = legacy_svc.LegacyPipelineService(db)
    detail = service.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Legacy run bulunamadı")
    run_dir = legacy_svc.get_run_dir(detail["kind"], run_id)
    try:
        chunks, suggested = legacy_svc.iter_zip_stream(run_dir, subdir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(suggested)}",
    }
    return StreamingResponse(chunks, media_type="application/zip", headers=headers)


@router.get("/runs/{run_id}/logs", response_model=list[PipelineLogEntryResponse])
def get_legacy_run_logs(run_id: str, db: Session = Depends(get_db)) -> list[PipelineLogEntryResponse]:
    rows = repository.list_pipeline_logs(db, run_id)
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
