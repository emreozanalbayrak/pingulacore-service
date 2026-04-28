"""Legacy pipeline service — in-process geometry (pomodoro) + turkce (agentic).

Subprocess + dış repo bağımlılığı kaldırıldı. Pomodoro ve agentic modülleri service repo'sunun
içinde vendor edildi; çağrılar `asyncio.to_thread` ile event loop'u tıkamadan koşulur.
Senkron pipeline'ların stdout/stderr'i satır satır yakalanıp DB'ye + SSE stream'ine yazılır.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import os
import re
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml as _yaml
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db import repository
from app.db.database import SessionLocal
from app.db.models import Pipeline
from app.services import log_stream_service
from app.services.pipeline_log_service import write_pipeline_log


LegacyKind = Literal["geometry", "turkce"]


@dataclass(frozen=True)
class LegacyPipelineDef:
    kind: LegacyKind
    label: str


LEGACY_PIPELINES: dict[LegacyKind, LegacyPipelineDef] = {
    "geometry": LegacyPipelineDef(kind="geometry", label="Geometri"),
    "turkce": LegacyPipelineDef(kind="turkce", label="Türkçe"),
}


_BACKGROUND_TASKS: set[asyncio.Task] = set()


UPLOAD_PREFIX = "uploads/"


def _yaml_root(kind: LegacyKind, settings: Settings) -> Path:
    if kind == "geometry":
        return settings.legacy_geo_yaml_dir
    if kind == "turkce":
        return settings.legacy_turkce_configs_dir
    raise RuntimeError(f"Bilinmeyen kind: {kind}")


def _uploads_root(kind: LegacyKind, settings: Settings) -> Path:
    return settings.legacy_uploads_dir / kind


def _safe_relative(rel_path: str, root: Path) -> Path:
    candidate = Path(rel_path)
    if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        raise ValueError("Geçersiz YAML yolu")
    resolved = (root / candidate).resolve()
    root_resolved = root.resolve()
    if root_resolved not in resolved.parents and resolved != root_resolved:
        raise ValueError("YAML kök dizinin dışında")
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(f"YAML bulunamadı: {rel_path}")
    return resolved


def _resolve_yaml_path(kind: LegacyKind, yaml_path: str, settings: Settings) -> Path:
    """Resolve a YAML path against vendored root or — if prefixed `uploads/` — uploads dir."""
    if yaml_path.startswith(UPLOAD_PREFIX):
        rel = yaml_path[len(UPLOAD_PREFIX) :]
        return _safe_relative(rel, _uploads_root(kind, settings))
    return _safe_relative(yaml_path, _yaml_root(kind, settings))


def _is_kind_enabled(kind: LegacyKind, settings: Settings) -> bool:
    """Vendor'lı kodlar her zaman erişilebilir; koşul API key ve ilgili içerik dizinleri."""
    if kind not in LEGACY_PIPELINES:
        return False
    if not (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
        return False
    if kind == "geometry":
        root = settings.legacy_geo_yaml_dir
        return root.exists() and root.is_dir()
    if kind == "turkce":
        required_dirs = (
            settings.legacy_turkce_configs_dir,
            settings.legacy_turkce_templates_dir,
        )
        return all(path.exists() and path.is_dir() for path in required_dirs)
    return False


def _apply_legacy_environment(settings: Settings) -> None:
    """Vendored legacy modules read a few paths from env at import time."""
    os.environ["LEGACY_STATE_DIR"] = str(settings.legacy_state_dir)
    os.environ["LEGACY_TURKCE_CONFIGS_DIR"] = str(settings.legacy_turkce_configs_dir)
    os.environ["LEGACY_TURKCE_TEMPLATES_DIR"] = str(settings.legacy_turkce_templates_dir)
    os.environ["LEGACY_TURKCE_MEB_BOOKS_DIR"] = str(settings.legacy_turkce_meb_books_dir)
    os.environ["LEGACY_TURKCE_DATA_DIR"] = str(settings.legacy_turkce_data_dir)


def list_pipelines(settings: Settings | None = None) -> list[dict[str, Any]]:
    s = settings or get_settings()
    _apply_legacy_environment(s)
    out: list[dict[str, Any]] = []
    for kind, defn in LEGACY_PIPELINES.items():
        out.append(
            {
                "kind": kind,
                "label": defn.label,
                "enabled": _is_kind_enabled(kind, s),
                "yaml_root": str(_yaml_root(kind, s)),
                "default_params": {"difficulty": "orta"} if kind == "geometry" else {},
            }
        )
    return out


def list_yaml_files(kind: LegacyKind, settings: Settings | None = None) -> list[str]:
    s = settings or get_settings()
    files: list[str] = []
    for prefix, root in (("", _yaml_root(kind, s)), (UPLOAD_PREFIX, _uploads_root(kind, s))):
        if not root.exists() or not root.is_dir():
            continue
        for path in root.rglob("*.y*ml"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".yaml", ".yml"}:
                continue
            if not _looks_like_pipeline_yaml(kind, path):
                continue
            rel = path.relative_to(root).as_posix()
            files.append(prefix + rel)
    files.sort()
    return files


def save_uploaded_yaml(
    kind: LegacyKind,
    *,
    filename: str,
    content: bytes,
    settings: Settings | None = None,
) -> str:
    """Validate + persist an uploaded YAML under the kind's uploads dir.

    Returns the path token (`uploads/<filename>`) usable by `run()`.
    """
    s = settings or get_settings()
    if kind not in LEGACY_PIPELINES:
        raise ValueError(f"Bilinmeyen pipeline türü: {kind}")
    if len(content) > 2 * 1024 * 1024:
        raise ValueError("YAML dosyası 2 MB sınırını aşıyor")

    safe_name = Path(filename).name
    if not safe_name or safe_name in {".", ".."}:
        raise ValueError("Geçersiz dosya adı")
    if Path(safe_name).suffix.lower() not in {".yaml", ".yml"}:
        raise ValueError("Yalnızca .yaml/.yml uzantıları kabul edilir")

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"YAML UTF-8 değil: {exc}") from exc
    try:
        data = _yaml.safe_load(text)
    except _yaml.YAMLError as exc:
        raise ValueError(f"YAML parse hatası: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("YAML kök öğesi sözlük olmalı")

    uploads_root = _uploads_root(kind, s)
    uploads_root.mkdir(parents=True, exist_ok=True)
    target = uploads_root / safe_name

    # Mark with a kind-specific structural check so we don't accept arbitrary YAMLs
    # that the pipeline can't run.
    if kind == "geometry" and not (isinstance(data.get("meta"), dict) and isinstance(data.get("context"), dict)):
        raise ValueError("Geometri YAML'ı `meta` ve `context` bloklarını içermeli")
    if kind == "turkce":
        has_generation_entry = any(k in data for k in ("template", "generation_plan", "context_generation_plan"))
        has_topic_source = any(k in data for k in ("topic", "topics_file"))
        if not (has_generation_entry and has_topic_source):
            raise ValueError(
                "Türkçe YAML'ı `template`/`generation_plan`/`context_generation_plan` ve `topic`/`topics_file` içermeli"
            )

    target.write_text(text, encoding="utf-8")
    return UPLOAD_PREFIX + safe_name


def _looks_like_pipeline_yaml(kind: LegacyKind, path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = _yaml.safe_load(fh) or {}
    except Exception:
        return False
    if not isinstance(data, dict):
        return False

    if kind == "geometry":
        return isinstance(data.get("meta"), dict) and isinstance(data.get("context"), dict)

    if kind == "turkce":
        has_generation_entry = any(
            key in data for key in ("template", "generation_plan", "context_generation_plan")
        )
        has_topic_source = any(key in data for key in ("topic", "topics_file"))
        return has_generation_entry and has_topic_source

    return False


def _run_dir_for(kind: LegacyKind, run_id: str, settings: Settings) -> Path:
    return settings.runs_dir / f"legacy_{kind}" / run_id


# -----------------------------------------------------------------------------
# Stream capture: stdout/stderr satırlarını DB + SSE'ye besle.
# -----------------------------------------------------------------------------


_SELF_PREFIX_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T[\d:.+\-]+\s+\[[A-Z]+\]\s+\[legacy_(stdout|stderr|runner)\]\s"
)
_RATE_CAP_PER_SEC = 50
_MAX_LINE_LEN = 4096


def _detach_stale_logging_handlers(captures: tuple[io.TextIOBase, ...]) -> None:
    """Vendored kodlar (özellikle agentic) çalışırken `logging.StreamHandler()` veya
    `logging.basicConfig` çağırırsa, default sys.stderr/stdout o sırada
    capture'a bağlı olduğundan handler stale capture'a sabitlenir. Run bittikten
    sonra root logger ve `agentic` logger'ı tarayıp bu capture'lara bağlı handler'ları
    çıkar — sonraki run'lara sızmamaları için.
    """
    import logging as _logging

    capture_set = set(id(c) for c in captures)
    for name in (None, "agentic"):
        logger = _logging.getLogger(name) if name else _logging.getLogger()
        for handler in list(logger.handlers):
            stream = getattr(handler, "stream", None)
            if stream is not None and id(stream) in capture_set:
                logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass


class _RateLimiter:
    """Per-instance simple sliding window rate limiter (1s window)."""

    def __init__(self, max_per_sec: int) -> None:
        self._max = max_per_sec
        self._window_start = 0.0
        self._count = 0
        self._dropped = 0
        self._lock = threading.Lock()

    def allow(self) -> tuple[bool, int]:
        """Return (allowed, dropped_since_last_allowed). dropped is 0 unless
        we just transitioned out of a saturated window."""
        with self._lock:
            now = time.monotonic()
            if now - self._window_start >= 1.0:
                dropped = self._dropped
                self._window_start = now
                self._count = 1
                self._dropped = 0
                return True, dropped
            if self._count < self._max:
                self._count += 1
                return True, 0
            self._dropped += 1
            return False, 0


class _StreamCapture(io.TextIOBase):
    """Per-run stdout/stderr capture. Her newline'da publish'i tetikler.

    Defensive guards:
    - Re-entrancy: aynı thread içinden tekrar girişte capture'a alma (loop kırma).
    - Self-format drop: kendi `<ts> [LEVEL] [legacy_*]` formatımızla başlayan
      satırlar capture'a geri sızmışsa drop et (loop kırma).
    - Rate cap: per-run sn'de _RATE_CAP_PER_SEC üstündeki satırlar atılır,
      pencere bitince sayım özet olarak akar.
    - Length cap: tek satır _MAX_LINE_LEN'i geçerse trunc edilir.

    `loop.call_soon_threadsafe` ile thread-safe; pomodoro/agentic asyncio.to_thread
    içinde koştuğu için event loop'a güvenli teslim eder.
    """

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        run_id: str,
        mode: str,
        component: str,
        level: str,
        stream_key: str | None,
    ) -> None:
        self._loop = loop
        self._run_id = run_id
        self._mode = mode
        self._component = component
        self._level = level
        self._stream_key = stream_key
        self._buffer = ""
        self._tls = threading.local()
        self._limiter = _RateLimiter(_RATE_CAP_PER_SEC)

    def writable(self) -> bool:
        return True

    def write(self, s: str) -> int:
        if not isinstance(s, str):
            s = str(s)
        # Re-entrancy guard: bir feedback path bizi tekrar çağırırsa orijinal
        # stdout'a sessizce drop et.
        if getattr(self._tls, "in_write", False):
            return len(s)
        self._tls.in_write = True
        try:
            self._buffer += s
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                self._dispatch(line)
            return len(s)
        finally:
            self._tls.in_write = False

    def flush(self) -> None:
        if getattr(self._tls, "in_write", False):
            return
        if self._buffer:
            self._tls.in_write = True
            try:
                line, self._buffer = self._buffer, ""
                self._dispatch(line)
            finally:
                self._tls.in_write = False

    def _dispatch(self, line: str) -> None:
        line = line.rstrip("\r")
        if not line:
            return
        # Kendi formatımızla başlayan satırlar — feedback loop kanıtı.
        if _SELF_PREFIX_RE.match(line):
            return
        if len(line) > _MAX_LINE_LEN:
            line = line[:_MAX_LINE_LEN] + " …[truncated]"
        allowed, dropped_summary = self._limiter.allow()
        if not allowed:
            return
        if dropped_summary:
            self._safe_emit(
                f"[rate-cap] previous 1s window dropped {dropped_summary} lines (cap={_RATE_CAP_PER_SEC}/s)"
            )
        self._safe_emit(line)

    def _safe_emit(self, line: str) -> None:
        try:
            self._loop.call_soon_threadsafe(
                _emit_log_line,
                self._run_id,
                self._mode,
                self._component,
                self._level,
                line,
                self._stream_key,
            )
        except RuntimeError:
            pass


