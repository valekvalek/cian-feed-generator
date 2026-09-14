"""Download, rasterize and cache stable PNG images used by CIAN feeds."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from threading import Lock, local
from typing import Iterable

import pymupdf
import requests
from cairosvg import svg2png
from PIL import Image, ImageOps

from feed_common import FeedGenerationError, add_text, build_http_session


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
RENDER_VERSION = "1"
MAX_WORKERS = 16
IMAGE_HEADERS = {
    "Accept": "image/avif,image/webp,image/svg+xml,image/*,application/pdf;q=0.9,*/*;q=0.8",
    "User-Agent": "Mozilla/5.0",
}


def media_filename(source_url: str) -> str:
    source_url = str(source_url or "").strip()
    if not source_url.startswith("https://"):
        raise FeedGenerationError(f"Некорректный URL изображения {source_url!r}")
    render_version = (
        "river-floor-crop-1"
        if "river-park.ru/pdf/lot_plan_" in source_url
        else RENDER_VERSION
    )
    cache_key = f"{render_version}\0{source_url}"
    return f"{sha256(cache_key.encode('utf-8')).hexdigest()}.png"


def media_public_url(source_url: str, public_base_url: str) -> str:
    return f"{public_base_url.rstrip('/')}/{media_filename(source_url)}"


def is_valid_png(path: Path) -> bool:
    try:
        return path.stat().st_size > len(PNG_SIGNATURE) and path.read_bytes().startswith(
            PNG_SIGNATURE
        )
    except OSError:
        return False


def download_media(source_url: str, session=None) -> bytes:
    owns_session = session is None
    session = session or build_http_session()
    try:
        response = session.get(source_url, headers=IMAGE_HEADERS, timeout=60)
        response.raise_for_status()
        if not response.content:
            raise FeedGenerationError(f"Пустое изображение {source_url}")
        return response.content
    except FeedGenerationError:
        raise
    except requests.RequestException as exc:
        raise FeedGenerationError(f"Ошибка загрузки изображения {source_url}: {exc}") from exc
    finally:
        if owns_session:
            session.close()


def _open_source_image(source: bytes, source_url: str) -> Image.Image:
    stripped = source.lstrip()
    if source.startswith(b"%PDF-"):
        try:
            document = pymupdf.open(stream=source, filetype="pdf")
            if document.page_count < 1:
                raise FeedGenerationError(f"PDF не содержит страниц: {source_url}")
            page = document[0]
            clip = page.rect
            if "river-park.ru/pdf/lot_plan_" in source_url:
                # River Park places the highlighted floor scheme in a fixed
                # sidebar of its landscape A4 lot card. Crop that scheme so it
                # remains readable in CIAN instead of publishing the full PDF.
                clip = pymupdf.Rect(8, 260, 115, 405)
            scale = 1200 / max(clip.width, 1)
            pixmap = page.get_pixmap(
                matrix=pymupdf.Matrix(scale, scale),
                clip=clip,
                alpha=False,
            )
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            document.close()
            return image
        except FeedGenerationError:
            raise
        except Exception as exc:
            raise FeedGenerationError(f"Ошибка чтения PDF {source_url}: {exc}") from exc

    if stripped.startswith(b"<svg") or b"<svg" in stripped[:1000]:
        try:
            rendered = svg2png(
                bytestring=source,
                output_width=1200,
                background_color="#ffffff",
            )
            return Image.open(BytesIO(rendered))
        except Exception as exc:
            raise FeedGenerationError(f"Ошибка конвертации SVG {source_url}: {exc}") from exc

    try:
        return Image.open(BytesIO(source))
    except Exception as exc:
        raise FeedGenerationError(f"Неизвестный формат изображения {source_url}: {exc}") from exc


def ensure_media_png(source_url: str, destination: Path, session=None) -> bool:
    """Create one white-background PNG or reuse an existing valid cache file."""
    if is_valid_png(destination):
        return False

    temp_path = destination.with_suffix(".png.tmp")
    try:
        source = download_media(source_url, session=session)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with _open_source_image(source, source_url) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGBA")
            white = Image.new("RGBA", image.size, "white")
            white.alpha_composite(image)
            image = white.convert("RGB")
            if image.width != 1200:
                height = max(1, round(image.height * 1200 / image.width))
                image = image.resize((1200, height), Image.Resampling.LANCZOS)
            image.quantize(colors=128).save(temp_path, format="PNG", optimize=True)

        if not is_valid_png(temp_path):
            raise FeedGenerationError(f"Не удалось создать PNG из {source_url}")
        temp_path.replace(destination)
        return True
    except FeedGenerationError:
        raise
    except (OSError, ValueError) as exc:
        raise FeedGenerationError(f"Ошибка подготовки PNG {source_url}: {exc}") from exc
    finally:
        temp_path.unlink(missing_ok=True)


def prepare_media_images(
    source_urls: Iterable[str],
    layout_dir: Path,
    public_base_url: str,
    *,
    label: str,
) -> dict[str, str]:
    """Build/reuse all unique PNGs and return source-to-public URL mapping."""
    sources = {str(url or "").strip() for url in source_urls}
    if "" in sources:
        raise FeedGenerationError(f"{label}: отсутствует одно из двух изображений")
    for source_url in sources:
        media_filename(source_url)

    layout_dir.mkdir(parents=True, exist_ok=True)
    destinations = {
        source_url: layout_dir / media_filename(source_url) for source_url in sources
    }
    missing = {
        source_url: destination
        for source_url, destination in destinations.items()
        if not is_valid_png(destination)
    }

    thread_state = local()
    sessions: list[requests.Session] = []
    sessions_lock = Lock()

    def get_session() -> requests.Session:
        session = getattr(thread_state, "session", None)
        if session is None:
            session = build_http_session()
            thread_state.session = session
            with sessions_lock:
                sessions.append(session)
        return session

    def prepare_one(source_url: str, destination: Path) -> bool:
        return ensure_media_png(source_url, destination, session=get_session())

    if missing:
        print(f"   {label}: нужно создать {len(missing)} PNG", flush=True)
        try:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {
                    executor.submit(prepare_one, source_url, destination): source_url
                    for source_url, destination in missing.items()
                }
                completed = 0
                for future in as_completed(futures):
                    future.result()
                    completed += 1
                    if completed % 25 == 0 or completed == len(missing):
                        print(f"   {label}: {completed} из {len(missing)} PNG", flush=True)
        finally:
            for session in sessions:
                session.close()

    expected_files = set(destinations.values())
    for cached_file in layout_dir.glob("*.png"):
        if cached_file not in expected_files:
            cached_file.unlink()

    print(
        f"   {label}: {len(sources)} PNG, {len(missing)} создано, "
        f"{len(sources) - len(missing)} из кэша"
    )
    return {
        source_url: media_public_url(source_url, public_base_url)
        for source_url in sources
    }


def add_two_feed_images(obj, layout_url: str, secondary_url: str, *, label: str) -> None:
    """Add exactly one apartment layout and one distinct secondary image."""
    urls = (str(layout_url).strip(), str(secondary_url).strip())
    if urls[0] == urls[1]:
        raise FeedGenerationError(f"{label}: планировка и второе изображение совпадают")
    if any(not url.startswith("https://") or not url.endswith(".png") for url in urls):
        raise FeedGenerationError(f"{label}: ожидались два публичных PNG URL")

    from xml.etree.ElementTree import SubElement

    layout = SubElement(obj, "LayoutPhoto")
    add_text(layout, "FullUrl", urls[0])
    add_text(layout, "PhotoType", "realtyObjectLayout")

    photos = SubElement(obj, "Photos")
    photo = SubElement(photos, "PhotoSchema")
    add_text(photo, "FullUrl", urls[1])
    add_text(photo, "PhotoType", "realtyObject")
