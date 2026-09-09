#!/usr/bin/env python3
"""
Генератор XML-фида для ЦИАН — Aeon (Ривер Парк Бизнес).
Запуск: python aeon/fetch_aeon.py

Выходной файл:
  aeon/aeon_riverpark_feed.xml
"""

import re
import time
from collections import Counter
from datetime import datetime, timezone
from xml.etree.ElementTree import Element, SubElement

from feed_common import (
    FeedGenerationError,
    add_text,
    build_http_session,
    parse_price,
    request_json,
    require_cian_id,
    write_feed_atomic,
)

BASE_URL   = "https://river-park.ru"
API_URL    = f"{BASE_URL}/ajax/flats/"
JK_NAME    = "Ривер Парк Бизнес"
ADDRESS    = "Россия, Москва, Коломенская набережная"
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

# Соответствие по регламенту ЦИАН:
# 1-4 — количество комнат
# 6   — многокомнатная (более 5 комнат)
# 7   — свободная планировка
# 9   — студия
# S/M/L в API — размерные классы апартаментов. Поле roomreal для них содержит
# варианты 0/1e/1, поэтому точное число комнат из API определить нельзя.
FREE_LAYOUT_CODES = {"S", "M", "L"}
ROOMS_MAP = {"0": 9, "1": 1, "2": 2, "3": 3, "4": 4, "6": 6, "7": 7, "9": 9}
ALLOWED_ARTICLE_TYPES = {"квартира"}
ALLOWED_ARTICLE_SUBTYPES = {"апартаменты", "квартира"}
KNOWN_COMPLETE_BUILDINGS = {"4", "7", "12", "14"}

# Этажность по корпусам — по максимальному доступному этажу из API
BUILDING_FLOORS = {
    "7":  12,
    "12": 13,
    "14": 13,
}
DEFAULT_FLOORS = 13  # fallback для неизвестных корпусов


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


def parse_deadline(ready_raw: str) -> dict | None:
    """
    Разбирает подтверждённые форматы срока сдачи.

    API сейчас возвращает внутренние коды вида YYQNN. Квартал можно извлекать
    только когда третий символ находится в диапазоне 1..4, например 25101.
    Также поддерживаются явные значения 25Q4 и 2025Q4. Коды 25552/25099 не
    интерпретируются: придумывать для них квартал опаснее, чем опустить Deadline.
    """
    quarter_map = {"1": "first", "2": "second", "3": "third", "4": "fourth"}
    s = str(ready_raw).strip()
    explicit = re.fullmatch(r"(?:20)?(?P<year>\d{2})Q(?P<quarter>[1-4])", s, re.I)
    internal = re.fullmatch(r"(?P<year>\d{2})(?P<quarter>[1-4])\d{2}", s)
    match = explicit or internal
    if match:
        return {
            "quarter": quarter_map[match.group("quarter")],
            "year": "20" + match.group("year"),
        }
    return None


def map_rooms(rooms_raw) -> int:
    code = str(rooms_raw).strip().upper()
    if code in FREE_LAYOUT_CODES:
        return 7
    if code in ROOMS_MAP:
        return ROOMS_MAP[code]
    raise FeedGenerationError(f"Aeon: неизвестный тип комнат {rooms_raw!r}")


def map_category(lot: dict) -> str:
    article_type = str(lot.get("articletype", "")).strip().casefold()
    article_subtype = str(lot.get("articlesubtype", "")).strip().casefold()
    if article_type not in ALLOWED_ARTICLE_TYPES:
        raise FeedGenerationError(f"Aeon: неподдерживаемый тип объекта {article_type!r}")
    if article_subtype not in ALLOWED_ARTICLE_SUBTYPES:
        raise FeedGenerationError(f"Aeon: неподдерживаемый подтип объекта {article_subtype!r}")
    return "newBuildingFlatSale"


def make_aeon_object(lot: dict, cian_id: str, warnings: Counter) -> Element:
    obj = Element("object")

    external_id = lot.get("lotcode") or lot.get("id", "")
    txt(obj, "ExternalId", external_id)
    txt(obj, "Description", f"ЖК {JK_NAME}, этаж {lot.get('floor', '')}, лот {lot.get('num', '')}")
    txt(obj, "Category", map_category(lot))
    txt(obj, "Address", ADDRESS)

    txt(obj, "FlatRoomsCount", map_rooms(lot.get("rooms")))
    txt(obj, "TotalArea", lot.get("sq", 0))
    txt(obj, "FloorNumber", lot.get("floor", ""))

    jk = SubElement(obj, "JKSchema")
    txt(jk, "Id",   cian_id)
    txt(jk, "Name", JK_NAME)
    house = SubElement(jk, "House")
    building = str(lot.get("building", ""))
    txt(house, "Id",   building)
    txt(house, "Name", building)
    flat_el = SubElement(house, "Flat")
    txt(flat_el, "FlatNumber",    lot.get("num", ""))
    txt(flat_el, "SectionNumber", lot.get("section", ""))

    agent = SubElement(obj, "SubAgent")
    txt(agent, "Email", EMAIL)

    layout = lot.get("layout", "")
    if layout:
        lp = SubElement(obj, "LayoutPhoto")
        txt(lp, "FullUrl",   BASE_URL + layout if not layout.startswith("http") else layout)
        txt(lp, "PhotoType", "realtyObjectLayout")

    bld_el = SubElement(obj, "Building")

    floors = BUILDING_FLOORS.get(building, DEFAULT_FLOORS)
    txt(bld_el, "FloorsCount", floors)

    ready_raw = lot.get("ready", "")
    deadline = parse_deadline(ready_raw)
    if deadline:
        dl = SubElement(bld_el, "Deadline")
        txt(dl, "Quarter",    deadline["quarter"])
        txt(dl, "Year",       deadline["year"])
        txt(dl, "IsComplete", "true" if building in KNOWN_COMPLETE_BUILDINGS else "false")
    else:
        warnings[str(ready_raw)] += 1

    price = parse_price(lot.get("real_price"))

    bt = SubElement(obj, "BargainTerms")
    txt(bt, "Price",           price)
    txt(bt, "Currency",        "rur")
    txt(bt, "MortgageAllowed", "true")

    return obj


def main():
    cian_id = require_cian_id("CIAN_ID_AEON")
    lots = fetch_all_lots()
    objects  = []
    skipped  = 0
    warnings: Counter = Counter()

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

        objects.append(make_aeon_object(lot, cian_id, warnings))

    print(f"\n✓ В фид: {len(objects)}, пропущено: {skipped}")

    if warnings:
        print(f"\n⚠️  Нераспознанные коды ready ({sum(warnings.values())} лотов):")
        for code, count in sorted(warnings.items()):
            print(f"   ready={code!r}: {count}")

    write_feed_atomic(
        objects,
        "aeon/aeon_riverpark_feed.xml",
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        min_objects=20,
    )
    print(f"\n✅ Готово: aeon/aeon_riverpark_feed.xml ({len(objects)} объектов)")


if __name__ == "__main__":
    main()
