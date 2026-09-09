import unittest

from feed_common import FeedGenerationError
from sezar.fetch_sezar import make_sezar_object, map_rooms


SAMPLE_FLAT = {
    "id": "01148bf8-3ad5-4eac-8b92-3973356ad801",
    "article": "SC_1_2_1_3_12",
    "project_slug": "sezarcity",
    "type": "flat",
    "section_number": 1,
    "floor_number": 3,
    "rooms": 1,
    "area": "47.50",
    "price": "24890000.00",
    "building_number": "2",
    "number": "12",
    "plan": "https://website.yandexcloud.net/sezar/media/plan.svg",
    "completion_year": 2027,
    "completion_quarter": 3,
    "max_floor": 28,
}


class SezarTests(unittest.TestCase):
    def test_object_maps_inventory_fields(self):
        obj = make_sezar_object(SAMPLE_FLAT, "4850351")
        self.assertEqual(obj.findtext("JKSchema/Id"), "4850351")
        self.assertEqual(obj.findtext("FlatRoomsCount"), "1")
        self.assertEqual(obj.findtext("Building/Deadline/Quarter"), "third")
        self.assertEqual(obj.findtext("SubAgent/Email"), "info@sezargroup.ru")
        self.assertEqual(obj.findtext("BargainTerms/Price"), "24890000")

    def test_only_confirmed_room_counts_are_accepted(self):
        self.assertEqual(map_rooms("4"), 4)
        with self.assertRaises(FeedGenerationError):
            map_rooms("studio")

    def test_other_projects_and_types_are_rejected(self):
        for override in ({"project_slug": "other"}, {"type": "commercial"}):
            flat = dict(SAMPLE_FLAT, **override)
            with self.subTest(override=override):
                with self.assertRaises(FeedGenerationError):
                    make_sezar_object(flat, "4850351")


if __name__ == "__main__":
    unittest.main()
