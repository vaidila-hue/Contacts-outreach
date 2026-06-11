"""CSV read/write helpers."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def read_csv(path: Path, columns: list[str] | None = None) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [dict(row) for row in reader]
    if columns:
        for row in rows:
            for col in columns:
                row.setdefault(col, "")
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in columns})


def empty_row(columns: list[str]) -> dict[str, str]:
    return {col: "" for col in columns}
