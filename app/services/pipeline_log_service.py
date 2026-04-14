from __future__ import annotations

from datetime import datetime, timezone
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
) -> int:
    ts = datetime.now(timezone.utc).isoformat()
    print(f"{ts} [{component}] {message}", flush=True)
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
