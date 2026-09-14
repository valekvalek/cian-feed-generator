#!/usr/bin/env python3
"""
Генератор XML-фида для ЦИАН — Aeon (Ривер Парк Бизнес).
Запуск: python aeon/fetch_aeon.py

Выходной файл:
  aeon/aeon_riverpark_feed.xml
"""

import time
from datetime import datetime, timezone
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement

from feed_common import (
    FeedGenerationError,
    add_text,
    build_http_session,
    parse_price,
    request_json,
    write_feed_atomic,
)
from feed_media import add_two_feed_images, prepare_media_images

BASE_URL   = "https://river-park.ru"
API_URL    = f"{BASE_URL}/ajax/flats/"
JK_NAME    = "Ривер Парк Бизнес"
EMAIL      = "info@rusich.group"

PARAMS_BASE = {
    "cnt": 30,
    "filter[project]": "Riverpark",
    "filter[special]": "",
    "filter[type]": "",
    "filter[bld]": "",
    "filter[offers]": "",
    "filter[finishing]": 0,
    "sort[sec]": 0,
    "sort[name]": 0,
    "sort[sq]": 0,
    "sort[price]": 1,
    "sort[rooms]": 0,
    "sort[floor]": 0,
    "art_code": "flat",
}
HEADERS = {"User-Agent": "Mozilla/5.0"}

# Все лоты этого фида публикуются в коммерческой категории «помещение свободного
# назначения», включая остаточные лоты корпуса 4 с числовым полем rooms.
COMMERCIAL_CATEGORY = "freeAppointmentObjectSale"
ALLOWED_ARTICLE_TYPES = {"квартира"}
ALLOWED_ARTICLE_SUBTYPES = {"апартаменты", "квартира"}

# Этажность по корпусам — по максимальному доступному этажу из API
BUILDING_FLOORS = {
    "4":  19,
    "7":  12,
    "12": 13,
    "14": 13,
}
DEFAULT_FLOORS = 13  # fallback для неизвестных корпусов

# Фактические адреса введённых в эксплуатацию коммерческих корпусов.
COMMERCIAL_BUILDING_ADDRESSES = {
    "4": "Россия, Москва, улица Корабельная, 1",
    "7": "Россия, Москва, улица Корабельная, 7",
    "12": "Россия, Москва, улица Корабельная, 2",
    "14": "Россия, Москва, улица Корабельная, 5",
}


def fetch_all_lots(session=None) -> list:
    """
    Загружает все лоты постранично.
    Пагинация через while-loop: грузим страницы пока API возвращает непустой data.
    Не используем count/30 — count может быть количеством на странице, а не общим.
    """
    all_lots = []
    page = 1
    MAX_PAGES = 50  # защита от бесконечного цикла
    session = session or build_http_session()
    seen_pages: set[tuple] = set()

    while page <= MAX_PAGES:
        p = dict(PARAMS_BASE, page=page)
        data = request_json(session, "GET", API_URL, params=p, headers=HEADERS)
        if not isinstance(data, dict):
            raise FeedGenerationError(f"Aeon: API вернул {type(data).__name__} вместо объекта")

        lots = data.get("data", [])
        if not isinstance(lots, list):
            raise FeedGenerationError("Aeon: поле data не является списком")

        # Логируем total только на первой странице (информационно)
        if page == 1:
            total = data.get("count", "?")
            print(f"API count (на странице или всего): {total}")

        if not lots:
            print(f"  стр {page}: пустой ответ — остановка")
            break

        page_key = tuple(str(item.get("lotcode") or item.get("id")) for item in lots)
        if page_key in seen_pages:
            raise FeedGenerationError(f"Aeon: API повторил страницу {page}")
        seen_pages.add(page_key)

        all_lots.extend(lots)
        print(f"  стр {page}: +{len(lots)}, итого {len(all_lots)}")

        # Если страница неполная — это последняя
        if len(lots) < PARAMS_BASE["cnt"]:
            print(f"  стр {page}: страница неполная ({len(lots)} < {PARAMS_BASE['cnt']}) — остановка")
            break

        page += 1
        time.sleep(0.3)

    print(f"Загружено лотов: {len(all_lots)}")
    return all_lots


def txt(parent, tag, value):
    return add_text(parent, tag, value)


def map_category(lot: dict) -> str:
    article_type = str(lot.get("articletype", "")).strip().casefold()
    article_subtype = str(lot.get("articlesubtype", "")).strip().casefold()
    if article_type not in ALLOWED_ARTICLE_TYPES:
        raise FeedGenerationError(f"Aeon: неподдерживаемый тип объекта {article_type!r}")
    if article_subtype not in ALLOWED_ARTICLE_SUBTYPES:
        raise FeedGenerationError(f"Aeon: неподдерживаемый подтип объекта {article_subtype!r}")
    return COMMERCIAL_CATEGORY


