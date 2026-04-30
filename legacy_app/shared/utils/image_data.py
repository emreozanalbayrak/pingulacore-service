from __future__ import annotations

import base64
import mimetypes
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=128)
def _encode_image_data_uri_cached(
    resolved_path: str,
    mtime_ns: int,
    size_bytes: int,
) -> str:
    mime_type = mimetypes.guess_type(resolved_path)[0] or "image/png"
    with open(resolved_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime_type};base64,{image_b64}"


def encode_image_data_uri(image_path: str | Path) -> str:
    """Return a cacheable data URI for a local image path."""
    path = Path(image_path).resolve()
    stat = path.stat()
    return _encode_image_data_uri_cached(
        str(path),
        stat.st_mtime_ns,
        stat.st_size,
    )
