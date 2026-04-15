from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db import repository


def write_pipeline_log(
    db: Session,
    *,
    mode: str,
    component: str,
    message: str,
    pipeline_id: str | None,
    sub_pipeline_id: str | None,
    level: str = "info",
    details: Any | None = None,
    log_path: Path | None = None,
) -> int:
    ts = datetime.now(timezone.utc).isoformat()
    line = f"{ts} [{level.upper()}] [{component}] {message}"
    print(line, flush=True)
    if log_path is not None:
        try:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass
    return repository.record_pipeline_log(
        db,
        mode=mode,
        level=level,
        component=component,
        message=message,
        pipeline_id=pipeline_id,
        sub_pipeline_id=sub_pipeline_id,
        details=details,
    )
