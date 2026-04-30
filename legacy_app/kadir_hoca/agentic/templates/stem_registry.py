"""
Stem Usage Registry - Global persistent tracking for balanced stem selection.

Supports a reservation/commit flow so parallel workers can reserve a stem during
generation and only consume it after the question is successfully saved.
Registry stored at ~/.cache/agentic/stem_usage.json
"""

from dataclasses import dataclass
import json
import logging
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

# Platform-specific imports for file locking
if sys.platform == 'win32':
    import msvcrt
else:
    import fcntl


@dataclass(frozen=True)
class StemReservation:
    """Runtime reservation for a selected stem."""

    template_id: str
    stem_index: int
    reservation_id: str
    stem_source: str = "registry_reservation"
    reservation_status: str = "reserved"
    selected_at: str = ""
    worker_label: str = ""


def _utc_now_iso() -> str:
    """Return a UTC ISO timestamp with trailing Z."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_registry_path() -> Path:
    """Get path to stem usage registry file."""
    cache_dir = Path.home() / ".cache" / "agentic"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "stem_usage.json"


def ensure_registry_exists() -> None:
    """Initialize registry file if it doesn't exist."""
    registry_path = get_registry_path()
    if not registry_path.exists():
        initial_data = {
            "version": "2.0",
            "last_reset": _utc_now_iso(),
            "templates": {}
        }
        registry_path.write_text(json.dumps(initial_data, indent=2, ensure_ascii=False))
        logger.info(f"[STEM REGISTRY] Initialized at {registry_path}")


@contextmanager
def locked_registry(path: Path, mode: str = 'r') -> Iterator:
    """
    Context manager for thread-safe registry file access with locking.

    Args:
        path: Path to registry file
        mode: File open mode ('r' or 'r+')

    Yields:
        Open file handle with exclusive lock
    """
    file = None
    try:
        file = open(path, mode, encoding='utf-8')

        # Apply platform-specific file lock
        if sys.platform == 'win32':
            msvcrt.locking(file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX)

        yield file

    finally:
        if file:
            # Lock released automatically on close
            file.close()


def _load_registry() -> dict:
    """
    Load registry with error handling.

    Returns:
        Registry data dict

    Raises:
        Exception on unrecoverable errors (propagated to caller)
    """
    ensure_registry_exists()
    registry_path = get_registry_path()

    try:
        with locked_registry(registry_path, 'r') as f:
            data = json.load(f)
            logger.debug(f"[STEM REGISTRY] Loaded from {registry_path}")
            return data
    except json.JSONDecodeError as e:
        # Backup corrupt file and reinitialize
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = registry_path.parent / f"stem_usage.json.corrupt.{timestamp}"
        registry_path.rename(backup_path)
        logger.warning(f"[STEM REGISTRY] Corrupt JSON, backed up to {backup_path}")
        ensure_registry_exists()
        return _load_registry()
    except OSError as e:
        logger.error(f"[STEM REGISTRY] File error: {e}")
        raise


def _save_registry(data: dict) -> None:
    """
    Save registry with error handling.

    Args:
        data: Registry data to save
    """
    registry_path = get_registry_path()

    try:
        with locked_registry(registry_path, 'r+') as f:
            f.seek(0)
            f.truncate()
            json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"[STEM REGISTRY] Saved to {registry_path}")
    except OSError as e:
        # Disk full or write error - log but don't crash
        logger.warning(f"[STEM REGISTRY] Save failed (continuing with stale data): {e}")


def _initialize_template_usage(template_id: str, total_stems: int) -> dict:
    """
    Initialize usage tracking for a template.

    Args:
        template_id: Template identifier
        total_stems: Number of stems in template

    Returns:
        Template usage dict
    """
    usage = {}
    for i in range(total_stems):
        usage[str(i)] = {
            "count": 0,
            "last_used": None
        }

    return {
        "total_stems": total_stems,
        "usage": usage,
        "reservations": {},
    }


def _current_worker_label() -> str:
    """Return a compact worker label for diagnostics."""
    try:
        import asyncio as _asyncio

        task = _asyncio.current_task()
        task_name = task.get_name() if task else "sync"
    except Exception:
        task_name = "sync"
    return f"pid={os.getpid()} task={task_name}"


