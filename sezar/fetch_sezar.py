#!/usr/bin/env python3
"""Generate the CIAN XML v2 feed for Sezar Group's SEZAR CITY project."""

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
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


BASE_URL = "https://sezar-group.ru"
API_URL = f"{BASE_URL}/api/flats/"
PROJECT_SLUG = "sezarcity"
JK_NAME = "СЕЗАР СИТИ"
ADDRESS = "Россия, Москва, 2-й Хорошёвский проезд, 7, стр. 8"
EMAIL = "info@sezargroup.ru"
OUTPUT_FILE = "sezar/sezar_city_feed.xml"
PAGE_SIZE = 10
MAX_WORKERS = 8
HEADERS = {
    "Accept": "application/json",
    "Referer": f"{BASE_URL}/flats?mode=cards&project={PROJECT_SLUG}",
    "User-Agent": "Mozilla/5.0",
}

ROOMS_MAP = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5}
QUARTERS = {1: "first", 2: "second", 3: "third", 4: "fourth"}


def fetch_sezar_flats(session=None) -> list[dict]:
    """Fetch the complete inventory, parallelizing Sezar's slow pages."""

    def fetch_page(offset: int, page_session=None) -> dict:
        owns_session = page_session is None
        page_session = page_session or build_http_session()
        try:
            data = request_json(
                page_session,
                "GET",
                API_URL,
                params={"limit": PAGE_SIZE, "offset": offset, "project": PROJECT_SLUG},
                headers=HEADERS,
                timeout=45,
            )
        finally:
            if owns_session:
                page_session.close()
        if not isinstance(data, dict):
            raise FeedGenerationError(
                f"Sezar: API вернул {type(data).__name__} вместо объекта"
            )
        return data

    first_page = fetch_page(0, session)
    try:
        expected_count = int(first_page.get("count"))
    except (TypeError, ValueError) as exc:
        raise FeedGenerationError("Sezar: API не вернул числовой count") from exc
    if expected_count <= 0:
        raise FeedGenerationError("Sezar: API вернул пустой фид")

    pages: dict[int, dict] = {0: first_page}
    offsets = list(range(PAGE_SIZE, expected_count, PAGE_SIZE))
    if offsets:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(fetch_page, offset, session): offset for offset in offsets
            }
            for future in as_completed(futures):
                offset = futures[future]
                pages[offset] = future.result()
                print(f"   загружена страница offset={offset}")

    flats: list[dict] = []
    seen_ids: set[str] = set()
    for offset in sorted(pages):
        data = pages[offset]

        batch = data.get("results")
        if not isinstance(batch, list):
            raise FeedGenerationError("Sezar: поле results не является списком")

        try:
            page_count = int(data.get("count"))
        except (TypeError, ValueError) as exc:
            raise FeedGenerationError("Sezar: API не вернул числовой count") from exc

        if page_count != expected_count:
            raise FeedGenerationError(
                f"Sezar: count изменился во время пагинации: {expected_count} → {page_count}"
            )

        expected_page_size = min(PAGE_SIZE, expected_count - offset)
        if len(batch) != expected_page_size:
            raise FeedGenerationError(
                f"Sezar: offset={offset}, получено {len(batch)} объектов "
                f"вместо {expected_page_size}"
            )

        page_ids = {str(item.get("id")) for item in batch}
        if "None" in page_ids or len(page_ids) != len(batch) or seen_ids & page_ids:
            raise FeedGenerationError(f"Sezar: повторяющиеся или пустые ID на offset={offset}")
        seen_ids.update(page_ids)

        flats.extend(batch)
        print(f"   offset={offset}: +{len(batch)}, итого {len(flats)} из {expected_count}")

    if len(flats) != expected_count:
        raise FeedGenerationError(
            f"Sezar: загружено {len(flats)} объектов из ожидаемых {expected_count}"
        )
    return flats


