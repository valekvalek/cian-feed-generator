#!/usr/bin/env python3
"""Keep deprecated public feed URLs valid during migration."""

from __future__ import annotations

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


def main() -> None:
    for alias, source in LEGACY_ALIASES.items():
        copy_atomic(source, alias)
        print(f"✓ {alias} ← {source}")


if __name__ == "__main__":
    main()