def _fresh_registry_data() -> dict:
    """Return a fresh registry payload."""
    return {
        "version": "2.0",
        "last_reset": _utc_now_iso(),
        "templates": {},
    }


def _ensure_template_entry(data: dict, template_id: str, total_stems: int) -> dict:
    """Ensure template entry exists and is upgraded to the latest shape."""
    if template_id not in data["templates"]:
        data["templates"][template_id] = _initialize_template_usage(template_id, total_stems)
        logger.info(
            f"[STEM REGISTRY] Initialized template {template_id} with {total_stems} stems"
        )

    template_data = data["templates"][template_id]

    if template_data.get("total_stems") != total_stems:
        logger.warning(
            f"[STEM REGISTRY] Template {template_id} stem count changed "
            f"({template_data.get('total_stems')} → {total_stems}), reinitializing"
        )
        data["templates"][template_id] = _initialize_template_usage(template_id, total_stems)
        template_data = data["templates"][template_id]

    template_data.setdefault("reservations", {})
    return template_data


def _candidate_sort_key(idx: int, entry: dict) -> tuple[str, int]:
    """Prefer never-used stems, then least-recently-used."""
    if entry["last_used"] is None:
        return ("", idx)
    return (entry["last_used"], idx)


def reserve_balanced_stem(
    template_id: str,
    total_stems: int,
    worker_label: str | None = None,
) -> StemReservation:
    """
    Reserve a stem without consuming it yet.

    Selection balances committed usage plus active reservations so parallel runs
    avoid picking the same stem when alternatives are available.
    """
    ensure_registry_exists()
    registry_path = get_registry_path()
    worker = worker_label or _current_worker_label()

    try:
        with locked_registry(registry_path, "r+") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                logger.warning("[STEM REGISTRY] Corrupt JSON detected, reinitializing")
                data = _fresh_registry_data()

            template_data = _ensure_template_entry(data, template_id, total_stems)
            usage = template_data["usage"]
            reservations = template_data["reservations"]

            active_counts = {str(i): 0 for i in range(total_stems)}
            for reservation in reservations.values():
                idx = str(reservation.get("stem_index"))
                if idx in active_counts:
                    active_counts[idx] += 1

            effective_counts = {
                idx: entry["count"] + active_counts.get(idx, 0)
                for idx, entry in usage.items()
            }
            min_count = min(effective_counts.values())
            candidates = [
                (int(idx), usage[idx])
                for idx, eff_count in effective_counts.items()
                if eff_count == min_count
            ]
            candidates.sort(key=lambda item: _candidate_sort_key(item[0], item[1]))
            selected_idx, selected_entry = candidates[0]

            reservation_id = uuid.uuid4().hex
            selected_at = _utc_now_iso()
            reservations[reservation_id] = {
                "stem_index": selected_idx,
                "reserved_at": selected_at,
                "worker": worker,
            }

            f.seek(0)
            f.truncate()
            json.dump(data, f, indent=2, ensure_ascii=False)

    except OSError as e:
        logger.error(f"[STEM REGISTRY] File error during reservation: {e}")
        raise

    logger.info(
        f"[STEM RESERVE] {worker} template={template_id} idx={selected_idx} "
        f"committed={selected_entry['count']} active_reservations={active_counts.get(str(selected_idx), 0)} "
        f"reservation={reservation_id}"
    )

    counts = [entry["count"] + active_counts.get(str(i), 0) for i, entry in enumerate(usage.values())]
    logger.info(
        f"[STEM BALANCE] {template_id}: min={min(counts)}, max={max(counts)}, "
        f"avg={sum(counts) / len(counts):.1f}"
    )

    return StemReservation(
        template_id=template_id,
        stem_index=selected_idx,
        reservation_id=reservation_id,
        selected_at=selected_at,
        worker_label=worker,
    )