def object_address(lot: dict) -> str:
    building = str(lot.get("building", "")).strip()
    try:
        return COMMERCIAL_BUILDING_ADDRESSES[building]
    except KeyError as exc:
        raise FeedGenerationError(
            f"Aeon: неизвестный адрес коммерческого корпуса {building!r}"
        ) from exc


def aeon_image_sources(lot: dict) -> tuple[str, str]:
    def absolute(value) -> str:
        url = str(value or "").strip()
        return url if url.startswith("http") else BASE_URL.rstrip("/") + "/" + url.lstrip("/")

    layout_url = absolute(lot.get("layout"))
    floor_card_url = absolute(lot.get("plan"))
    if not lot.get("layout") or not lot.get("plan"):
        raise FeedGenerationError(
            f"Aeon: у лота {lot.get('lotcode') or lot.get('id')} нет двух планов"
        )
    if layout_url == floor_card_url:
        raise FeedGenerationError(
            f"Aeon: у лота {lot.get('lotcode') or lot.get('id')} планы совпадают"
        )
    return layout_url, floor_card_url


def make_aeon_object(
    lot: dict,
    layout_url: str,
    floor_card_url: str,
) -> Element:
    obj = Element("object")

    external_id = lot.get("lotcode") or lot.get("id", "")
    category = map_category(lot)
    txt(obj, "ExternalId", external_id)
    txt(
        obj,
        "Description",
        f"Помещение свободного назначения, корпус {lot.get('building', '')}, "
        f"этаж {lot.get('floor', '')}, лот {lot.get('num', '')}",
    )
    txt(obj, "Category", category)
    txt(obj, "Address", object_address(lot))

    txt(obj, "TotalArea", lot.get("sq", 0))
    txt(obj, "FloorNumber", lot.get("floor", ""))
    txt(obj, "Layout", "openSpace")

    building = str(lot.get("building", ""))

    agent = SubElement(obj, "SubAgent")
    txt(agent, "Email", EMAIL)

    add_two_feed_images(
        obj,
        layout_url,
        floor_card_url,
        label=f"Aeon / {external_id}",
    )

    bld_el = SubElement(obj, "Building")

    floors = BUILDING_FLOORS.get(building, DEFAULT_FLOORS)
    txt(bld_el, "Name", f"Ривер Парк Бизнес, корпус {building}")
    txt(bld_el, "FloorsCount", floors)
    txt(bld_el, "Type", "businessCenter")
    txt(bld_el, "StatusType", "operational")

    price = parse_price(lot.get("real_price"))

    bt = SubElement(obj, "BargainTerms")
    txt(bt, "Price",           price)
    txt(bt, "PriceType", "all")
    txt(bt, "Currency",        "rur")
    tax = SubElement(bt, "Tax")
    txt(tax, "Type", "vat")
    txt(tax, "Rate", "22")
    txt(tax, "IncludedInPrice", "true")

    return obj


def main():
    lots = fetch_all_lots()
    valid_lots = []
    skipped  = 0

    for lot in lots:
        lot_id = lot.get("lotcode") or lot.get("id", "?")

        # Пропускаем зарезервированные
        if lot.get("reserved") == "Y":
            skipped += 1
            print(f"  [SKIP] Лот {lot_id}: зарезервирован")
            continue

        # Пропускаем только если цена реально отсутствует (None/пусто)
        # Лоты с price=0 включаем, но фиксируем предупреждение
        if lot.get("real_price") is None or str(lot.get("real_price", "")).strip() == "":
            skipped += 1
            print(f"  [SKIP] Лот {lot_id}: цена отсутствует (None/пусто)")
            continue

        valid_lots.append(lot)

    source_pairs = [aeon_image_sources(lot) for lot in valid_lots]
    layout_dir = Path(__file__).resolve().parent / "layouts"
    public_base_url = (
        "https://raw.githubusercontent.com/valekvalek/"
        "cian-feed-generator/main/aeon/layouts"
    )
    image_urls = prepare_media_images(
        (url for pair in source_pairs for url in pair),
        layout_dir,
        public_base_url,
        label="River Park изображения",
    )
    objects = [
        make_aeon_object(
            lot,
            image_urls[pair[0]],
            image_urls[pair[1]],
        )
        for lot, pair in zip(valid_lots, source_pairs)
    ]

    print(f"\n✓ В фид: {len(objects)}, пропущено: {skipped}")

    write_feed_atomic(
        objects,
        "aeon/aeon_riverpark_feed.xml",
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        min_objects=20,
    )
    print(f"\n✅ Готово: aeon/aeon_riverpark_feed.xml ({len(objects)} объектов)")


if __name__ == "__main__":
    main()
