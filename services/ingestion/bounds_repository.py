"""Hot-reloadable bounds repository.

TRD v2.0 §3.1 requires implausible-value bounds to be "a versioned,
editable table, not a magic number in code."  This module provides a
``BoundsRepository`` protocol and two concrete implementations:

* ``FileBoundsRepository`` — reads from a JSON file and watches its
  mtime for hot-reload (no redeploy needed).
* ``DatabaseBoundsRepository`` — reads from the
  ``implausible_value_bounds`` table added in migration 0005.

Both expose the same ``get()`` interface so the quality gate is
storage-agnostic.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Protocol

from services.ingestion.config import BoundsConfig, BoundsEntry


class BoundsRepository(Protocol):
    def get(self) -> BoundsConfig: ...


class FileBoundsRepository:
    """Reads ``BoundsConfig`` from a JSON file, hot-reloading on mtime change."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._mtime: float = 0.0
        self._config: BoundsConfig = BoundsConfig()
        self._load()

    def _load(self) -> None:
        try:
            stat = os.stat(self._path)
            if stat.st_mtime != self._mtime:
                with open(self._path) as f:
                    data: dict[str, Any] = json.load(f)
                self._config = BoundsConfig.model_validate(data)
                self._mtime = stat.st_mtime
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            pass

    def get(self) -> BoundsConfig:
        with self._lock:
            self._load()
            return self._config


class DatabaseBoundsRepository:
    """Reads bounds from the ``implausible_value_bounds`` table.

    Accepts a callable that returns a DB connection (to stay compatible
    with both sync and async connection pools).
    """

    def __init__(self, get_connection: Any) -> None:
        self._get_connection = get_connection

    def get(self) -> BoundsConfig:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT circuit_type, min_kwh, max_kwh "
                "FROM implausible_value_bounds "
                "WHERE is_active = TRUE "
                "ORDER BY circuit_type"
            )
            rows = cursor.fetchall()
        finally:
            conn.close()

        if not rows:
            return BoundsConfig()

        circuit_type_bounds: dict[str, BoundsEntry] = {}
        default_bounds = BoundsEntry(min_kwh=0.0, max_kwh=5000.0)
        for row in rows:
            ct, lo, hi = row[0], float(row[1]), float(row[2])
            entry = BoundsEntry(min_kwh=lo, max_kwh=hi)
            if ct == "__default__":
                default_bounds = entry
            else:
                circuit_type_bounds[ct] = entry

        return BoundsConfig(
            circuit_type_bounds=circuit_type_bounds,
            default_bounds=default_bounds,
        )


class InMemoryBoundsRepository:
    """In-memory bounds repository for testing."""

    def __init__(self, config: BoundsConfig | None = None) -> None:
        self._config = config or BoundsConfig()

    def set(self, config: BoundsConfig) -> None:
        self._config = config

    def get(self) -> BoundsConfig:
        return self._config
