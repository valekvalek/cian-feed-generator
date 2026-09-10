#!/usr/bin/env python3
"""Keep deprecated public feed URLs valid during migration."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from validate_feeds import LEGACY_ALIASES


def copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as temp_file:
            temp_name = temp_file.name
            temp_file.write(source.read_bytes())
        os.replace(temp_name, destination)
        temp_name = None
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)


def aliases_for_sources(sources: set[Path] | None = None) -> dict[Path, Path]:
    """Return only aliases owned by the selected canonical feeds."""
    if not sources:
        return dict(LEGACY_ALIASES)
    return {
        alias: source
        for alias, source in LEGACY_ALIASES.items()
        if source in sources
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        action="append",
        type=Path,
        help="Синхронизировать только aliases указанного канонического файла",
    )
    args = parser.parse_args()
    selected_sources = set(args.source) if args.source else None

    for alias, source in aliases_for_sources(selected_sources).items():
        copy_atomic(source, alias)
        print(f"✓ {alias} ← {source}")


if __name__ == "__main__":
    main()
