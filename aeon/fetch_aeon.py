#!/usr/bin/env python3
"""
Генератор XML-фида для ЦИАН — Aeon (Ривер Парк Бизнес).
Запуск: python aeon/fetch_aeon.py

Выходной файл:
  aeon/aeon_riverpark_feed.xml
"""

import requests
import math
import os
import re
import time
from datetime import datetime, timezone
from xml.etree.ElementTree import Element, SubElement, ElementTree, indent

BASE_URL   = "https://river-park.ru"
API_URL    = f"{BASE_URL}/ajax/flats/"
JK_NAME    = "Ривер Парк Бизнес"
JK_CIAN_ID = os.getenv("CIAN_ID_AEON", "AEON_CIAN_ID")
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
ROOMS_MAP = {"S": 7, "1": 1, "2": 2, "3": 3, "4": 4}

# Этажность по корпусам — по максимальному доступному этажу из API
BUILDING_FLOORS = {
    "7":  12,
    "12": 13,
    "14": 13,
}
DEFAULT_FLOORS = 13  # fallback для неизвестных корпусов


def fetch_all_lots() -> list:
    p    = dict(PARAMS_BASE, page=1)
    r    = requests.get(API_URL, params=p, headers=HEADERS, timeout=30)
    data = r.json()
    count = data.get("count", 0)
    pages = math.ceil(count / 30)
    print(f"Всего лотов: {count}, страниц: {pages}")
    all_lots = data.get("data", [])
    for page in range(2, pages + 1):
        p    = dict(PARAMS_BASE, page=page)
        r    = requests.get(API_URL, params=p, headers=HEADERS, timeout=30)
        lots = r.json().get("data", [])
        all_lots.extend(lots)
        print(f"  стр {page}: +{len(lots)}, итого {len(all_lots)}")
        time.sleep(0.3)
    return all_lots


def clean_price(val) -> int:
    if val is None:
        return 0
    cleaned = re.sub(r"\D", "", str(val))
    return int(cleaned) if cleaned else 0


def txt(parent, tag, value):
    el = SubElement(parent, tag)
    el.text = str(value) if value is not None else ""
    return el


def parse_deadline(ready_raw: str) -> dict | None:
    """
    Разбирает поле ready из API.
    Ожидаемый формат: 5 символов, например '251Q4' → год 2025, квартал 4.
    Возвращает dict с ключами quarter, year или None если формат не распознан.
    """
    quarter_map = {"1": "first", "2": "second", "3": "third", "4": "fourth"}
    s = str(ready_raw).strip()
    if len(s) == 5:
        year    = "20" + s[:2]
        q_digit = s[2]
        q_str   = quarter_map.get(q_digit)
        if q_str and year.isdigit():
            return {"quarter": q_str, "year": year}
    return None


def make_aeon_object(lot: dict, warnings: list) -> Element:
    obj = Element("object")

    external_id = lot.get("lotcode") or lot.get("id", "")
    txt(obj, "ExternalId", external_id)
    txt(obj, "Description", f"ЖК {JK_NAME}, этаж {lot.get('floor', '')}, лот {lot.get('num', '')}")
    txt(obj, "Category", "newBuildingFlatSale")
    txt(obj, "Address", ADDRESS)

    rooms_raw = lot.get("rooms", "S")
    rooms = ROOMS_MAP.get(str(rooms_raw))
    if rooms is None:
        warnings.append(f"[WARN] Лот {external_id}: неизвестный тип комнат '{rooms_raw}', подставляем 7 (свободная планировка)")
        rooms = 7
    txt(obj, "FlatRoomsCount", rooms)
    txt(obj, "TotalArea", lot.get("sq", 0))
    txt(obj, "FloorNumber", lot.get("floor", ""))

    jk = SubElement(obj, "JKSchema")
    txt(jk, "Id",   JK_CIAN_ID)
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
        txt(dl, "IsComplete", "false")
    else:
        warnings.append(f"[WARN] Лот {external_id}: поле ready='{ready_raw}' не распознано, блок Deadline не добавлен")

    price = clean_price(lot.get("real_price", 0))
    if price <= 0:
        warnings.append(f"[WARN] Лот {external_id}: цена равна 0 или отсутствует, лот всё равно включён в фид")

    bt = SubElement(obj, "BargainTerms")
    txt(bt, "Price",           price)
    txt(bt, "Currency",        "rur")
    txt(bt, "MortgageAllowed", "true")

    return obj


def write_feed(objects: list, output_file: str):
    root = Element("feed")
    txt(root, "feed_version", "2")
    txt(root, "generated", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    for o in objects:
        root.append(o)
    indent(root, space="  ")
    tree = ElementTree(root)
    with open(output_file, "wb") as f:
        tree.write(f, encoding="utf-8", xml_declaration=True)
    import os as _os
    size = _os.path.getsize(output_file)
    print(f"   💾 {output_file} ({size:,} байт)")


def main():
    lots = fetch_all_lots()
    objects  = []
    skipped  = 0
    warnings = []

    for lot in lots:
        price = clean_price(lot.get("real_price", 0))
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

        objects.append(make_aeon_object(lot, warnings))

    print(f"\n✓ В фид: {len(objects)}, пропущено: {skipped}")

    if warnings:
        print(f"\n⚠️  Предупреждения ({len(warnings)}):")
        for w in warnings:
            print(" ", w)

    write_feed(objects, "aeon/aeon_riverpark_feed.xml")
    print(f"\n✅ Готово: aeon/aeon_riverpark_feed.xml ({len(objects)} объектов)")


if __name__ == "__main__":
    main()
