from __future__ import annotations

import base64
import json
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db import repository
from app.schemas.api import ExplorerFileReadResponse, ExplorerRoot, ExplorerTreeNode
from app.services import sub_pipeline_files_service as sp_files


class ExplorerService:
    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()

    def _root_path(self, root: ExplorerRoot) -> Path:
        if root == "runs":
            return self.settings.runs_dir.resolve()
        return (self.settings.root_dir / "sp_files").resolve()

    def _normalize_relative(self, path: str | None, *, allow_empty: bool = True) -> str:
        if path is None:
            return ""
        raw = path.strip().replace("\\", "/")
        if raw in {"", "."} and allow_empty:
            return ""
        token = Path(raw)
        if token.is_absolute() or ".." in token.parts:
            raise ValueError("Geçersiz dosya yolu")
        parts = [part for part in token.parts if part not in {"", "."}]
        normalized = "/".join(parts)
        if not normalized and not allow_empty:
            raise ValueError("Geçersiz dosya yolu")
        return normalized

    def _resolve(self, root: ExplorerRoot, path: str | None, *, allow_empty: bool = True) -> tuple[Path, Path, str]:
        root_path = self._root_path(root)
        rel_path = self._normalize_relative(path, allow_empty=allow_empty)
        target = (root_path / rel_path).resolve() if rel_path else root_path
        if target != root_path and root_path not in target.parents:
            raise ValueError("Geçersiz dosya yolu")
        return root_path, target, rel_path

    @staticmethod
    def _asset_url_for_runs(relative_path: str) -> str:
        encoded = "/".join(quote(part, safe="") for part in relative_path.split("/") if part)
        return f"/v1/assets/runs/{encoded}"

    @staticmethod
    def _modified_iso(path: Path) -> str | None:
        try:
            stat = path.stat()
        except Exception:
            return None
        return datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

    @staticmethod
    def _infer_stored_kind_and_filename(root: ExplorerRoot, relative_path: str) -> tuple[str, str] | None:
        if root != "sp_files":
            return None
        token = Path(relative_path)
        if len(token.parts) != 2:
            return None
        kind, filename = token.parts[0], token.parts[1]
        if kind not in {"q_json", "layout"}:
            return None
        if not (filename.endswith(".question.json") or filename.endswith(".layout.json")):
            return None
        return kind, filename

    def is_favoritable(self, root: ExplorerRoot, relative_path: str) -> bool:
        token = Path(relative_path)
        name = token.name.lower()
        if name.startswith("render") and name.endswith(".png"):
            return True
        return self._infer_stored_kind_and_filename(root, relative_path) is not None

    def _is_favorite(self, root: ExplorerRoot, relative_path: str, favoritable: bool) -> bool:
        if not favoritable:
            return False

        inferred = self._infer_stored_kind_and_filename(root, relative_path)
        if inferred is not None:
            kind, filename = inferred
            row = repository.get_stored_json_output(self.db, kind=kind, filename=filename)
            if row is not None:
                return bool(getattr(row, "is_favorite", False))
            try:
                return sp_files.get_stored_json_favorite(kind, filename)  # type: ignore[arg-type]
            except Exception:
                return False

        try:
            return sp_files.get_path_favorite(root, relative_path)
        except Exception:
            return False

    def _build_tree(self, root: ExplorerRoot, root_path: Path, base_dir: Path) -> list[ExplorerTreeNode]:
        rows: list[ExplorerTreeNode] = []
        children = sorted(
            [item for item in base_dir.iterdir() if item.name not in {".DS_Store"}],
            key=lambda item: (not item.is_dir(), item.name.lower()),
        )
        for child in children:
            rel = child.relative_to(root_path).as_posix()
            if child.is_dir():
                rows.append(
                    ExplorerTreeNode(
                        name=child.name,
                        path=rel,
                        kind="dir",
                        modified_at=self._modified_iso(child),
                        children=self._build_tree(root, root_path, child),
                    )
                )
                continue

            favoritable = self.is_favoritable(root, rel)
            rows.append(
                ExplorerTreeNode(
                    name=child.name,
                    path=rel,
                    kind="file",
                    size=child.stat().st_size if child.exists() else None,
                    modified_at=self._modified_iso(child),
                    is_favorite=self._is_favorite(root, rel, favoritable),
                    favoritable=favoritable,
                )
            )
        return rows

    def list_tree(self, root: ExplorerRoot, path: str | None = None) -> list[ExplorerTreeNode]:
        root_path, target, _ = self._resolve(root, path, allow_empty=True)
        if not target.exists():
            raise FileNotFoundError("Dizin bulunamadı")
        if not target.is_dir():
            raise ValueError("Dizin bekleniyor")
        return self._build_tree(root, root_path, target)

    def read_file(self, root: ExplorerRoot, path: str) -> ExplorerFileReadResponse:
        _, target, rel = self._resolve(root, path, allow_empty=False)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError("Dosya bulunamadı")

        suffix = target.suffix.lower()
        mime = mimetypes.guess_type(target.name)[0]

        if suffix == ".json":
            content = json.loads(target.read_text(encoding="utf-8"))
            return ExplorerFileReadResponse(
                root=root,
                path=rel,
                filename=target.name,
                content_type="json",
                content=content,
                mime_type="application/json",
            )

        if suffix in {".html", ".htm"}:
            return ExplorerFileReadResponse(
                root=root,
                path=rel,
                filename=target.name,
                content_type="html",
                content=target.read_text(encoding="utf-8"),
                mime_type=mime or "text/html",
            )

        if suffix in {".txt", ".md", ".log", ".yml", ".yaml", ".csv", ".tsv", ".py", ".js", ".ts", ".tsx", ".css"}:
            return ExplorerFileReadResponse(
                root=root,
                path=rel,
                filename=target.name,
                content_type="text",
                content=target.read_text(encoding="utf-8"),
                mime_type=mime or "text/plain",
            )

        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
            if root == "runs" and suffix == ".png":
                return ExplorerFileReadResponse(
                    root=root,
                    path=rel,
                    filename=target.name,
                    content_type="image",
                    asset_url=self._asset_url_for_runs(rel),
                    mime_type=mime or "image/png",
                )
            raw = target.read_bytes()
            return ExplorerFileReadResponse(
                root=root,
                path=rel,
                filename=target.name,
                content_type="image",
                content=base64.b64encode(raw).decode("ascii"),
                mime_type=mime or "application/octet-stream",
            )

        raw = target.read_bytes()
        return ExplorerFileReadResponse(
            root=root,
            path=rel,
            filename=target.name,
            content_type="binary",
            content=base64.b64encode(raw).decode("ascii"),
            mime_type=mime or "application/octet-stream",
        )

    def delete_file(self, root: ExplorerRoot, path: str) -> None:
        _, target, rel = self._resolve(root, path, allow_empty=False)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError("Dosya bulunamadı")

        inferred = self._infer_stored_kind_and_filename(root, rel)
        if inferred is not None:
            kind, filename = inferred
            sp_files.set_stored_json_favorite(kind, filename, False)  # type: ignore[arg-type]
            repository.delete_stored_json_output(self.db, kind=kind, filename=filename)

        if self.is_favoritable(root, rel):
            sp_files.set_path_favorite(root, rel, False)

        target.unlink()

    def set_favorite(self, root: ExplorerRoot, path: str, is_favorite: bool) -> None:
        _, target, rel = self._resolve(root, path, allow_empty=False)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError("Dosya bulunamadı")
        if not self.is_favoritable(root, rel):
            raise ValueError("Bu dosya favorilenemez")

        inferred = self._infer_stored_kind_and_filename(root, rel)
        if inferred is not None:
            kind, filename = inferred
            row = repository.get_stored_json_output(self.db, kind=kind, filename=filename)
            if row is None:
                content = sp_files.read_json_file(kind, filename)  # type: ignore[arg-type]
                repository.upsert_stored_json_output(
                    self.db,
                    kind=kind,
                    filename=filename,
                    content=content,
                    source_sub_pipeline_id=None,
                )
            repository.set_stored_json_output_favorite(self.db, kind=kind, filename=filename, is_favorite=is_favorite)
            sp_files.set_stored_json_favorite(kind, filename, is_favorite)  # type: ignore[arg-type]
            return

        sp_files.set_path_favorite(root, rel, is_favorite)
