#!/usr/bin/env python3
"""
Автоматический генератор XML-фидов для ЦИАН.
Запуск: python fetch_feed.py

Выходные файлы:
  cian_feed.xml      — общий фид (все ЖК)
  marusino_feed.xml  — Легенда Марусино
  korenevo_feed.xml  — Легенда Коренево
  svet_feed.xml      — Свет (Dominanta)
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

# ─── Проекты (Легенда) ───────────────────────────────────────────────────
PROJECTS = [
    {
        "project_id":  "a5f9b6b9-037d-4cd8-981c-cbd55e93a5c0",
        "jk_name":     "Легенда Марусино",
        "jk_cian_id":  os.getenv("CIAN_ID_MARUSINO", "MARUSINO_CIAN_ID"),
        "address":     "Россия, Московская область, Люберцы, Марусино",
        "base_url":    "https://legendamarusino.ru/",
        "api_url":     "https://legendamarusino.ru/api/realty-filter/custom/real-estates",
        "output_file": "marusino_feed.xml",
        "source":      "legenda",
    },
    {
        "project_id":  "61b193a5-aa22-4f3a-bf22-216ebc5648b1",
        "jk_name":     "Легенда Коренево",
        "jk_cian_id":  os.getenv("CIAN_ID_KORENEVO", "KORENEVO_CIAN_ID"),
        "address":     "Россия, Московская область, Железнодорожный, Коренево",
        "base_url":    "https://legendakorenevo.ru/",
        "api_url":     "https://legendakorenevo.ru/api/realty-filter/custom/real-estates",
        "output_file": "korenevo_feed.xml",
        "source":      "legenda",
    },
    {
        "jk_name":     "Свет",
        "jk_cian_id":  os.getenv("CIAN_ID_SVET", "SVET_CIAN_ID"),
        "address":     "Россия, Москва",
        "base_url":    "https://d-a.ru",
        "api_url":     "https://d-a.ru/ajax/flats/",
        "project_code": "svet",
        "output_file": "svet_feed.xml",
        "source":      "dominanta",
    },
]

PAGE_SIZE = 100
EMAIL     = "info@rusich.group"


# ─── Загрузка Легенда (POST + offset) ───────────────────────────────────
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


# ─── Загрузка Dominanta (GET + page) ──────────────────────────────────────
def fetch_dominanta(cfg: dict) -> list:
    flats = []
    page  = 1
    cnt   = 50
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://d-a.ru/projects/residential/svet/choose/",
    }

    while True:
        params = {
            "filter[price][0]": "0",
            "filter[price][1]": "0",
            "filter[sq][0]": "0",
            "filter[sq][1]": "0",
            "filter[profile]": "Жилая",
            "filter[project_code]": cfg["project_code"],
            "filter[hide_reserved][0]": "Y",
            "sort[price]": "1",
            "page": str(page),
            "cnt": str(cnt),
        }
        try:
            resp = requests.get(cfg["api_url"], params=params, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  ⚠ ({cfg['jk_name']} page={page}): {e}", file=sys.stderr)
            break

        if isinstance(data, list):
            batch = data
        elif isinstance(data, dict):
            batch = (data.get("items") or data.get("data") or
                     data.get("flats") or data.get("results") or [])
        else:
            break

        if not batch:
            break

        valid = [f for f in batch if f.get("reserved", "Y") == "N"
                 and f.get("real_price") not in (None, "", "0", 0)]
        flats.extend(valid)
        print(f"   page={page}: +{len(batch)}, в фид {len(valid)}, итого {len(flats)}")

        if len(batch) < cnt:
            break
        page += 1

    print(f"   → в фид: {len(flats)}")
    return flats


# ─── XML ──────────────────────────────────────────────────────────────────────
def quarter_str(q) -> str:
    return {"1": "first", "2": "second", "3": "third", "4": "fourth",
            1: "first",   2: "second",   3: "third",   4: "fourth"}.get(str(q), "fourth")

def txt(parent, tag, value):
    el = SubElement(parent, tag)
    el.text = str(value) if value is not None else ""
    return el

def clean_price(val) -> int:
    "'17 418 321' → 17418321"
    return int(re.sub(r"\D", "", str(val))) if val else 0

def abs_url(path: str, base_url: str) -> str:
    """Превращает относительный путь в абсолютный URL."""
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

    # ─ LayoutPhoto: plan → floor_plan → layout_plan ──────────────────────────
    plan_path = (flat.get("plan") or flat.get("floor_plan") or flat.get("layout_plan") or "")
    plan_url = abs_url(plan_path, cfg["base_url"])
    if plan_url:
        lp = SubElement(obj, "LayoutPhoto")
        txt(lp, "FullUrl",   plan_url)
        txt(lp, "PhotoType", "realtyObjectLayout")

    # ─ Photos: images[] → building_render → genplan ──────────────────────────
    photo_urls = []

    # 1. Массив images (если есть)
    for img in flat.get("images", []):
        u = img.get("url") or img.get("full_url") or ""
        u = abs_url(u, cfg["base_url"])
        if u:
            photo_urls.append(u)

    # 2. Если images пустой — берём building_render и genplan
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


# ─ Dominanta ──────────────────────────────────────────────────────────────────
def make_dominanta_object(flat: dict, cfg: dict) -> Element:
    obj = Element("object")

    rooms = flat.get("rooms", "0")
    if not rooms or str(rooms) == "0":
        rooms = 9
    else:
        rooms = int(rooms)

    floor      = flat.get("floor", "")
    flat_num   = flat.get("num", "")
    section    = flat.get("section", "")
    building   = flat.get("building", "1")
    total_floors = flat.get("totalfloors", "")
    sq         = flat.get("sq", "0")
    price      = clean_price(flat.get("real_price", "0"))
    flat_id    = flat.get("id", "")

    # План из plans.default[1] (без мебели) или plans["0"]
    plan_url = ""
    plans = flat.get("plans", {})
    if isinstance(plans, dict):
        default_plans = plans.get("default") or []
        if default_plans:
            chosen = next((p for p in default_plans if "без" in p.get("name", "").lower()), default_plans[0])
            plan_url = chosen.get("url", "")
        elif plans.get("1"):
            plan_url = plans["1"]
        elif plans.get("0"):
            plan_url = plans["0"]
    if plan_url and not plan_url.startswith("http"):
        plan_url = cfg["base_url"] + plan_url

    # Срок сдачи из project
    project    = flat.get("project", {})
    fin_q      = project.get("finish_quarter", "")
    fin_y      = project.get("finish_year", "")

    txt(obj, "ExternalId",       flat_id)
    txt(obj, "Description",      f"ЖК {cfg['jk_name']}, этаж {floor}, номер квартиры {flat_num}")
    txt(obj, "Category",         "newBuildingFlatSale")
    txt(obj, "Address",          cfg["address"])
    txt(obj, "FlatRoomsCount",   rooms)
    txt(obj, "TotalArea",        sq)
    txt(obj, "FloorNumber",      floor)

    jk = SubElement(obj, "JKSchema")
    txt(jk, "Id",   cfg["jk_cian_id"])
    txt(jk, "Name", cfg["jk_name"])
    house = SubElement(jk, "House")
    txt(house, "Id",   building)
    txt(house, "Name", building)
    flat_el = SubElement(house, "Flat")
    txt(flat_el, "FlatNumber",    flat_num)
    txt(flat_el, "SectionNumber", section)

    agent = SubElement(obj, "SubAgent")
    txt(agent, "Email", EMAIL)

    if plan_url:
        lp = SubElement(obj, "LayoutPhoto")
        txt(lp, "FullUrl",   plan_url)
        txt(lp, "PhotoType", "realtyObjectLayout")

    bld_el = SubElement(obj, "Building")
    txt(bld_el, "FloorsCount", total_floors or DEFAULT_FLOORS)
    if fin_q and fin_y:
        dl = SubElement(bld_el, "Deadline")
        txt(dl, "Quarter",    quarter_str(fin_q))
        txt(dl, "Year",       fin_y)
        txt(dl, "IsComplete", "false")

    bt = SubElement(obj, "BargainTerms")
    txt(bt, "Price",           price)
    txt(bt, "Currency",        "rur")
    txt(bt, "MortgageAllowed", "true")
    return obj


# ─── Общая запись фида ──────────────────────────────────────────────────────────
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
    all_objects = []
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for cfg in PROJECTS:
        print(f"\n📥 Загрузка {cfg['jk_name']}...")
        source = cfg.get("source", "legenda")

        if source == "dominanta":
            flats   = fetch_dominanta(cfg)
            objects = [make_dominanta_object(f, cfg) for f in flats]
        else:
            flats   = fetch_legenda(cfg)
            objects = [make_legenda_object(f, cfg) for f in flats]

        print(f"   ✓ В фид: {len(objects)} квартир")
        write_feed(objects, cfg["output_file"])
        all_objects.extend(objects)

    write_feed(all_objects, "cian_feed.xml")
    print(f"\n✅ [{ts}] Готово: {len(all_objects)} объектов")


if __name__ == "__main__":
    main()
