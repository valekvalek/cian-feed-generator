import json
import unittest
from pathlib import Path

from aeon.fetch_aeon import make_aeon_object, map_category
from feed_common import FeedGenerationError


FIXTURE = Path(__file__).parent / "fixtures" / "aeon_response.json"


class AeonTests(unittest.TestCase):
    def test_all_supported_lots_are_free_appointment_sale(self):
        for rooms, subtype in (("S", "апартаменты"), ("2", "квартира")):
            self.assertEqual(
                map_category(
                    {
                        "articletype": "квартира",
                        "articlesubtype": subtype,
                        "rooms": rooms,
                    }
                ),
                "freeAppointmentObjectSale",
            )
        with self.assertRaises(FeedGenerationError):
            map_category({"articletype": "офис", "articlesubtype": "офис"})

    def test_fixture_maps_every_lot_as_free_appointment(self):
        lots = json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]
        objects = [
            make_aeon_object(
                lot,
                f"https://example.com/{index}-layout.png",
                f"https://example.com/{index}-floor.png",
            )
            for index, lot in enumerate(lots)
        ]
        self.assertEqual(len(objects), 4)
        self.assertTrue(
            all(obj.findtext("Category") == "freeAppointmentObjectSale" for obj in objects)
        )
        self.assertTrue(all(obj.find("FlatRoomsCount") is None for obj in objects))
        self.assertTrue(all(obj.find("JKSchema") is None for obj in objects))
        self.assertEqual(objects[0].findtext("Layout"), "openSpace")
        self.assertEqual(objects[0].findtext("Building/Type"), "businessCenter")
        self.assertEqual(objects[0].findtext("BargainTerms/PriceType"), "all")
        self.assertEqual(objects[0].findtext("BargainTerms/Tax/Rate"), "22")
        self.assertEqual(
            objects[0].findtext("Address"),
            "Россия, Москва, улица Корабельная, 2",
        )
        self.assertEqual(
            objects[-1].findtext("Address"),
            "Россия, Москва, улица Корабельная, 1",
        )
        self.assertEqual(objects[-1].findtext("Building/FloorsCount"), "19")
        self.assertTrue(
            all(len(obj.findall("Photos/PhotoSchema")) == 1 for obj in objects)
        )


if __name__ == "__main__":
    unittest.main()