def commit_reserved_stem(template_id: str, reservation_id: str) -> StemReservation:
    """Commit a previously reserved stem."""
    ensure_registry_exists()
    registry_path = get_registry_path()

    try:
        with locked_registry(registry_path, "r+") as f:
            data = json.load(f)
            template_data = data["templates"].get(template_id)
            if not template_data:
                raise KeyError(f"Template not found in registry: {template_id}")

            reservations = template_data.setdefault("reservations", {})
            reservation = reservations.pop(reservation_id, None)
            if reservation is None:
                raise KeyError(
                    f"Reservation not found for template={template_id}: {reservation_id}"
                )

            stem_index = int(reservation["stem_index"])
            usage_entry = template_data["usage"][str(stem_index)]
            usage_entry["count"] += 1
            usage_entry["last_used"] = _utc_now_iso()

            f.seek(0)
            f.truncate()
            json.dump(data, f, indent=2, ensure_ascii=False)

    except OSError as e:
        logger.error(f"[STEM REGISTRY] File error during commit: {e}")
        raise

    worker = reservation.get("worker", "unknown")
    logger.info(
        f"[STEM COMMIT] {worker} template={template_id} idx={stem_index} "
        f"reservation={reservation_id} count={usage_entry['count']}"
    )

    return StemReservation(
        template_id=template_id,
        stem_index=stem_index,
        reservation_id=reservation_id,
        reservation_status="committed",
        selected_at=reservation.get("reserved_at", ""),
        worker_label=worker,
    )


def release_reserved_stem(template_id: str, reservation_id: str) -> StemReservation | None:
    """Release a reservation without consuming usage count."""
    ensure_registry_exists()
    registry_path = get_registry_path()

    try:
        with locked_registry(registry_path, "r+") as f:
            data = json.load(f)
            template_data = data["templates"].get(template_id)
            if not template_data:
                return None

            reservations = template_data.setdefault("reservations", {})
            reservation = reservations.pop(reservation_id, None)
            if reservation is None:
                return None

            f.seek(0)
            f.truncate()
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError as e:
        logger.error(f"[STEM REGISTRY] File error during release: {e}")
        raise

    stem_index = int(reservation["stem_index"])
    worker = reservation.get("worker", "unknown")
    logger.info(
        f"[STEM RELEASE] {worker} template={template_id} idx={stem_index} "
        f"reservation={reservation_id}"
    )

    return StemReservation(
        template_id=template_id,
        stem_index=stem_index,
        reservation_id=reservation_id,
        reservation_status="released",
        selected_at=reservation.get("reserved_at", ""),
        worker_label=worker,
    )


def select_balanced_stem(template_id: str, total_stems: int) -> int:
    """
    Select stem using least-used-first algorithm with atomic read-modify-write.

    Uses a single file lock for the entire read→select→write cycle to prevent
    race conditions when multiple parallel workers access the registry.

    Algorithm:
    1. Find minimum usage count across all stems
    2. Filter stems with min count
    3. Among tied stems, pick least-recently-used (by timestamp)
    4. Update count and timestamp

    Args:
        template_id: Template identifier (e.g., 'konu_standard')
        total_stems: Total number of stems in template

    Returns:
        Selected stem index (0-based)

    Raises:
        Exception on registry errors (propagated to caller)
    """
    reservation = reserve_balanced_stem(template_id, total_stems)
    commit_reserved_stem(template_id, reservation.reservation_id)
    return reservation.stem_index


def reset_stem_registry() -> None:
    """Reset all stem usage tracking to start fresh."""
    registry_path = get_registry_path()

    initial_data = {
        "version": "2.0",
        "last_reset": _utc_now_iso(),
        "templates": {}
    }

    registry_path.write_text(json.dumps(initial_data, indent=2, ensure_ascii=False))
    logger.info(f"[STEM REGISTRY] Reset complete at {registry_path}")


def get_stem_statistics() -> dict:
    """
    Get stem usage statistics for all templates.

    Returns:
        Dict with template stats:
        {
            "template_id": {
                "total": int,
                "min": int,
                "max": int,
                "avg": float,
                "unused": int,
                "usage": {stem_idx: count, ...}
            }
        }
    """
    try:
        data = _load_registry()
    except Exception as e:
        logger.error(f"[STEM STATS] Failed to load registry: {e}")
        return {}

    stats = {}

    for template_id, template_data in data["templates"].items():
        usage = template_data["usage"]
        counts = [entry["count"] for entry in usage.values()]

        if not counts:
            continue

        stats[template_id] = {
            "total": len(counts),
            "min": min(counts),
            "max": max(counts),
            "avg": sum(counts) / len(counts),
            "unused": sum(1 for c in counts if c == 0),
            "active_reservations": len(template_data.get("reservations", {})),
            "usage": {int(idx): entry["count"] for idx, entry in usage.items()}
        }

    return stats
