#!/usr/bin/env python3
"""Validate generated feeds before they are committed."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from xml.etree.ElementTree import parse

from feed_common import FeedGenerationError, validate_feed


ACTIVE_FEEDS = {
    Path("legenda/marusino_feed.xml"): 5,
    Path("legenda/korenevo_feed.xml"): 5,
    Path("legenda/nekrasovka_feed.xml"): 10,
    Path("dominanta/svet_feed.xml"): 10,
    Path("dominanta/dominanta_feed.xml"): 10,
    Path("aeon/aeon_riverpark_feed.xml"): 20,
}

LEGACY_ALIASES = {
    Path("cian_feed.xml"): Path("legenda/nekrasovka_feed.xml"),
    Path("marusino_feed.xml"): Path("legenda/marusino_feed.xml"),
    Path("korenevo_feed.xml"): Path("legenda/korenevo_feed.xml"),
    Path("nekrasovka_feed.xml"): Path("legenda/nekrasovka_feed.xml"),
    Path("svet_feed.xml"): Path("dominanta/svet_feed.xml"),
    Path("dominanta_feed.xml"): Path("dominanta/dominanta_feed.xml"),
    Path("aeon_riverpark_feed.xml"): Path("aeon/aeon_riverpark_feed.xml"),
    Path("legenda/svet_feed.xml"): Path("dominanta/svet_feed.xml"),
    Path("legenda/dominanta_feed.xml"): Path("dominanta/dominanta_feed.xml"),
}


def external_ids(path: Path) -> list[str]:
    return [
        (obj.findtext("ExternalId") or "").strip()
        for obj in parse(path).getroot().findall("object")
    ]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_relationships() -> None:
    marusino = external_ids(Path("legenda/marusino_feed.xml"))
    korenevo = external_ids(Path("legenda/korenevo_feed.xml"))
    combined = external_ids(Path("legenda/nekrasovka_feed.xml"))
    if combined != marusino + korenevo:
        raise FeedGenerationError("nekrasovka_feed.xml не равен объединению Марусино и Коренево")

    svet = external_ids(Path("dominanta/svet_feed.xml"))
    dominanta = external_ids(Path("dominanta/dominanta_feed.xml"))
    if dominanta != svet:
        raise FeedGenerationError("dominanta_feed.xml не совпадает с текущим фидом Свет")


def validate_legacy_aliases() -> None:
    for alias, source in LEGACY_ALIASES.items():
        validate_feed(alias, min_objects=ACTIVE_FEEDS.get(source, 1))
        if digest(alias) != digest(source):
            raise FeedGenerationError(f"Legacy-файл {alias} не синхронизирован с {source}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-legacy", action="store_true")
    args = parser.parse_args()

    try:
        total = 0
        for path, minimum in ACTIVE_FEEDS.items():
            count = validate_feed(path, min_objects=minimum)
            total += count
            print(f"✓ {path}: {count} объектов")
        validate_relationships()
        if args.include_legacy:
            validate_legacy_aliases()
            print(f"✓ Legacy-файлы синхронизированы: {len(LEGACY_ALIASES)}")
        print(f"✓ Валидация завершена: {total} объектов во всех активных файлах")
        return 0
    except FeedGenerationError as exc:
        print(f"✗ Валидация не пройдена: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
