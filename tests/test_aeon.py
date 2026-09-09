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

    def test_room_size_classes_are_explicit_free_layouts(self):
        for code in ("S", "M", "L"):
            self.assertEqual(map_rooms(code), 7)
        self.assertEqual(map_rooms("2"), 2)
        with self.assertRaises(FeedGenerationError):
            map_rooms("UNKNOWN")

    def test_category_rejects_non_residential_api_objects(self):
        self.assertEqual(
            map_category({"articletype": "квартира", "articlesubtype": "апартаменты"}),
            "newBuildingFlatSale",
        )
        with self.assertRaises(FeedGenerationError):
            map_category({"articletype": "офис", "articlesubtype": "офис"})

    def test_fixture_maps_without_room_warnings(self):
        lots = json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]
        warnings = Counter()
        objects = [make_aeon_object(lot, "123456", warnings) for lot in lots]
        self.assertEqual(len(objects), 4)
        self.assertEqual(warnings, Counter({"25552": 2, "25099": 1}))
        self.assertEqual(objects[0].findtext("FlatRoomsCount"), "7")
        self.assertEqual(objects[-1].findtext("FlatRoomsCount"), "2")


if __name__ == "__main__":
    unittest.main()
