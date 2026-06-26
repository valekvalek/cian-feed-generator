#!/usr/bin/env python3
"""
Автоматический генератор XML-фида для ЦИАН.
Получает данные о свободных квартирах из API сайтов ЖК Легенда
и формирует cian_feed.xml по стандарту ЦИАН XML v2.

API-особенности (проверено 2026-06-26):
- Метод: POST
- Пагинация: параметр offset (не page!), page_size макс. 100
- Всего квартир: Коренево ~539, Марусино ~206

Запуск: python fetch_feed.py
"""

import requests
import os
import sys
from datetime import datetime

# ─── Конфигурация проектов ────────────────────────────────────────────────────
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

PAGE_SIZE   = 100   # максимум, который принимает API
OUTPUT_FILE = "cian_feed.xml"
EMAIL       = "info@rusich.group"


# ─── Запрос с offset-пагинацией ──────────────────────────────────────────────
def fetch_all_flats(cfg: dict) -> list:
    """
    Загружает все свободные квартиры по проекту через POST-запросы.
    API использует offset-пагинацию (не page), page_size макс 100.
    """
    flats  = []
    offset = 0
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    while True:
        body = {
            "project_id": cfg["project_id"],
            "status":     ["free"],
            "page_size":  PAGE_SIZE,
            "offset":     offset,
        }
        try:
            resp = requests.post(
                cfg["api_url"],
                json=body,
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  ⚠ Ошибка запроса ({cfg['jk_name']} offset={offset}): {e}", file=sys.stderr)
            break

        data = resp.json()

        # API возвращает список напрямую
        if isinstance(data, list):
            batch = data
        else:
            batch = data.get("results") or data.get("items") or data.get("data") or []

        if not batch:
            break  # пустой ответ — всё скачали

        flats.extend(batch)
        print(f"   offset={offset}: +{len(batch)} кв., итого {len(flats)}")

        if len(batch) < PAGE_SIZE:
            break  # последняя страница

        offset += PAGE_SIZE

    return flats


# ─── XML-утилиты ─────────────────────────────────────────────────────────────
def esc(s) -> str:
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def quarter_str(q: int) -> str:
    return {1: "first", 2: "second", 3: "third", 4: "fourth"}.get(q, "fourth")


def make_object_xml(flat: dict, cfg: dict) -> str:
    """Формирует XML-блок <object> для одной квартиры."""
    ext_id   = flat.get("external_id", "")
    rooms    = flat.get("rooms", 0)
    total    = flat.get("total_area", 0)
    living   = flat.get("living_area", 0)
    kitchen  = flat.get("kitchen_area", 0)
    floor    = flat.get("floor_number", "")
    section  = flat.get("section_number", "")
    number   = flat.get("number", "")
    price    = int(flat.get("price", 0))
    axis     = flat.get("axis", "")
    bld_num  = flat.get("building_number", "")
    q        = flat.get("completion_quarter")
    yr       = flat.get("completion_year")
    is_ready = flat.get("is_ready", False)
    base     = cfg["base_url"]
    jk_name  = cfg["jk_name"]
    jk_cid   = cfg["jk_cian_id"]

    # Планировка
    plan = flat.get("plan") or flat.get("layout_plan", "")
    layout_xml = ""
    if plan:
        url = plan if plan.startswith("http") else base + plan
        layout_xml = (
            f"<LayoutPhoto><FullUrl>{esc(url)}</FullUrl>"
            f"<PhotoType>realtyObjectLayout</PhotoType></LayoutPhoto>"
        )

    # Фотографии
    images = flat.get("images", [])
    imgs_xml = ""
    if images:
        items_xml = ""
        for img in images:
            u = img.get("url") or img.get("full_url", "")
            if u:
                items_xml += (
                    f"<PhotoSchema><FullUrl>{esc(u)}</FullUrl>"
                    f"<PhotoType>realtyObject</PhotoType></PhotoSchema>"
                )
        if items_xml:
            imgs_xml = f"<Photos>{items_xml}</Photos>"

    # Срок сдачи
    deadline_xml = ""
    if q and yr:
        done = "true" if is_ready else "false"
        deadline_xml = (
            f"<Deadline><Quarter>{quarter_str(q)}</Quarter>"
            f"<Year>{yr}</Year>"
            f"<IsComplete>{done}</IsComplete></Deadline>"
        )

    desc = f"ЖК {jk_name}, этаж {floor}, номер квартиры {number}"

    return (
        f"<object>"
        f"<ExternalId>{esc(ext_id)}</ExternalId>"
        f"<Description>{esc(desc)}</Description>"
        f"<Category>newBuildingFlatSale</Category>"
        f"<FlatOnFloorNumber>{esc(str(axis))}</FlatOnFloorNumber>"
        f"<Address>{esc(cfg['address'])}</Address>"
        f"<FlatRoomsCount>{rooms}</FlatRoomsCount>"
        f"<TotalArea>{total}</TotalArea>"
        f"<LivingArea>{living}</LivingArea>"
        f"<KitchenArea>{kitchen}</KitchenArea>"
        f"<FloorNumber>{floor}</FloorNumber>"
        f"<JKSchema>"
        f"<Id>{esc(jk_cid)}</Id>"
        f"<Name>{esc(jk_name)}</Name>"
        f"<House><Id>{esc(bld_num)}</Id><Name>{esc(bld_num)}</Name>"
        f"<Flat><FlatNumber>{esc(number)}</FlatNumber>"
        f"<SectionNumber>{esc(section)}</SectionNumber></Flat>"
        f"</House></JKSchema>"
        f"<SubAgent><Email>{EMAIL}</Email></SubAgent>"
        f"{layout_xml}"
        f"{imgs_xml}"
        f"<Building>{deadline_xml}</Building>"
        f"<BargainTerms>"
        f"<Price>{price}</Price>"
        f"<Currency>rur</Currency>"
        f"<MortgageAllowed>true</MortgageAllowed>"
        f"</BargainTerms>"
        f"</object>"
    )


# ─── Главный блок ─────────────────────────────────────────────────────────────
def main():
    all_objects = []

    for cfg in PROJECTS:
        print(f"\n📥 Загрузка {cfg['jk_name']} ({cfg['api_url']})...")
        flats = fetch_all_flats(cfg)
        print(f"   ✓ Итого: {len(flats)} квартир")
        for flat in flats:
            all_objects.append(make_object_xml(flat, cfg))

    xml_out = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed><feed_version>2</feed_version>'
        + "".join(all_objects)
        + "</feed>"
    )

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(xml_out)

    total = len(all_objects)
    size  = os.path.getsize(OUTPUT_FILE)
    ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n✅ [{ts}] Готово: {total} объектов → {OUTPUT_FILE} ({size:,} байт)")


if __name__ == "__main__":
    main()
