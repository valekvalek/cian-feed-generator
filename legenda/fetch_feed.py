#!/usr/bin/env python3
"""
Автоматический генератор XML-фидов для ЦИАН — ГК Некрасовка (Легенда).
Запуск: python legenda/fetch_feed.py

Выходные файлы:
  legenda/nekrasovka_feed.xml — ГК Некрасовка (Легенда Марусино + Легенда Коренево)
  legenda/marusino_feed.xml   — Легенда Марусино
  legenda/korenevo_feed.xml   — Легенда Коренево
"""

import requests
import os
import sys
import re
from datetime import datetime, timezone
from xml.etree.ElementTree import Element, SubElement, ElementTree, indent

# ─── Этажность по корпусам ─────────────────────────────────────────────────
BUILDING_FLOORS = {
    # Легенда Марусино
    "1.1": 7, "1.2": 7, "1.3": 7,
    # Легенда Коренево
    "Корпус 1": 8, "Корпус 2": 8, "Корпус 3": 8,
    "Корпус 4": 8, "Корпус 5": 8,
}
DEFAULT_FLOORS = 8

# ─── Проекты ─────────────────────────────────────────────────────────────────
PROJECTS = [
    {
        "project_id":  "a5f9b6b9-037d-4cd8-981c-cbd55e93a5c0",
        "jk_name":     "Легенда Марусино",
        "jk_cian_id":  os.getenv("CIAN_ID_MARUSINO", "MARUSINO_CIAN_ID"),
        "address":     "Россия, Московская область, Люберцы, Марусино",
        "base_url":    "https://legendamarusino.ru/",
        "api_url":     "https://legendamarusino.ru/api/realty-filter/custom/real-estates",
        "output_file": "legenda/marusino_feed.xml",
        "source":      "legenda",
    },
    {
        "project_id":  "61b193a5-aa22-4f3a-bf22-216ebc5648b1",
        "jk_name":     "Легенда Коренево",
        "jk_cian_id":  os.getenv("CIAN_ID_KORENEVO", "KORENEVO_CIAN_ID"),
        "address":     "Россия, Московская область, Железнодорожный, Коренево",
        "base_url":    "https://legendakorenevo.ru/",
        "api_url":     "https://legendakorenevo.ru/api/realty-filter/custom/real-estates",
        "output_file": "legenda/korenevo_feed.xml",
        "source":      "legenda",
    },
]

PAGE_SIZE = 100
EMAIL     = "info@rusich.group"


