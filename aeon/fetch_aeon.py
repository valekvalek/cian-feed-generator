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

# rooms: S=студия(9), 1=1к, 2=2к, ...
ROOMS_MAP = {"S": 9, "1": 1, "2": 2, "3": 3, "4": 4}


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
    return int(re.sub(r"\D", "", str(val))) if val else 0


def txt(parent, tag, value):
    el = SubElement(parent, tag)
    el.text = str(value) if value is not None else ""
    return el


def make_aeon_object(lot: dict) -> Element:
    obj = Element("object")

    # ExternalId — обязательное поле ЦИАН
    external_id = lot.get("lotcode") or lot.get("id", "")
    txt(obj, "ExternalId", external_id)
    txt(obj, "Description", f"ЖК {JK_NAME}, этаж {lot.get('floor', '')}, лот {lot.get('num', '')}")
    txt(obj, "Category", "newBuildingFlatSale")
    txt(obj, "Address", ADDRESS)

    rooms_raw = lot.get("rooms", "S")
    rooms = ROOMS_MAP.get(str(rooms_raw), 9)
    txt(obj, "FlatRoomsCount", rooms)
    txt(obj, "TotalArea", lot.get("sq", 0))
    txt(obj, "FloorNumber", lot.get("floor", ""))

    # JKSchema — обязательный блок с name и external_id ЖК
    jk = SubElement(obj, "JKSchema")
    txt(jk, "Id",   JK_CIAN_ID)
    txt(jk, "Name", JK_NAME)
    house = SubElement(jk, "House")
    building = lot.get("building", "1")
    txt(house, "Id",   building)
    txt(house, "Name", building)
    flat_el = SubElement(house, "Flat")
    txt(flat_el, "FlatNumber",    lot.get("num", ""))
    txt(flat_el, "SectionNumber", lot.get("section", ""))

    agent = SubElement(obj, "SubAgent")
    txt(agent, "Email", EMAIL)

    # Планировка
    layout = lot.get("layout", "")
    if layout:
        lp = SubElement(obj, "LayoutPhoto")
        txt(lp, "FullUrl",   BASE_URL + layout if not layout.startswith("http") else layout)
        txt(lp, "PhotoType", "realtyObjectLayout")

    # Корпус / срок сдачи
    bld_el = SubElement(obj, "Building")
    txt(bld_el, "FloorsCount", lot.get("totalfloors", 0) or 0)

    ready_raw = str(lot.get("ready", ""))
    # ready вида "25101" = Q1 2025, "25552" = Q2 2025 и т.д.
    quarter_map = {"1": "first", "2": "second", "3": "third", "4": "fifth"}
    if len(ready_raw) == 5:
        year    = "20" + ready_raw[:2]
        q_digit = ready_raw[2]
        q_str   = quarter_map.get(q_digit, "fourth")
        dl = SubElement(bld_el, "Deadline")
        txt(dl, "Quarter",    q_str)
        txt(dl, "Year",       year)
        txt(dl, "IsComplete", "false")

    # Цена
    bt = SubElement(obj, "BargainTerms")
    txt(bt, "Price",           clean_price(lot.get("real_price", 0)))
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
    objects = []
    skipped = 0
    for lot in lots:
        if not lot.get("real_price") or lot.get("reserved") == "Y":
            skipped += 1
            continue
        objects.append(make_aeon_object(lot))

    print(f"\n✓ В фид: {len(objects)}, пропущено: {skipped}")
    write_feed(objects, "aeon/aeon_riverpark_feed.xml")
    print(f"✅ Готово: aeon/aeon_riverpark_feed.xml ({len(objects)} объектов)")


if __name__ == "__main__":
    main()