def _emit_log_line(
    run_id: str,
    mode: str,
    component: str,
    level: str,
    message: str,
    stream_key: str | None,
) -> None:
    """Event loop içinde yakalanan stdout/stderr satırını DB + SSE'ye yazar.

    `write_pipeline_log()` stdout'a da print eder. Legacy runner aktifken stdout
    global capture altında olduğundan burada print etmek aynı log satırını yeniden
    capture edip çoğaltır.
    """
    db = SessionLocal()
    try:
        repository.record_pipeline_log(
            db,
            mode=mode,
            level=level,
            component=component,
            message=message,
            pipeline_id=run_id,
            sub_pipeline_id=None,
            details=None,
        )
        if stream_key:
            ts = datetime.now(timezone.utc).isoformat()
            line = f"{ts} [{level.upper()}] [{component}] {message}"
            log_stream_service.publish(stream_key, line)
    except Exception:
        try:
            if stream_key:
                log_stream_service.publish(stream_key, f"[{level.upper()}] [{component}] {message}")
        except Exception:
            pass
    finally:
        db.close()


# -----------------------------------------------------------------------------
# In-process runners
# -----------------------------------------------------------------------------


def _run_geometry_sync(
    *,
    yaml_abs: Path,
    run_dir: Path,
    difficulty: str,
    variant_name: str | None,
) -> None:
    """Geometri pipeline'ı (pomodoro.graph.run) sync olarak çalıştırır."""
    from pomodoro.graph import run as pomodoro_run

    pomodoro_run(
        yaml_path=str(yaml_abs),
        difficulty=difficulty,
        output_dir=str(run_dir),
        variant_name=variant_name,
    )


