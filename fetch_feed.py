#!/usr/bin/env python3
"""
Автоматический генератор XML-фида для ЦИАН.
API-особенности: POST, offset-пагинация, page_size макс. 100.
API игнорирует status-фильтр — фильтруем локально: status==free и price != None.
Запуск: python fetch_feed.py
"""

import requests
import os
import sys
from datetime import datetime, timezone
from xml.etree.ElementTree import Element, SubElement, ElementTree, indent

# ─── Конфигурация ───────────────────────────────────────────────────────────
PROJECTS = [
    {
        "project_id": "a5f9b6b9-037d-4cd8-981c-cbd55e93a5c0",
        "jk_name":    "Легенда Марусино",
        "jk_cian_id": os.getenv("CIAN_ID_MARUSINO", "MARUSINO_CIAN_ID"),
        "address":    "Россия, Московская область, Люберцы, Марусино",
        "base_url":   "https://legendamarusino.ru/",
        "api_url":    "https://legendamarusino.ru/api/realty-filter/custom/real-estates",
    },
    {
        "project_id": "61b193a5-aa22-4f3a-bf22-216ebc5648b1",
        "jk_name":    "Легенда Коренево",
        "jk_cian_id": os.getenv("CIAN_ID_KORENEVO", "KORENEVO_CIAN_ID"),
        "address":    "Россия, Московская область, Железнодорожный, Коренево",
        "base_url":   "https://legendakorenevo.ru/",
        "api_url":    "https://legendakorenevo.ru/api/realty-filter/custom/real-estates",
    },
]

PAGE_SIZE   = 100
OUTPUT_FILE = "cian_feed.xml"
EMAIL       = "info@rusich.group"


# ─── Загрузка данных ───────────────────────────────────────────────────────────
def fetch_all_flats(cfg: dict) -> list:
    flats  = []
    offset = 0
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    total_fetched = 0
    total_skipped = 0

    while True:
        body = {
            "project_id": cfg["project_id"],
            "status":     ["free"],
            "page_size":  PAGE_SIZE,
            "offset":     offset,
        }
        try:
            resp = requests.post(cfg["api_url"], json=body, headers=headers, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  ⚠ Ошибка ({cfg['jk_name']} offset={offset}): {e}", file=sys.stderr)
            break

        data = resp.json()
        batch = data if isinstance(data, list) else (
            data.get("results") or data.get("items") or data.get("data") or []
        )

        if not batch:
            break

        total_fetched += len(batch)
        valid = [
            f for f in batch
            if f.get("status") == "free" and f.get("price") not in (None, 0, "")
        ]
        skipped = len(batch) - len(valid)
        total_skipped += skipped
        flats.extend(valid)
        print(f"   offset={offset}: +{len(batch)} загр., в фид {len(valid)} (пропущено {skipped}), итого {len(flats)}")

        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    print(f"   → загружено {total_fetched}, пропущено {total_skipped}, в фид: {len(flats)}")
    return flats


# ─── Сборка XML-объекта ───────────────────────────────────────────────────────
def quarter_str(q: int) -> str:
    return {1: "first", 2: "second", 3: "third", 4: "fourth"}.get(q, "fourth")


def txt(parent: Element, tag: str, value) -> Element:
    """SubElement с текстом, пропускает None."""
    el = SubElement(parent, tag)
    el.text = str(value) if value is not None else ""
    return el


def make_object_element(flat: dict, cfg: dict) -> Element:
    obj = Element("object")

    txt(obj, "ExternalId",       flat.get("external_id", ""))
    txt(obj, "Description",      f"ЖК {cfg['jk_name']}, этаж {flat.get('floor_number', '')}, номер квартиры {flat.get('number', '')}")
    txt(obj, "Category",         "newBuildingFlatSale")
    txt(obj, "FlatOnFloorNumber", flat.get("axis", ""))
    txt(obj, "Address",          cfg["address"])
    txt(obj, "FlatRoomsCount",   flat.get("rooms", 0))
    txt(obj, "TotalArea",        flat.get("total_area", 0))
    txt(obj, "LivingArea",       flat.get("living_area", 0))
    txt(obj, "KitchenArea",      flat.get("kitchen_area", 0))
    txt(obj, "FloorNumber",      flat.get("floor_number", ""))

    # JKSchema
    jk = SubElement(obj, "JKSchema")
    txt(jk, "Id",   cfg["jk_cian_id"])
    txt(jk, "Name", cfg["jk_name"])
    house = SubElement(jk, "House")
    bld = flat.get("building_number", "")
    txt(house, "Id",   bld)
    txt(house, "Name", bld)
    flat_el = SubElement(house, "Flat")
    txt(flat_el, "FlatNumber",    flat.get("number", ""))
    txt(flat_el, "SectionNumber", flat.get("section_number", ""))

    # SubAgent
    agent = SubElement(obj, "SubAgent")
    txt(agent, "Email", EMAIL)

    # LayoutPhoto
    plan = flat.get("plan") or flat.get("layout_plan", "")
    if plan:
        url = plan if plan.startswith("http") else cfg["base_url"] + plan
        lp = SubElement(obj, "LayoutPhoto")
        txt(lp, "FullUrl",   url)
        txt(lp, "PhotoType", "realtyObjectLayout")

    # Photos
    images = flat.get("images", [])
    if images:
        photos = SubElement(obj, "Photos")
        for img in images:
            u = img.get("url") or img.get("full_url", "")
            if u:
                ps = SubElement(photos, "PhotoSchema")
                txt(ps, "FullUrl",   u)
                txt(ps, "PhotoType", "realtyObject")

    # Building / Deadline
    building = SubElement(obj, "Building")
    q  = flat.get("completion_quarter")
    yr = flat.get("completion_year")
    if q and yr:
        dl = SubElement(building, "Deadline")
        txt(dl, "Quarter",    quarter_str(q))
        txt(dl, "Year",       yr)
        txt(dl, "IsComplete", "true" if flat.get("is_ready") else "false")

    # BargainTerms
    bt = SubElement(obj, "BargainTerms")
    txt(bt, "Price",           int(flat.get("price", 0)))
    txt(bt, "Currency",        "rur")
    txt(bt, "MortgageAllowed", "true")

    return obj


# ─── Главный блок ─────────────────────────────────────────────────────────────
def main():
    root = Element("feed")
    txt(root, "feed_version", "2")
    txt(root, "generated", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    total_objects = 0
    for cfg in PROJECTS:
        print(f"\n📥 Загрузка {cfg['jk_name']}...")
        flats = fetch_all_flats(cfg)
        print(f"   ✓ В фид: {len(flats)} квартир")
        for flat in flats:
            root.append(make_object_element(flat, cfg))
            total_objects += 1

    # Красивые отступы (indent доступен с Python 3.9+)
    indent(root, space="  ")

    tree = ElementTree(root)
    with open(OUTPUT_FILE, "wb") as f:
        tree.write(f, encoding="utf-8", xml_declaration=True)

    size = os.path.getsize(OUTPUT_FILE)
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n✅ [{ts}] Готово: {total_objects} объектов → {OUTPUT_FILE} ({size:,} байт)")


if __name__ == "__main__":
    main()
