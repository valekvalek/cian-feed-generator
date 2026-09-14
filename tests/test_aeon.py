import json
import unittest
from collections import Counter
from pathlib import Path

from aeon.fetch_aeon import make_aeon_object, map_category, map_rooms, parse_deadline
from feed_common import FeedGenerationError


FIXTURE = Path(__file__).parent / "fixtures" / "aeon_response.json"


class AeonTests(unittest.TestCase):
    def test_deadline_parser_is_strict(self):
        self.assertEqual(parse_deadline("25101"), {"quarter": "first", "year": "2025"})
        self.assertEqual(parse_deadline("25Q4"), {"quarter": "fourth", "year": "2025"})
        self.assertEqual(parse_deadline("2025Q4"), {"quarter": "fourth", "year": "2025"})
        self.assertIsNone(parse_deadline("25552"))
        self.assertIsNone(parse_deadline("25099"))

    def test_room_size_classes_cannot_be_mapped_to_flat_rooms(self):
        for code in ("S", "M", "L"):
            with self.assertRaises(FeedGenerationError):
                map_rooms(code)
        self.assertEqual(map_rooms("2"), 2)
        with self.assertRaises(FeedGenerationError):
            map_rooms("UNKNOWN")

    def test_category_maps_size_classes_to_free_appointment_sale(self):
        self.assertEqual(
            map_category(
                {
                    "articletype": "квартира",
                    "articlesubtype": "апартаменты",
                    "rooms": "S",
                }
            ),
            "freeAppointmentObjectSale",
        )
        self.assertEqual(
            map_category(
                {
                    "articletype": "квартира",
                    "articlesubtype": "квартира",
                    "rooms": "2",
                }
            ),
            "newBuildingFlatSale",
        )
        with self.assertRaises(FeedGenerationError):
            map_category({"articletype": "офис", "articlesubtype": "офис"})

    def test_fixture_maps_without_room_warnings(self):
        lots = json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]
        warnings = Counter()
        objects = [
            make_aeon_object(
                lot,
                "123456",
                warnings,
                f"https://example.com/{index}-layout.png",
                f"https://example.com/{index}-floor.png",
            )
            for index, lot in enumerate(lots)
        ]
        self.assertEqual(len(objects), 4)
        self.assertEqual(warnings, Counter({"25099": 1}))
        self.assertEqual(objects[0].findtext("Category"), "freeAppointmentObjectSale")
        self.assertIsNone(objects[0].find("FlatRoomsCount"))
        self.assertIsNone(objects[0].find("JKSchema"))
        self.assertEqual(objects[0].findtext("Layout"), "openSpace")
        self.assertEqual(objects[0].findtext("Building/Type"), "businessCenter")
        self.assertEqual(objects[0].findtext("BargainTerms/PriceType"), "all")
        self.assertEqual(objects[0].findtext("BargainTerms/Tax/Rate"), "22")
        self.assertEqual(
            objects[0].findtext("Address"),
            "Россия, Москва, улица Корабельная, 2",
        )
        self.assertEqual(objects[-1].findtext("Category"), "newBuildingFlatSale")
        self.assertEqual(objects[-1].findtext("FlatRoomsCount"), "2")
        self.assertEqual(objects[-1].findtext("JKSchema/Id"), "123456")
        self.assertTrue(
            all(len(obj.findall("Photos/PhotoSchema")) == 1 for obj in objects)
        )


if __name__ == "__main__":
    unittest.main()