def map_rooms(value) -> int:
    try:
        rooms = int(value)
    except (TypeError, ValueError) as exc:
        raise FeedGenerationError(f"Sezar: неизвестное число комнат {value!r}") from exc
    if rooms not in ROOMS_MAP:
        raise FeedGenerationError(f"Sezar: неизвестное число комнат {value!r}")
    return ROOMS_MAP[rooms]


def make_sezar_object(flat: dict, cian_id: str) -> Element:
    if flat.get("project_slug") != PROJECT_SLUG:
        raise FeedGenerationError(
            f"Sezar: лот {flat.get('id', '?')} относится к проекту "
            f"{flat.get('project_slug')!r}"
        )
    if flat.get("type") != "flat":
        raise FeedGenerationError(
            f"Sezar: неподдерживаемый тип объекта {flat.get('type')!r}"
        )

    external_id = flat.get("id") or flat.get("article")
    floor = flat.get("floor_number")
    flat_number = flat.get("number")
    section = flat.get("section_number")
    building_number = flat.get("building_number")
    article = flat.get("article")

    obj = Element("object")
    add_text(obj, "ExternalId", external_id)
    add_text(
        obj,
        "Description",
        f"ЖК {JK_NAME}, корпус {building_number}, этаж {floor}, квартира {flat_number}",
    )
    add_text(obj, "Category", "newBuildingFlatSale")
    add_text(obj, "Address", ADDRESS)
    add_text(obj, "FlatRoomsCount", map_rooms(flat.get("rooms")))
    add_text(obj, "TotalArea", flat.get("area"))
    add_text(obj, "FloorNumber", floor)

    jk = SubElement(obj, "JKSchema")
    add_text(jk, "Id", cian_id)
    add_text(jk, "Name", JK_NAME)
    house = SubElement(jk, "House")
    add_text(house, "Id", building_number)
    add_text(house, "Name", building_number)
    flat_element = SubElement(house, "Flat")
    add_text(flat_element, "FlatNumber", flat_number)
    add_text(flat_element, "SectionNumber", section)

    agent = SubElement(obj, "SubAgent")
    add_text(agent, "Email", EMAIL)

    plan_url = str(flat.get("plan") or "").strip()
    if plan_url:
        layout = SubElement(obj, "LayoutPhoto")
        add_text(layout, "FullUrl", plan_url)
        add_text(layout, "PhotoType", "realtyObjectLayout")

    if article:
        add_text(obj, "Url", f"{BASE_URL}/projects/{PROJECT_SLUG}/flats/{article}")

    building = SubElement(obj, "Building")
    add_text(building, "FloorsCount", flat.get("max_floor"))
    year = flat.get("completion_year")
    quarter = flat.get("completion_quarter")
    if year and quarter:
        try:
            quarter_name = QUARTERS[int(quarter)]
        except (KeyError, TypeError, ValueError) as exc:
            raise FeedGenerationError(f"Sezar: неизвестный квартал {quarter!r}") from exc
        deadline = SubElement(building, "Deadline")
        add_text(deadline, "Quarter", quarter_name)
        add_text(deadline, "Year", year)
        add_text(deadline, "IsComplete", "false")

    bargain = SubElement(obj, "BargainTerms")
    add_text(bargain, "Price", parse_price(flat.get("price")))
    add_text(bargain, "Currency", "rur")
    add_text(bargain, "MortgageAllowed", "true")
    return obj


def main() -> None:
    cian_id = require_cian_id("CIAN_ID_SEZAR_CITY")
    print(f"\n📥 Загрузка {JK_NAME}...")
    flats = fetch_sezar_flats()
    objects = [make_sezar_object(flat, cian_id) for flat in flats]
    write_feed_atomic(
        objects,
        OUTPUT_FILE,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        min_objects=100,
    )
    print(f"✅ {OUTPUT_FILE}: {len(objects)} квартир")


if __name__ == "__main__":
    main()
