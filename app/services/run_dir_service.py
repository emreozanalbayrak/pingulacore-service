from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")


def _safe_token(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", value).strip("_") or "run"


def make_run_dir_name(yaml_filename: str | None = None, token: str | None = None) -> str:
    """
    Build the timestamped folder name: {YYYY-MM-DD_HH-MM-SS}_{first_token}_{uuid6}

    first_token priority:
      1. First underscore-delimited segment of yaml_filename stem (e.g. "g1" from "g1_toplama.yaml")
      2. token argument (used for sub-pipelines that receive a question_id instead of a yaml filename)
      3. Fallback: "run"

    A 6-char UUID suffix prevents collisions when two runs start in the same second.
    """
    ts = _timestamp()
    if yaml_filename:
        stem = Path(yaml_filename).stem
        raw = stem.split("_")[0]
    elif token:
        raw = token.split("_")[0]
    else:
        raw = "run"
    first = _safe_token(raw)[:20]
    suffix = uuid4().hex[:6]
    return f"{ts}_{first}_{suffix}"


def create_full_run_dir(runs_dir: Path, yaml_filename: str) -> Path:
    """Create runs/full/{name}/ and runs/full/{name}/assets/ — returns the run directory."""
    name = make_run_dir_name(yaml_filename=yaml_filename)
    run_dir = runs_dir / "full" / name
    (run_dir / "assets").mkdir(parents=True, exist_ok=True)
    return run_dir


def create_sub_run_dir(
    runs_dir: Path,
    yaml_filename: str | None = None,
    token: str | None = None,
) -> Path:
    """Create runs/sub/{name}/ and runs/sub/{name}/assets/ — returns the run directory."""
    name = make_run_dir_name(yaml_filename=yaml_filename, token=token)
    run_dir = runs_dir / "sub" / name
    (run_dir / "assets").mkdir(parents=True, exist_ok=True)
    return run_dir


def create_standalone_run_dir(runs_dir: Path, agent_name: str) -> Path:
    """Create runs/standalone/{name}/ — returns the run directory (no assets/ subdir)."""
    name = make_run_dir_name(token=agent_name)
    run_dir = runs_dir / "standalone" / name
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_manifest(
    run_dir: Path,
    *,
    run_type: str,
    yaml_filename: str | None,
    agent_name: str | None,
    pipeline_id: str | None,
    sub_pipeline_id: str | None,
    sub_kind: str | None,
) -> None:
    """Write manifest.json into run_dir."""
    manifest = {
        "run_type": run_type,
        "run_dir": str(run_dir.name),
        "yaml_filename": yaml_filename,
        "agent_name": agent_name,
        "pipeline_id": pipeline_id,
        "sub_pipeline_id": sub_pipeline_id,
        "sub_kind": sub_kind,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def update_manifest_status(run_dir: Path, status: str) -> None:
    """Update the status field in an existing manifest.json."""
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = status
        manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


def run_relative_path(run_dir: Path, runs_dir: Path, *parts: str) -> str:
    """
    Return the runs-relative URL fragment suitable for HTML src= attributes and
    the /assets/ endpoint.

    Example: run_relative_path(run_dir, runs_dir, "assets", "classroom.png")
             → "runs/full/2026-04-15_14-30-00_g1_abc123/assets/classroom.png"
    """
    rel = run_dir.relative_to(runs_dir.parent)  # e.g. runs/full/2026-04-15_...
    if parts:
        rel = rel / Path(*parts)
    return str(rel)
