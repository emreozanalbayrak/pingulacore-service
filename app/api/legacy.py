from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db import repository
from app.db.database import get_db
from app.schemas.api import (
    LegacyOutputItem,
    LegacyPipelineDescriptor,
    LegacyPipelineKind,
    LegacyPipelinesResponse,
    LegacyRunDetailResponse,
    LegacyRunRequest,
    LegacyRunResponse,
    LegacyYamlFilesResponse,
    LegacyYamlUploadResponse,
    PipelineLogEntryResponse,
)
from app.services import legacy_pipeline_service as legacy_svc


router = APIRouter(prefix="/v1/legacy", tags=["legacy"])


def _dt(value) -> str | None:
    if value is None:
        return None
    return value.isoformat()


@router.get("/pipelines", response_model=LegacyPipelinesResponse)
def list_legacy_pipelines() -> LegacyPipelinesResponse:
    items = legacy_svc.list_pipelines()
    return LegacyPipelinesResponse(
        pipelines=[LegacyPipelineDescriptor(**item) for item in items]
    )


@router.get("/pipelines/{kind}/yaml-files", response_model=LegacyYamlFilesResponse)
def list_legacy_yaml_files(kind: LegacyPipelineKind) -> LegacyYamlFilesResponse:
    if kind not in legacy_svc.LEGACY_PIPELINES:
        raise HTTPException(status_code=400, detail="Bilinmeyen pipeline türü")
    files = legacy_svc.list_yaml_files(kind)
    return LegacyYamlFilesResponse(kind=kind, files=files)


@router.post("/pipelines/{kind}/yaml-upload", response_model=LegacyYamlUploadResponse)
async def upload_legacy_yaml(
    kind: LegacyPipelineKind,
    file: UploadFile = File(...),
) -> LegacyYamlUploadResponse:
    if kind not in legacy_svc.LEGACY_PIPELINES:
        raise HTTPException(status_code=400, detail="Bilinmeyen pipeline türü")
    content = await file.read()
    try:
        yaml_path = legacy_svc.save_uploaded_yaml(
            kind, filename=file.filename or "uploaded.yaml", content=content
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return LegacyYamlUploadResponse(kind=kind, yaml_path=yaml_path)


@router.post("/pipelines/{kind}/run", response_model=LegacyRunResponse)
async def run_legacy_pipeline(
    kind: LegacyPipelineKind,
    req: LegacyRunRequest,
    db: Session = Depends(get_db),
) -> LegacyRunResponse:
    if kind not in legacy_svc.LEGACY_PIPELINES:
        raise HTTPException(status_code=400, detail="Bilinmeyen pipeline türü")
    service = legacy_svc.LegacyPipelineService(db)
    try:
        result = await service.run(
            kind=kind,
            yaml_path=req.yaml_path,
            params=req.params,
            stream_key=req.stream_key,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return LegacyRunResponse(**result)


@router.get("/runs/{run_id}", response_model=LegacyRunDetailResponse)
def get_legacy_run(run_id: str, db: Session = Depends(get_db)) -> LegacyRunDetailResponse:
    service = legacy_svc.LegacyPipelineService(db)
    detail = service.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Legacy run bulunamadı")
    detail = dict(detail)
    detail["outputs"] = [LegacyOutputItem(**item) for item in detail.get("outputs", [])]
    return LegacyRunDetailResponse(**detail)


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
