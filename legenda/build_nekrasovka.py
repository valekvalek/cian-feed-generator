#!/usr/bin/env python3
"""Build the combined Nekrasovka feed from the two current Legenda feeds."""

from datetime import datetime, timezone
from pathlib import Path
from xml.etree.ElementTree import Element, parse

from feed_common import validate_feed, write_feed_atomic


SOURCES = (
    (Path("legenda/marusino_feed.xml"), 5),
    (Path("legenda/korenevo_feed.xml"), 5),
)
OUTPUT_FILE = Path("legenda/nekrasovka_feed.xml")


def collect_objects() -> list[Element]:
    objects: list[Element] = []
    for path, minimum in SOURCES:
        count = validate_feed(path, min_objects=minimum)
        objects.extend(parse(path).getroot().findall("object"))
        print(f"✓ {path}: {count} объектов")
    return objects


def main() -> None:
    objects = collect_objects()
    write_feed_atomic(
        objects,
        OUTPUT_FILE,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        min_objects=10,
    )
    print(f"✅ {OUTPUT_FILE}: {len(objects)} объектов")


if __name__ == "__main__":
    main()
