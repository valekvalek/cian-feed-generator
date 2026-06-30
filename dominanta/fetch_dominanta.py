#!/usr/bin/env python3
"""
Генератор XML-фидов для ЦИАН — Доминанта (ЖК Свет).
Запуск: python dominanta/fetch_dominanta.py

Выходные файлы:
  dominanta/svet_feed.xml      — ЖК Свет
  dominanta/dominanta_feed.xml — сводный фид Доминанта
"""

import requests
import os
import re
import sys
from datetime import datetime, timezone
from xml.etree.ElementTree import Element, SubElement, ElementTree, indent

DEFAULT_FLOORS = 8
EMAIL = "info@rusich.group"

PROJECTS = [
    {
        "jk_name":      "Свет",
        "jk_cian_id":   os.getenv("CIAN_ID_SVET", "SVET_CIAN_ID"),
        "address":      "Россия, Москва",
        "base_url":     "https://d-a.ru",
        "api_url":      "https://d-a.ru/ajax/flats/",
        "project_code": "svet",
        "output_file":  "dominanta/svet_feed.xml",
    },
]


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


def quarter_str(q) -> str:
    return {"1": "first", "2": "second", "3": "third", "4": "fourth",
            1: "first",   2: "second",   3: "third",   4: "fourth"}.get(str(q), "fourth")

def txt(parent, tag, value):
    el = SubElement(parent, tag)
    el.text = str(value) if value is not None else ""
    return el

def clean_price(val) -> int:
    return int(re.sub(r"\D", "", str(val))) if val else 0


def make_dominanta_object(flat: dict, cfg: dict) -> Element:
    obj = Element("object")

    rooms = flat.get("rooms", "0")
    rooms = 9 if not rooms or str(rooms) == "0" else int(rooms)

    floor        = flat.get("floor", "")
    flat_num     = flat.get("num", "")
    section      = flat.get("section", "")
    building     = flat.get("building", "1")
    total_floors = flat.get("totalfloors", "")
    sq           = flat.get("sq", "0")
    price        = clean_price(flat.get("real_price", "0"))
    flat_id      = flat.get("id", "")

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

    project = flat.get("project", {})
    fin_q   = project.get("finish_quarter", "")
    fin_y   = project.get("finish_year", "")

    txt(obj, "ExternalId",     flat_id)
    txt(obj, "Description",    f"ЖК {cfg['jk_name']}, этаж {floor}, номер квартиры {flat_num}")
    txt(obj, "Category",       "newBuildingFlatSale")
    txt(obj, "Address",        cfg["address"])
    txt(obj, "FlatRoomsCount", rooms)
    txt(obj, "TotalArea",      sq)
    txt(obj, "FloorNumber",    floor)

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


def main():
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    all_objects = []

    for cfg in PROJECTS:
        print(f"\n📥 Загрузка {cfg['jk_name']}...")
        flats   = fetch_dominanta(cfg)
        objects = [make_dominanta_object(f, cfg) for f in flats]
        print(f"   ✓ В фид: {len(objects)} квартир")
        write_feed(objects, cfg["output_file"])
        all_objects.extend(objects)

    write_feed(all_objects, "dominanta/dominanta_feed.xml")

    print(f"\n✅ [{ts}] Готово:")
    print(f"   ЖК Свет   → dominanta/svet_feed.xml      ({len(all_objects)} объектов)")
    print(f"   Доминанта → dominanta/dominanta_feed.xml ({len(all_objects)} объектов)")


if __name__ == "__main__":
    main()
