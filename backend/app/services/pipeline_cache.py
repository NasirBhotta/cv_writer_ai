
import hashlib
import json
import os

from pathlib import Path
from typing import Any


CACHE_DIR = (
    Path(__file__).resolve().parents[3]
    / ".cache"
    / "resume_pipeline"
)


def _cache_enabled() -> bool:
    value = os.getenv(
        "RESUME_CACHE_ENABLED", "1"
    ).lower()

    return value not in {
        "0", "false", "off", "no"
    }


def _cache_path(
    stage: str,
    inputs: dict[str, Any],
    cache_dir: Path | None = None,
) -> Path:
    # Version lets us invalidate old results.
    version = os.getenv(
        "RESUME_CACHE_VERSION", "v1"
    )

    payload = {
        "version": version,
        "stage": stage,
        "inputs": inputs,
    }

    serialized = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    fingerprint = hashlib.sha256(
        serialized.encode("utf-8")
    ).hexdigest()

    directory = (
        cache_dir
        if cache_dir is not None
        else CACHE_DIR
    )

    return directory / f"{stage}_{fingerprint}.json"


def load_cached(
    stage: str,
    inputs: dict[str, Any],
    cache_dir: Path | None = None,
) -> Any | None:
    if not _cache_enabled():
        return None

    path = _cache_path(stage, inputs, cache_dir)

    if not path.exists():
        return None

    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        # Corrupt cache should not break the pipeline.
        return None


def save_cached(
    stage: str,
    inputs: dict[str, Any],
    result: Any,
    cache_dir: Path | None = None,
) -> bool:
    if not _cache_enabled():
        return False

    path = _cache_path(stage, inputs, cache_dir)

    try:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return True

    except (OSError, TypeError, ValueError):
        # Cache is optional; generation can continue.
        return False
