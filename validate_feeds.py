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
    Path("sezar/sezar_city_feed.xml"): 100,
}
SEZAR_FEED = Path("sezar/sezar_city_feed.xml")
SEZAR_LAYOUT_DIR = Path("sezar/layouts")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
FEED_GROUPS = {
    "marusino": (Path("legenda/marusino_feed.xml"),),
    "korenevo": (Path("legenda/korenevo_feed.xml"),),
    "nekrasovka": (Path("legenda/nekrasovka_feed.xml"),),
    "svet": (
        Path("dominanta/svet_feed.xml"),
        Path("dominanta/dominanta_feed.xml"),
    ),
    "aeon": (Path("aeon/aeon_riverpark_feed.xml"),),
    "sezar": (SEZAR_FEED,),
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


def validate_sezar_images(*, require_layout_dir: bool = False) -> None:
    if not SEZAR_LAYOUT_DIR.is_dir():
        if require_layout_dir:
            raise FeedGenerationError(f"{SEZAR_LAYOUT_DIR}: каталог PNG не создан")
        return

    for obj in parse(SEZAR_FEED).getroot().findall("object"):
        external_id = (obj.findtext("ExternalId") or "").strip()
        layout_url = (obj.findtext("LayoutPhoto/FullUrl") or "").strip()
        photo_urls = [
            (photo.findtext("FullUrl") or "").strip()
            for photo in obj.findall("Photos/PhotoSchema")
        ]
        if not layout_url.endswith(".png"):
            raise FeedGenerationError(
                f"{SEZAR_FEED}: ExternalId={external_id}, планировка не в PNG"
            )
        if len(photo_urls) != 2:
            raise FeedGenerationError(
                f"{SEZAR_FEED}: ExternalId={external_id}, "
                f"ожидалось 2 изображения, найдено {len(photo_urls)}"
            )
        if photo_urls[0] != layout_url:
            raise FeedGenerationError(
                f"{SEZAR_FEED}: ExternalId={external_id}, "
                "PNG-планировка отсутствует первой в Photos"
            )
        if photo_urls[1] == layout_url or not photo_urls[1].endswith(".png"):
            raise FeedGenerationError(
                f"{SEZAR_FEED}: ExternalId={external_id}, "
                "второй PNG-план этажа отсутствует в Photos"
            )

        for image_url in photo_urls:
            local_layout = SEZAR_LAYOUT_DIR / image_url.rsplit("/", 1)[-1]
            if not local_layout.is_file():
                raise FeedGenerationError(
                    f"{SEZAR_FEED}: ExternalId={external_id}, отсутствует {local_layout}"
                )
            if local_layout.read_bytes()[: len(PNG_SIGNATURE)] != PNG_SIGNATURE:
                raise FeedGenerationError(
                    f"{SEZAR_FEED}: ExternalId={external_id}, "
                    f"{local_layout} не является PNG"
                )


def validate_group_relationships(group: str) -> None:
    if group == "nekrasovka":
        marusino = external_ids(Path("legenda/marusino_feed.xml"))
        korenevo = external_ids(Path("legenda/korenevo_feed.xml"))
        combined = external_ids(Path("legenda/nekrasovka_feed.xml"))
        if combined != marusino + korenevo:
            raise FeedGenerationError(
                "nekrasovka_feed.xml не равен объединению Марусино и Коренево"
            )

    if group == "svet":
        svet = external_ids(Path("dominanta/svet_feed.xml"))
        dominanta = external_ids(Path("dominanta/dominanta_feed.xml"))
        if dominanta != svet:
            raise FeedGenerationError(
                "dominanta_feed.xml не совпадает с текущим фидом Свет"
            )

    if group == "sezar":
        validate_sezar_images(require_layout_dir=True)


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

    validate_sezar_images()


def validate_legacy_aliases(sources: set[Path] | None = None) -> None:
    for alias, source in LEGACY_ALIASES.items():
        if sources is not None and source not in sources:
            continue
        validate_feed(alias, min_objects=ACTIVE_FEEDS.get(source, 1))
        if digest(alias) != digest(source):
            raise FeedGenerationError(f"Legacy-файл {alias} не синхронизирован с {source}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-legacy", action="store_true")
    parser.add_argument("--only", choices=sorted(FEED_GROUPS))
    parser.add_argument("--only-sezar", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    try:
        selected_group = "sezar" if args.only_sezar else args.only
        if selected_group:
            selected_paths = set(FEED_GROUPS[selected_group])
            total = 0
            for path in FEED_GROUPS[selected_group]:
                count = validate_feed(path, min_objects=ACTIVE_FEEDS[path])
                total += count
                print(f"✓ {path}: {count} объектов")
            validate_group_relationships(selected_group)
            if args.include_legacy:
                validate_legacy_aliases(selected_paths)
                print(f"✓ Legacy-файлы группы {selected_group} синхронизированы")
            print(f"✓ Группа {selected_group}: {total} объектов")
            return 0

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