def _run_turkce_sync(
    *,
    yaml_abs: Path,
    run_dir: Path,
) -> None:
    """Türkçe pipeline'ı (agentic.__main__.main_async) sync olarak çalıştırır.

    Subprocess wrapper'ın yaptığı gibi: orijinal config YAML'i geçici dosyaya kopyalar,
    `output.dir` alanını backend run_dir'e override eder, sonra main_async çağırır.
    """
    import asyncio as _asyncio
    from agentic.__main__ import main_async  # type: ignore

    with yaml_abs.open("r", encoding="utf-8") as fh:
        config_data = _yaml.safe_load(fh) or {}
    if not isinstance(config_data, dict):
        config_data = {}
    output_block = config_data.get("output")
    if not isinstance(output_block, dict):
        output_block = {}
        config_data["output"] = output_block
    output_block["dir"] = str(run_dir)

    # Geçici YAML'i orijinal dizinde tut → relative path'ler (PDF, topics_file vb.) korunur.
    tmp_dir = yaml_abs.parent
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=f"_legacy_run_{yaml_abs.stem}_",
        suffix=".yaml",
        dir=str(tmp_dir),
    )
    os.close(fd)
    tmp_path = Path(tmp_path_str)
    try:
        with tmp_path.open("w", encoding="utf-8") as fh:
            _yaml.safe_dump(config_data, fh, allow_unicode=True, sort_keys=False)

        original_argv = sys.argv[:]
        original_cwd = os.getcwd()
        sys.argv = ["agentic", "--config", str(tmp_path)]
        try:
            # agentic kökten relative path'leri config dir'e göre çözer; cwd değiştirmiyoruz.
            exit_code = _asyncio.run(main_async())
        finally:
            sys.argv = original_argv
            try:
                os.chdir(original_cwd)
            except Exception:
                pass

        if exit_code not in (None, 0):
            raise RuntimeError(f"agentic main_async exit_code={exit_code}")
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Service
# -----------------------------------------------------------------------------


