import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree.ElementTree import Element, SubElement

from feed_common import (
    FeedGenerationError,
    add_text,
    count_objects,
    parse_price,
    require_cian_id,
    validate_feed,
    write_feed_atomic,
)


def valid_object(external_id: str) -> Element:
    obj = Element("object")
    for tag, value in (
        ("ExternalId", external_id),
        ("Category", "newBuildingFlatSale"),
        ("Address", "Россия, Москва"),
        ("FlatRoomsCount", "1"),
        ("TotalArea", "40"),
        ("FloorNumber", "2"),
    ):
        add_text(obj, tag, value)
    jk = SubElement(obj, "JKSchema")
    add_text(jk, "Id", "123456")
    add_text(jk, "Name", "Тест")
    agent = SubElement(obj, "SubAgent")
    add_text(agent, "Email", "test@example.com")
    building = SubElement(obj, "Building")
    add_text(building, "FloorsCount", "10")
    bargain = SubElement(obj, "BargainTerms")
    add_text(bargain, "Price", "10000000")
    add_text(bargain, "Currency", "rur")
    return obj


class CommonTests(unittest.TestCase):
    def test_price_parser_handles_decimal_and_grouping(self):
        cases = {
            "15 000 000 ₽": 15_000_000,
            "15000000.00": 15_000_000,
            "15,000,000": 15_000_000,
            15_000_000: 15_000_000,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(parse_price(raw), expected)

    def test_cian_id_is_required_and_numeric(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(FeedGenerationError):
                require_cian_id("CIAN_ID_TEST")
        with patch.dict(os.environ, {"CIAN_ID_TEST": "abc"}, clear=True):
            with self.assertRaises(FeedGenerationError):
                require_cian_id("CIAN_ID_TEST")
        with patch.dict(os.environ, {"CIAN_ID_TEST": "12345"}, clear=True):
            self.assertEqual(require_cian_id("CIAN_ID_TEST"), "12345")

    def test_atomic_write_preserves_last_good_feed_on_large_drop(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feed.xml"
            old_objects = [valid_object(f"old-{index}") for index in range(10)]
            write_feed_atomic(old_objects, path, generated_at="2026-01-01T00:00:00Z")
            self.assertEqual(validate_feed(path), 10)

            with self.assertRaises(FeedGenerationError):
                write_feed_atomic(
                    [valid_object(f"new-{index}") for index in range(4)],
                    path,
                    generated_at="2026-01-02T00:00:00Z",
                )
            self.assertEqual(count_objects(path), 10)

    def test_duplicate_external_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feed.xml"
            with self.assertRaises(FeedGenerationError):
                write_feed_atomic(
                    [valid_object("same"), valid_object("same")],
                    path,
                    generated_at="2026-01-01T00:00:00Z",
                )


if __name__ == "__main__":
    unittest.main()
