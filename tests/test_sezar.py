import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from PIL import Image

from feed_common import FeedGenerationError
from sezar.fetch_sezar import (
    PNG_SIGNATURE,
    ensure_layout_png,
    floor_hover_overlay,
    prepare_layout_images,
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
    "floor_plan": "https://website.yandexcloud.net/sezar/media/floor-plan.svg",
    "floor_hover": '<polygon class="st5" points="10,10 90,10 90,90 10,90" />',
    "completion_year": 2027,
    "completion_quarter": 3,
    "max_floor": 28,
}


class SezarTests(unittest.TestCase):
    def test_object_maps_inventory_fields(self):
        layout_url = layout_public_url(SAMPLE_FLAT["plan"])
        overlay = floor_hover_overlay(SAMPLE_FLAT["floor_hover"])
        floor_plan_url = layout_public_url(SAMPLE_FLAT["floor_plan"], overlay)
        obj = make_sezar_object(
            SAMPLE_FLAT, "4850351", layout_url, floor_plan_url
        )
        self.assertEqual(obj.findtext("JKSchema/Id"), "4850351")
        self.assertEqual(obj.findtext("FlatRoomsCount"), "1")
        self.assertEqual(obj.findtext("Building/Deadline/Quarter"), "third")
        self.assertEqual(obj.findtext("SubAgent/Email"), "info@sezargroup.ru")
        self.assertEqual(obj.findtext("BargainTerms/Price"), "24890000")
        self.assertEqual(obj.findtext("LayoutPhoto/FullUrl"), layout_url)
        self.assertEqual(obj.findtext("LayoutPhoto/PhotoType"), "realtyObjectLayout")
        photos = obj.findall("Photos/PhotoSchema")
        self.assertEqual(
            [photo.findtext("FullUrl") for photo in photos],
            [layout_url, floor_plan_url],
        )
        self.assertTrue(
            all(photo.findtext("PhotoType") == "realtyObject" for photo in photos)
        )

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

    def test_floor_plan_overlay_is_rendered_and_changes_cache_key(self):
        svg = (
            b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
            b'<rect width="100" height="100" fill="#FFFFFF"/></svg>'
        )
        response = Mock(content=svg)
        response.raise_for_status.return_value = None
        session = Mock()
        session.get.return_value = response
        overlay = floor_hover_overlay(SAMPLE_FLAT["floor_hover"])

        with TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "floor-plan.png"
            self.assertTrue(
                ensure_layout_png(
                    SAMPLE_FLAT["floor_plan"],
                    destination,
                    session=session,
                    overlay_svg=overlay,
                )
            )
            with Image.open(destination) as rendered:
                pixel = rendered.convert("RGB").getpixel((600, 600))
                self.assertGreater(pixel[0], pixel[2])
            self.assertNotEqual(
                layout_public_url(SAMPLE_FLAT["floor_plan"]),
                layout_public_url(SAMPLE_FLAT["floor_plan"], overlay),
            )

    def test_floor_plan_overlay_accepts_all_live_sezar_shapes(self):
        samples = (
            '<rect x="450.1" y="1000" width="528.4" height="505.8" />',
            '<path d="M2055.4,1016h159.3v-4.6h32.9z" />',
            '<path d="M590.1,1588.1" />'
            '<polygon points="584.8,1584.1 584.8,1134.1 121.7,1134.1" />',
        )
        for sample in samples:
            with self.subTest(sample=sample):
                overlay = floor_hover_overlay(sample)
                self.assertIn('fill="#D8C7A9"', overlay)

    @patch("sezar.fetch_sezar.download_layout_svg")
    def test_shared_floor_plan_is_downloaded_once(self, download_svg):
        download_svg.return_value = (
            b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
            b'<rect width="100" height="100" fill="#FFFFFF"/></svg>'
        )
        first = dict(SAMPLE_FLAT)
        second = dict(
            SAMPLE_FLAT,
            id="second",
            article="second",
            floor_hover='<rect x="10" y="10" width="20" height="20" />',
        )

        with TemporaryDirectory() as temp_dir:
            urls = prepare_layout_images([first, second], Path(temp_dir))

        self.assertEqual(len(urls), 3)
        self.assertEqual(download_svg.call_count, 2)

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
                        flat,
                        "4850351",
                        layout_public_url(SAMPLE_FLAT["plan"]),
                        layout_public_url(SAMPLE_FLAT["floor_plan"]),
                    )


if __name__ == "__main__":
    unittest.main()