class LegacyPipelineService:
    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()
        _apply_legacy_environment(self.settings)

    def _resolve_yaml(self, kind: LegacyKind, yaml_path: str) -> Path:
        return _resolve_yaml_path(kind, yaml_path, self.settings)

    async def run(
        self,
        *,
        kind: LegacyKind,
        yaml_path: str,
        params: dict[str, Any],
        stream_key: str | None,
    ) -> dict[str, Any]:
        if kind not in LEGACY_PIPELINES:
            raise ValueError(f"Bilinmeyen pipeline: {kind}")
        if not _is_kind_enabled(kind, self.settings):
            raise RuntimeError(
                f"{kind} legacy pipeline yapılandırılmamış (GOOGLE_API_KEY ve YAML dizini gerekli)"
            )

        yaml_abs = self._resolve_yaml(kind, yaml_path)

        mode = f"legacy_{kind}"
        pipeline_row = repository.create_pipeline(
            self.db,
            yaml_filename=yaml_path,
            retry_config={"params": params},
        )
        pipeline_row.mode = mode
        self.db.add(pipeline_row)
        self.db.commit()
        self.db.refresh(pipeline_row)
        run_id = pipeline_row.id

        run_dir = _run_dir_for(kind, run_id, self.settings)
        run_dir.mkdir(parents=True, exist_ok=True)

        write_pipeline_log(
            self.db,
            mode=mode,
            component="legacy_runner",
            message=f"Başlatılıyor: kind={kind} yaml={yaml_path}",
            pipeline_id=run_id,
            sub_pipeline_id=None,
            level="info",
            details={"run_dir": str(run_dir), "params": params},
            stream_key=stream_key,
        )
        timeout_seconds = self.settings.legacy_timeout_seconds
        loop = asyncio.get_running_loop()

        async def _supervise() -> None:
            error_msg: str | None = None

            stdout_capture = _StreamCapture(
                loop=loop,
                run_id=run_id,
                mode=mode,
                component="legacy_stdout",
                level="info",
                stream_key=stream_key,
            )
            stderr_capture = _StreamCapture(
                loop=loop,
                run_id=run_id,
                mode=mode,
                component="legacy_stderr",
                level="warning",
                stream_key=stream_key,
            )

            def _invoke_in_thread() -> None:
                with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
                    try:
                        if kind == "geometry":
                            _run_geometry_sync(
                                yaml_abs=yaml_abs,
                                run_dir=run_dir,
                                difficulty=str(params.get("difficulty") or "orta"),
                                variant_name=(str(params.get("variant_name")) or None) if params.get("variant_name") else None,
                            )
                        elif kind == "turkce":
                            _run_turkce_sync(yaml_abs=yaml_abs, run_dir=run_dir)
                        else:
                            raise RuntimeError(f"Bilinmeyen kind: {kind}")
                    finally:
                        stdout_capture.flush()
                        stderr_capture.flush()
                        _detach_stale_logging_handlers((stdout_capture, stderr_capture))

            try:
                await asyncio.wait_for(asyncio.to_thread(_invoke_in_thread), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                error_msg = f"Timeout ({timeout_seconds}s) aşıldı"
            except Exception as exc:
                error_msg = f"{type(exc).__name__}: {exc}"

            status = "success" if error_msg is None else "failed"

            bg_db = SessionLocal()
            try:
                try:
                    write_pipeline_log(
                        bg_db,
                        mode=mode,
                        component="legacy_runner",
                        message=f"Tamamlandı: status={status}",
                        pipeline_id=run_id,
                        sub_pipeline_id=None,
                        level="info" if status == "success" else "error",
                        details={"error": error_msg},
                        stream_key=stream_key,
                    )
                except Exception:
                    pass
                try:
                    repository.finish_pipeline(bg_db, run_id, status, error_msg)
                except Exception:
                    pass
            finally:
                bg_db.close()

            if stream_key:
                try:
                    log_stream_service.publish_done(stream_key)
                except Exception:
                    pass

        task = asyncio.create_task(_supervise())
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)

        return {
            "run_id": run_id,
            "pipeline_id": run_id,
            "status": "running",
            "stream_key": stream_key,
        }

    def get_run_detail(self, run_id: str) -> dict[str, Any] | None:
        row = self.db.get(Pipeline, run_id)
        if row is None or not str(row.mode).startswith("legacy_"):
            return None
        kind: LegacyKind
        if row.mode == "legacy_geometry":
            kind = "geometry"
        elif row.mode == "legacy_turkce":
            kind = "turkce"
        else:
            return None
        run_dir = _run_dir_for(kind, run_id, self.settings)
        outputs = _collect_outputs(run_dir)
        return {
            "run_id": row.id,
            "kind": kind,
            "yaml_path": row.yaml_filename,
            "status": row.status,
            "error": row.error,
            "started_at": row.created_at.isoformat() if row.created_at else "",
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            "outputs": outputs,
        }


def _collect_outputs(run_dir: Path) -> list[dict[str, Any]]:
    if not run_dir.exists():
        return []
    settings = get_settings()
    runs_root = settings.runs_dir.resolve()
    items: list[dict[str, Any]] = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            abs_path = path.resolve()
            rel_to_runs_root = abs_path.relative_to(runs_root.parent)
        except ValueError:
            continue
        items.append(
            {
                "path": str(abs_path),
                "url": f"/v1/assets/{rel_to_runs_root.as_posix()}",
                "size": path.stat().st_size,
            }
        )
    return items
