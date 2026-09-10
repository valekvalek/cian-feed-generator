#!/usr/bin/env python3
"""Generate the CIAN XML v2 feed for Sezar Group's SEZAR CITY project."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import re
from xml.etree.ElementTree import Element, SubElement

import requests
from cairosvg import svg2png

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
LAYOUT_DIR = Path(__file__).resolve().parent / "layouts"
LAYOUT_PUBLIC_BASE_URL = (
    "https://raw.githubusercontent.com/valekvalek/"
    "cian-feed-generator/main/sezar/layouts"
)
PAGE_SIZE = 10
MAX_WORKERS = 8
LAYOUT_MAX_WORKERS = 12
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
WHITE_FILL_RE = re.compile(rb"#[fF]{6}\b|#[fF]{3}\b")
HEADERS = {
    "Accept": "application/json",
    "Referer": f"{BASE_URL}/flats?mode=cards&project={PROJECT_SLUG}",
    "User-Agent": "Mozilla/5.0",
}
IMAGE_HEADERS = {
    **HEADERS,
    "Accept": "image/svg+xml,image/*;q=0.9,*/*;q=0.8",
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


def layout_filename(plan_url: str) -> str:
    """Return a stable cache filename for a source layout URL."""
    plan_url = str(plan_url or "").strip()
    if not plan_url.startswith("https://"):
        raise FeedGenerationError(f"Sezar: некорректный URL планировки {plan_url!r}")
    return f"{sha256(plan_url.encode('utf-8')).hexdigest()}.png"


def layout_public_url(plan_url: str) -> str:
    return f"{LAYOUT_PUBLIC_BASE_URL}/{layout_filename(plan_url)}"


def is_valid_png(path: Path) -> bool:
    try:
        return path.stat().st_size > len(PNG_SIGNATURE) and path.read_bytes().startswith(
            PNG_SIGNATURE
        )
    except OSError:
        return False


def ensure_layout_png(plan_url: str, destination: Path, session=None) -> bool:
    """Download an SVG plan and atomically render it as a white-background PNG.

    Returns True when a new PNG was written and False when the cache was reused.
    """
    if is_valid_png(destination):
        return False

    owns_session = session is None
    session = session or build_http_session()
    temp_path = destination.with_suffix(".png.tmp")
    try:
        response = session.get(plan_url, headers=IMAGE_HEADERS, timeout=45)
        response.raise_for_status()
        if not response.content:
            raise FeedGenerationError(f"Sezar: пустая SVG-планировка {plan_url}")

        destination.parent.mkdir(parents=True, exist_ok=True)
        # Sezar's SVGs are designed for a dark page background: their visible
        # walls, labels and furniture are white. CIAN uses a white photo canvas,
        # so normalize white vector fills to dark ink before rasterization.
        printable_svg = WHITE_FILL_RE.sub(b"#111111", response.content)
        svg2png(
            bytestring=printable_svg,
            write_to=str(temp_path),
            output_width=1200,
            background_color="#ffffff",
        )
        if not is_valid_png(temp_path):
            raise FeedGenerationError(f"Sezar: не удалось создать PNG из {plan_url}")
        temp_path.replace(destination)
        return True
    except FeedGenerationError:
        raise
    except (requests.RequestException, OSError, ValueError) as exc:
        raise FeedGenerationError(
            f"Sezar: ошибка подготовки PNG-планировки {plan_url}: {exc}"
        ) from exc
    except Exception as exc:
        # CairoSVG can raise parser-specific exceptions that are not part of its
        # public API. Convert them into the generator's safe failure type.
        raise FeedGenerationError(
            f"Sezar: ошибка конвертации SVG-планировки {plan_url}: {exc}"
        ) from exc
    finally:
        temp_path.unlink(missing_ok=True)
        if owns_session:
            session.close()


def prepare_layout_images(
    flats: list[dict], layout_dir: Path = LAYOUT_DIR
) -> dict[str, str]:
    """Build/reuse every plan PNG and return source-to-public URL mapping."""
    source_urls: set[str] = set()
    for flat in flats:
        plan_url = str(flat.get("plan") or "").strip()
        if not plan_url:
            raise FeedGenerationError(
                f"Sezar: у лота {flat.get('id') or flat.get('article')} нет планировки"
            )
        layout_filename(plan_url)  # Validate before starting concurrent downloads.
        source_urls.add(plan_url)

    layout_dir.mkdir(parents=True, exist_ok=True)
    destinations = {
        plan_url: layout_dir / layout_filename(plan_url) for plan_url in source_urls
    }
    missing = {
        plan_url: destination
        for plan_url, destination in destinations.items()
        if not is_valid_png(destination)
    }

    if missing:
        with ThreadPoolExecutor(max_workers=LAYOUT_MAX_WORKERS) as executor:
            futures = {
                executor.submit(ensure_layout_png, plan_url, destination): plan_url
                for plan_url, destination in missing.items()
            }
            completed = 0
            for future in as_completed(futures):
                future.result()
                completed += 1
                if completed % 25 == 0 or completed == len(futures):
                    print(f"   PNG-планировки: {completed} из {len(futures)}")

    expected_files = set(destinations.values())
    for cached_file in layout_dir.glob("*.png"):
        if cached_file not in expected_files:
            cached_file.unlink()

    print(
        f"   PNG-планировки: {len(source_urls)} всего, "
        f"{len(missing)} создано, {len(source_urls) - len(missing)} из кэша"
    )
    return {plan_url: layout_public_url(plan_url) for plan_url in source_urls}


def make_sezar_object(flat: dict, cian_id: str, layout_url: str) -> Element:
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

    if not layout_url.startswith("https://") or not layout_url.endswith(".png"):
        raise FeedGenerationError(
            f"Sezar: некорректный публичный URL PNG-планировки {layout_url!r}"
        )

    layout = SubElement(obj, "LayoutPhoto")
    add_text(layout, "FullUrl", layout_url)
    add_text(layout, "PhotoType", "realtyObjectLayout")

    photos = SubElement(obj, "Photos")
    photo = SubElement(photos, "PhotoSchema")
    add_text(photo, "FullUrl", layout_url)
    add_text(photo, "PhotoType", "realtyObject")

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
    layout_urls = prepare_layout_images(flats)
    objects = [
        make_sezar_object(flat, cian_id, layout_urls[str(flat["plan"]).strip()])
        for flat in flats
    ]
    write_feed_atomic(
        objects,
        OUTPUT_FILE,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        min_objects=100,
    )
    print(f"✅ {OUTPUT_FILE}: {len(objects)} квартир")


if __name__ == "__main__":
    main()
