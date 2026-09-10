#!/usr/bin/env python3
"""
Автоматический генератор XML-фидов для ЦИАН — ГК Некрасовка (Легенда).
Запуск: python legenda/fetch_feed.py

Выходные файлы:
  legenda/nekrasovka_feed.xml — ГК Некрасовка (Легенда Марусино + Легенда Коренево)
  legenda/marusino_feed.xml   — Легенда Марусино
  legenda/korenevo_feed.xml   — Легенда Коренево
"""

import argparse
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
        "key":         "marusino",
        "project_id":  "a5f9b6b9-037d-4cd8-981c-cbd55e93a5c0",
        "jk_name":     "Легенда Марусино",
        "cian_env":    "CIAN_ID_MARUSINO",
        "address":     "Россия, Московская область, Люберцы, Марусино",
        "base_url":    "https://legendamarusino.ru/",
        "api_url":     "https://legendamarusino.ru/api/realty-filter/custom/real-estates",
        "output_file": "legenda/marusino_feed.xml",
        "min_objects": 5,
    },
    {
        "key":         "korenevo",
        "project_id":  "61b193a5-aa22-4f3a-bf22-216ebc5648b1",
        "jk_name":     "Легенда Коренево",
        "cian_env":    "CIAN_ID_KORENEVO",
        "address":     "Россия, Московская область, Железнодорожный, Коренево",
        "base_url":    "https://legendakorenevo.ru/",
        "api_url":     "https://legendakorenevo.ru/api/realty-filter/custom/real-estates",
        "output_file": "legenda/korenevo_feed.xml",
        "min_objects": 5,
    },
]

PAGE_SIZE = 100
EMAIL     = "info@rusich.group"


# ─── Загрузка Легенда (POST + offset) ────────────────────────────────────────
def fetch_legenda(cfg: dict, session=None) -> list:
    flats, offset = [], 0
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    total_fetched = total_skipped = 0
    session = session or build_http_session()
    seen_pages: set[tuple] = set()

    while True:
        body = {"project_id": cfg["project_id"], "status": ["free"],
                "page_size": PAGE_SIZE, "offset": offset}
        data = request_json(session, "POST", cfg["api_url"], json=body, headers=headers)
        if isinstance(data, list):
            batch = data
        elif isinstance(data, dict):
            batch = data.get("results") or data.get("items") or data.get("data") or []
        else:
            raise FeedGenerationError(
                f"{cfg['jk_name']}: API вернул {type(data).__name__} вместо списка/объекта"
            )
        if not isinstance(batch, list):
            raise FeedGenerationError(f"{cfg['jk_name']}: поле с объектами не является списком")
        if not batch:
            break

        page_key = tuple(str(item.get("external_id") or item.get("id")) for item in batch)
        if page_key in seen_pages:
            raise FeedGenerationError(f"{cfg['jk_name']}: API повторил страницу offset={offset}")
        seen_pages.add(page_key)

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
    result = {"1": "first", "2": "second", "3": "third", "4": "fourth"}.get(str(q))
    if result is None:
        raise FeedGenerationError(f"Неизвестный квартал сдачи: {q!r}")
    return result

def txt(parent, tag, value):
    return add_text(parent, tag, value)

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
    txt(bt, "Price",           parse_price(flat.get("price")))
    txt(bt, "Currency",        "rur")
    txt(bt, "MortgageAllowed", "true")
    return obj


# ─── Запись фида ─────────────────────────────────────────────────────────────
# ─── main ─────────────────────────────────────────────────────────────────────
def generate_project(project_key: str, generated_at: str) -> list[Element]:
    try:
        raw_cfg = next(cfg for cfg in PROJECTS if cfg["key"] == project_key)
    except StopIteration as exc:
        raise FeedGenerationError(f"Неизвестный проект Легенда: {project_key!r}") from exc

    cfg = dict(raw_cfg)
    cfg["jk_cian_id"] = require_cian_id(cfg["cian_env"])
    print(f"\n📥 Загрузка {cfg['jk_name']}...")
    flats = fetch_legenda(cfg)
    objects = [make_legenda_object(flat, cfg) for flat in flats]
    print(f"   ✓ В фид: {len(objects)} квартир")
    write_feed_atomic(
        objects,
        cfg["output_file"],
        generated_at=generated_at,
        min_objects=cfg["min_objects"],
    )
    return objects


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project",
        choices=[cfg["key"] for cfg in PROJECTS] + ["all"],
        default="all",
        help="Сгенерировать один проект или все проекты Легенда",
    )
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    selected_keys = (
        [cfg["key"] for cfg in PROJECTS]
        if args.project == "all"
        else [args.project]
    )
    generated: dict[str, list[Element]] = {
        key: generate_project(key, generated_at) for key in selected_keys
    }

    if args.project == "all":
        nekrasovka_objects = [
            obj
            for cfg in PROJECTS
            for obj in generated[cfg["key"]]
        ]
        write_feed_atomic(
            nekrasovka_objects,
            "legenda/nekrasovka_feed.xml",
            generated_at=generated_at,
            min_objects=10,
        )
        print(f"\n✅ [{ts}] ГК Некрасовка: {len(nekrasovka_objects)} объектов")
        return

    project = next(cfg for cfg in PROJECTS if cfg["key"] == args.project)
    print(
        f"\n✅ [{ts}] {project['jk_name']} → {project['output_file']} "
        f"({len(generated[args.project])} объектов)"
    )


if __name__ == "__main__":
    main()
