from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.api import (
    ExplorerFavoriteRequest,
    ExplorerFavoriteResponse,
    ExplorerFileReadResponse,
    ExplorerRoot,
    ExplorerTreeResponse,
)
from app.services.explorer_service import ExplorerService

router = APIRouter(prefix="/v1/explorer", tags=["explorer"])


@router.get("/tree", response_model=ExplorerTreeResponse)
def explorer_tree(
    root: ExplorerRoot = Query(...),
    path: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> ExplorerTreeResponse:
    service = ExplorerService(db)
    try:
        items = service.list_tree(root, path=path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dizin bulunamadı")
    return ExplorerTreeResponse(root=root, path=path, items=items)


@router.get("/file", response_model=ExplorerFileReadResponse)
def explorer_read_file(
    root: ExplorerRoot = Query(...),
    path: str = Query(...),
    db: Session = Depends(get_db),
) -> ExplorerFileReadResponse:
    service = ExplorerService(db)
    try:
        return service.read_file(root, path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dosya bulunamadı")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Dosya okunamadı")


@router.delete("/file", status_code=204, response_class=Response)
def explorer_delete_file(
    root: ExplorerRoot = Query(...),
    path: str = Query(...),
    db: Session = Depends(get_db),
) -> Response:
    service = ExplorerService(db)
    try:
        service.delete_file(root, path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dosya bulunamadı")
    return Response(status_code=204)


@router.patch("/file/favorite", response_model=ExplorerFavoriteResponse)
def explorer_set_favorite(
    req: ExplorerFavoriteRequest,
    db: Session = Depends(get_db),
) -> ExplorerFavoriteResponse:
    service = ExplorerService(db)
    try:
        service.set_favorite(req.root, req.path, req.is_favorite)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dosya bulunamadı")
    return ExplorerFavoriteResponse(root=req.root, path=req.path, is_favorite=req.is_favorite)
