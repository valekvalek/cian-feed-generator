"""Shared reliability and XML validation helpers for CIAN feed generators."""

from __future__ import annotations

import copy
import os
import re
import tempfile
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable
from xml.etree.ElementTree import Element, ElementTree, ParseError, SubElement, indent, parse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


PLACEHOLDER_RE = re.compile(r"(?:^|_)[A-Z]+_CIAN_ID$")
REQUIRED_OBJECT_FIELDS = (
    "ExternalId",
    "Category",
    "Address",
    "FlatRoomsCount",
    "TotalArea",
    "FloorNumber",
    "JKSchema",
    "SubAgent",
    "Building",
    "BargainTerms",
)


class FeedGenerationError(RuntimeError):
    """Raised when publishing a new feed would be unsafe."""


def require_cian_id(env_name: str) -> str:
    value = os.getenv(env_name, "").strip()
    if not value:
        raise FeedGenerationError(f"Обязательная переменная {env_name} не задана")
    if not value.isdigit():
        raise FeedGenerationError(f"{env_name} должна содержать числовой CIAN ID")
    return value


def build_http_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def request_json(session: requests.Session, method: str, url: str, **kwargs):
    try:
        response = session.request(method, url, timeout=30, **kwargs)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise FeedGenerationError(f"Ошибка API {url}: {exc}") from exc


def parse_price(value) -> int:
    """Parse a ruble price without multiplying decimal values by 100."""
    if value is None or isinstance(value, bool):
        raise FeedGenerationError("Цена отсутствует")

    if isinstance(value, (int, float, Decimal)):
        normalized = str(value)
    else:
        normalized = re.sub(r"[^0-9,.-]", "", str(value).replace("\u00a0", ""))

    if not normalized:
        raise FeedGenerationError(f"Не удалось разобрать цену: {value!r}")

    separators = [pos for pos, char in enumerate(normalized) if char in ",."]
    if separators:
        last = separators[-1]
        decimals = len(normalized) - last - 1
        if len(separators) == 1 and 1 <= decimals <= 2:
            normalized = normalized.replace(",", ".")
        elif len(separators) > 1 and 1 <= decimals <= 2:
            decimal_separator = normalized[last]
            integer_part = re.sub(r"[,.]", "", normalized[:last])
            normalized = integer_part + "." + normalized[last + 1 :]
        else:
            normalized = re.sub(r"[,.]", "", normalized)

    try:
        amount = Decimal(normalized)
    except InvalidOperation as exc:
        raise FeedGenerationError(f"Не удалось разобрать цену: {value!r}") from exc

    price = int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if price <= 0:
        raise FeedGenerationError(f"Цена должна быть положительной: {value!r}")
    return price


def add_text(parent: Element, tag: str, value) -> Element:
    element = SubElement(parent, tag)
    element.text = str(value) if value is not None else ""
    return element


def build_feed_root(objects: Iterable[Element], generated_at: str) -> Element:
    root = Element("feed")
    add_text(root, "feed_version", "2")
    add_text(root, "generated", generated_at)
    for obj in objects:
        root.append(copy.deepcopy(obj))
    return root


def count_objects(path: str | Path) -> int:
    try:
        return len(parse(path).getroot().findall("object"))
    except (OSError, ParseError):
        return 0


def validate_feed(path: str | Path, *, min_objects: int = 1) -> int:
    path = Path(path)
    try:
        root = parse(path).getroot()
    except (OSError, ParseError) as exc:
        raise FeedGenerationError(f"{path}: некорректный XML: {exc}") from exc

    if root.tag != "feed":
        raise FeedGenerationError(f"{path}: корневой элемент должен быть <feed>")
    if root.findtext("feed_version") != "2":
        raise FeedGenerationError(f"{path}: ожидается feed_version=2")

    objects = root.findall("object")
    if len(objects) < min_objects:
        raise FeedGenerationError(
            f"{path}: объектов {len(objects)}, минимально допустимо {min_objects}"
        )

    seen_ids: set[str] = set()
    for index, obj in enumerate(objects, start=1):
        for tag in REQUIRED_OBJECT_FIELDS:
            element = obj.find(tag)
            if element is None or not "".join(element.itertext()).strip():
                raise FeedGenerationError(f"{path}: object #{index}, пустое поле {tag}")

        external_id = (obj.findtext("ExternalId") or "").strip()
        if external_id in seen_ids:
            raise FeedGenerationError(f"{path}: повторяющийся ExternalId={external_id}")
        seen_ids.add(external_id)

        cian_id = (obj.findtext("JKSchema/Id") or "").strip()
        if not cian_id.isdigit() or PLACEHOLDER_RE.search(cian_id):
            raise FeedGenerationError(f"{path}: некорректный CIAN ID={cian_id!r}")

        price = parse_price(obj.findtext("BargainTerms/Price"))
        if price <= 0:  # pragma: no cover - parse_price already enforces this
            raise FeedGenerationError(f"{path}: ExternalId={external_id}, цена <= 0")

        for url_element in obj.findall(".//FullUrl"):
            url = (url_element.text or "").strip()
            if not re.match(r"^https?://", url):
                raise FeedGenerationError(
                    f"{path}: ExternalId={external_id}, некорректный URL={url!r}"
                )

    return len(objects)


def write_feed_atomic(
    objects: list[Element],
    output_file: str | Path,
    *,
    generated_at: str,
    min_objects: int = 1,
    max_drop_ratio: float = 0.5,
) -> None:
    """Validate a temporary feed and replace the last good file atomically."""
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    previous_count = count_objects(output_path) if output_path.exists() else 0

    root = build_feed_root(objects, generated_at)
    indent(root, space="  ")

    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent,
            delete=False,
        ) as temp_file:
            temp_name = temp_file.name
            ElementTree(root).write(temp_file, encoding="utf-8", xml_declaration=True)

        new_count = validate_feed(temp_name, min_objects=min_objects)
        if previous_count and new_count < previous_count * (1 - max_drop_ratio):
            raise FeedGenerationError(
                f"{output_path}: резкое падение количества объектов "
                f"{previous_count} → {new_count} (> {max_drop_ratio:.0%})"
            )

        os.replace(temp_name, output_path)
        temp_name = None
        print(f"   💾 {output_path} ({output_path.stat().st_size:,} байт, {new_count} объектов)")
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)
