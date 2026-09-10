import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from PIL import Image

from feed_common import FeedGenerationError
from sezar.fetch_sezar import (
    PNG_SIGNATURE,
    ensure_layout_png,
    layout_public_url,
    make_sezar_object,
    map_rooms,
)


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
        layout_url = layout_public_url(SAMPLE_FLAT["plan"])
        obj = make_sezar_object(SAMPLE_FLAT, "4850351", layout_url)
        self.assertEqual(obj.findtext("JKSchema/Id"), "4850351")
        self.assertEqual(obj.findtext("FlatRoomsCount"), "1")
        self.assertEqual(obj.findtext("Building/Deadline/Quarter"), "third")
        self.assertEqual(obj.findtext("SubAgent/Email"), "info@sezargroup.ru")
        self.assertEqual(obj.findtext("BargainTerms/Price"), "24890000")
        self.assertEqual(obj.findtext("LayoutPhoto/FullUrl"), layout_url)
        self.assertEqual(obj.findtext("LayoutPhoto/PhotoType"), "realtyObjectLayout")
        self.assertEqual(obj.findtext("Photos/PhotoSchema/FullUrl"), layout_url)
        self.assertEqual(obj.findtext("Photos/PhotoSchema/PhotoType"), "realtyObject")

    def test_svg_plan_is_rendered_to_png_and_cached(self):
        svg = (
            b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
            b'<rect width="10" height="10" fill="#FFFFFF"/></svg>'
        )
        response = Mock(content=svg)
        response.raise_for_status.return_value = None
        session = Mock()
        session.get.return_value = response

        with TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "plan.png"
            self.assertTrue(
                ensure_layout_png(SAMPLE_FLAT["plan"], destination, session=session)
            )
            self.assertTrue(destination.read_bytes().startswith(PNG_SIGNATURE))
            with Image.open(destination) as rendered:
                self.assertNotEqual(
                    rendered.convert("RGB").getpixel((600, 600)),
                    (255, 255, 255),
                )
            self.assertFalse(
                ensure_layout_png(SAMPLE_FLAT["plan"], destination, session=session)
            )
            session.get.assert_called_once()

    def test_only_confirmed_room_counts_are_accepted(self):
        self.assertEqual(map_rooms("4"), 4)
        with self.assertRaises(FeedGenerationError):
            map_rooms("studio")

    def test_other_projects_and_types_are_rejected(self):
        for override in ({"project_slug": "other"}, {"type": "commercial"}):
            flat = dict(SAMPLE_FLAT, **override)
            with self.subTest(override=override):
                with self.assertRaises(FeedGenerationError):
                    make_sezar_object(
                        flat, "4850351", layout_public_url(SAMPLE_FLAT["plan"])
                    )


if __name__ == "__main__":
    unittest.main()
