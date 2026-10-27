"""
In-process reuse of computed dataset state.

Every analytics request used to re-read all committed rows of the active
dataset, re-infer its structure and re-run the module. On a 70k-row upload that
is several seconds per page view even though nothing about the dataset changed
between two requests.

This module keeps the prepared frame, the capability map and each module payload
for the *current version* of a dataset. Entries are keyed by a signature taken
from the registry row (id, row count, template, task, target, upload marker plus
digests of the mapping and validation documents), so a reclassification, remap,
target change or re-upload produces a new key and the old entry is never read
again. A TTL and a small bound keep memory in check.

Every hit returns a deep copy: callers may extend the payload (the strategy
endpoint does) and a shared mutable frame would let two concurrent requests
interfere with each other.
"""
from __future__ import annotations

import copy
import os
import time
import zlib
from collections import OrderedDict
from threading import RLock
from typing import Any, Hashable, Optional

from db.models import DatasetMeta

TTL_SECONDS = float(os.getenv("BIDS_CACHE_TTL", "900"))
FRAME_ENTRIES = int(os.getenv("BIDS_CACHE_FRAMES", "4"))
PAYLOAD_ENTRIES = int(os.getenv("BIDS_CACHE_PAYLOADS", "64"))


def _digest(value: Optional[str]) -> int:
    if not value:
        return 0
    return zlib.crc32(value.encode("utf-8", "ignore"))


def dataset_signature(meta: Optional[DatasetMeta]) -> Optional[tuple]:
    """Version marker for one dataset revision; None when there is nothing to cache."""
    if meta is None or meta.id is None:
        return None
    return (
        meta.id,
        meta.row_count or 0,
        meta.schema_kind or "",
        meta.analysis_task or "",
        meta.target_field or "",
        str(meta.uploaded_at or ""),
        _digest(meta.mapping_json),
        _digest(meta.validation_json),
    )


class _Store:
    """Thread-safe LRU with a time-to-live."""

    def __init__(self, max_entries: int) -> None:
        self._items: "OrderedDict[Hashable, tuple[float, Any]]" = OrderedDict()
        self._lock = RLock()
        self._max = max(1, max_entries)

    def get(self, key: Hashable) -> Optional[Any]:
        if not key:
            return None
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            if TTL_SECONDS > 0 and (time.time() - stored_at) > TTL_SECONDS:
                self._items.pop(key, None)
                return None
            self._items.move_to_end(key)
            return copy.deepcopy(value)

    def put(self, key: Hashable, value: Any) -> None:
        if not key:
            return
        with self._lock:
            self._items[key] = (time.time(), copy.deepcopy(value))
            self._items.move_to_end(key)
            while len(self._items) > self._max:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


_frames = _Store(FRAME_ENTRIES)
_payloads = _Store(PAYLOAD_ENTRIES)


def get_frame(key: Optional[tuple]) -> Optional[tuple[dict, Any]]:
    """(capabilities, prepared frame) for a dataset revision, if it is cached."""
    return _frames.get(key)


def put_frame(key: Optional[tuple], capabilities: dict, frame: Any) -> None:
    # An empty frame is never cached: it can be observed between the registry
    # row and its committed records during an upload.
    if getattr(frame, "empty", True):
        return
    _frames.put(key, (capabilities, frame))


def get_payload(key: Optional[tuple]) -> Optional[dict]:
    return _payloads.get(key)


def put_payload(key: Optional[tuple], payload: dict) -> None:
    _payloads.put(key, payload)


def clear() -> None:
    """Drop everything (used by tests and by explicit workspace resets)."""
    _frames.clear()
    _payloads.clear()


def stats() -> dict:
    return {"frames": len(_frames), "payloads": len(_payloads), "ttl_seconds": TTL_SECONDS}