# ─── Загрузка Легенда (POST + offset) ────────────────────────────────────────
def fetch_legenda(cfg: dict) -> list:
    flats, offset = [], 0
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    total_fetched = total_skipped = 0

    while True:
        body = {"project_id": cfg["project_id"], "status": ["free"],
                "page_size": PAGE_SIZE, "offset": offset}
        try:
            resp = requests.post(cfg["api_url"], json=body, headers=headers, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  ⚠ ({cfg['jk_name']} offset={offset}): {e}", file=sys.stderr)
            break

        data = resp.json()
        batch = data if isinstance(data, list) else (
            data.get("results") or data.get("items") or data.get("data") or [])
        if not batch:
            break

        total_fetched += len(batch)
        valid = [f for f in batch
                 if f.get("status") == "free" and f.get("price") not in (None, 0, "")]
        total_skipped += len(batch) - len(valid)
        flats.extend(valid)
        print(f"   offset={offset}: +{len(batch)}, в фид {len(valid)}, итого {len(flats)}")

        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    print(f"   → загружено {total_fetched}, пропущено {total_skipped}, в фид: {len(flats)}")
    return flats


# ─── XML-утилиты ─────────────────────────────────────────────────────────────
def quarter_str(q) -> str:
    return {"1": "first", "2": "second", "3": "third", "4": "fourth",
            1: "first",   2: "second",   3: "third",   4: "fourth"}.get(str(q), "fourth")

def txt(parent, tag, value):
    el = SubElement(parent, tag)
    el.text = str(value) if value is not None else ""
    return el

def clean_price(val) -> int:
    return int(re.sub(r"\D", "", str(val))) if val else 0

def abs_url(path: str, base_url: str) -> str:
    if not path:
        return ""
    if path.startswith("http"):
        return path
    base = base_url.rstrip("/")
    path = path.lstrip("/")
    return f"{base}/{path}"


# ─ Легенда ───────────────────────────────────────────────────────────────────
def make_legenda_object(flat: dict, cfg: dict) -> Element:
    obj = Element("object")
    rooms = flat.get("rooms", 0)
    if not rooms or int(rooms) == 0:
        rooms = 9

    txt(obj, "ExternalId",       flat.get("external_id", ""))
    txt(obj, "Description",      f"ЖК {cfg['jk_name']}, этаж {flat.get('floor_number', '')}, номер квартиры {flat.get('number', '')}")
    txt(obj, "Category",         "newBuildingFlatSale")
    txt(obj, "FlatOnFloorNumber", flat.get("axis", ""))
    txt(obj, "Address",          cfg["address"])
    txt(obj, "FlatRoomsCount",   rooms)
    txt(obj, "TotalArea",        flat.get("total_area", 0))
    txt(obj, "LivingArea",       flat.get("living_area", 0))
    txt(obj, "KitchenArea",      flat.get("kitchen_area", 0))
    txt(obj, "FloorNumber",      flat.get("floor_number", ""))

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

    agent = SubElement(obj, "SubAgent")
    txt(agent, "Email", EMAIL)

    plan_path = (flat.get("plan") or flat.get("floor_plan") or flat.get("layout_plan") or "")
    plan_url = abs_url(plan_path, cfg["base_url"])
    if plan_url:
        lp = SubElement(obj, "LayoutPhoto")
        txt(lp, "FullUrl",   plan_url)
        txt(lp, "PhotoType", "realtyObjectLayout")

    photo_urls = []
    for img in flat.get("images", []):
        u = abs_url(img.get("url") or img.get("full_url") or "", cfg["base_url"])
        if u:
            photo_urls.append(u)
    if not photo_urls:
        for field in ("building_render", "genplan"):
            u = abs_url(flat.get(field, ""), cfg["base_url"])
            if u:
                photo_urls.append(u)
    if photo_urls:
        photos = SubElement(obj, "Photos")
        for u in photo_urls:
            ps = SubElement(photos, "PhotoSchema")
            txt(ps, "FullUrl",   u)
            txt(ps, "PhotoType", "realtyObject")

    building = SubElement(obj, "Building")
    floors_count = BUILDING_FLOORS.get(str(bld), DEFAULT_FLOORS)
    txt(building, "FloorsCount", floors_count)

    q  = flat.get("completion_quarter")
    yr = flat.get("completion_year")
    if q and yr:
        dl = SubElement(building, "Deadline")
        txt(dl, "Quarter",    quarter_str(q))
        txt(dl, "Year",       yr)
        txt(dl, "IsComplete", "true" if flat.get("is_ready") else "false")

    bt = SubElement(obj, "BargainTerms")
    txt(bt, "Price",           int(flat.get("price", 0)))
    txt(bt, "Currency",        "rur")
    txt(bt, "MortgageAllowed", "true")
    return obj


# ─── Запись фида ─────────────────────────────────────────────────────────────
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
    size = os.path.getsize(output_file)
    print(f"   💾 {output_file} ({size:,} байт)")


# ─── main ─────────────────────────────────────────────────────────────────────
def main():
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    nekrasovka_objects = []

    for cfg in PROJECTS:
        print(f"\n📥 Загрузка {cfg['jk_name']}...")
        flats   = fetch_legenda(cfg)
        objects = [make_legenda_object(f, cfg) for f in flats]
        print(f"   ✓ В фид: {len(objects)} квартир")
        write_feed(objects, cfg["output_file"])
        nekrasovka_objects.extend(objects)

    write_feed(nekrasovka_objects, "legenda/nekrasovka_feed.xml")

    print(f"\n✅ [{ts}] Готово:")
    print(f"   ГК Некрасовка → legenda/nekrasovka_feed.xml ({len(nekrasovka_objects)} объектов)")


if __name__ == "__main__":
    main()
