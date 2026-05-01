from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db import repository
from app.services import log_stream_service


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
    stream_key: str | None = None,
) -> int:
    ts = datetime.now(timezone.utc).isoformat()
    line = f"{ts} [{level.upper()}] [{component}] {message}"
    # sys.__stdout__: vendored pipeline'lar contextlib.redirect_stdout ile sys.stdout'u
    # capture eder. Buradan print() etmek bu capture'a tekrar girip sonsuz feedback loop
    # üretir; orijinal stdout'a yazıp redirect'i bypass ediyoruz.
    try:
        sys.__stdout__.write(line + "\n")
        sys.__stdout__.flush()
    except Exception:
        pass
    if log_path is not None:
        try:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass
    if stream_key:
        log_stream_service.publish(stream_key, line)
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
