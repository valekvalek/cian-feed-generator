import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
from xml.etree.ElementTree import Element

import pymupdf
from PIL import Image

from feed_common import FeedGenerationError
from feed_media import (
    PNG_SIGNATURE,
    add_two_feed_images,
    ensure_media_png,
    media_filename,
)
from aeon.fetch_aeon import aeon_image_sources
from dominanta.fetch_dominanta import dominanta_image_sources
from legenda.fetch_feed import PROJECTS as LEGENDA_PROJECTS, legenda_image_sources


def session_with(content: bytes) -> Mock:
    response = Mock(content=content)
    response.raise_for_status.return_value = None
    session = Mock()
    session.get.return_value = response
    return session


class FeedMediaTests(unittest.TestCase):
    def test_source_specific_image_pairs_are_distinct(self):
        legenda = legenda_image_sources(
            {"external_id": "1", "plan": "media/flat.svg", "floor_plan": "media/floor.png"},
            LEGENDA_PROJECTS[0],
        )
        self.assertTrue(all(url.startswith("https://storage.yandexcloud.net/") for url in legenda))

        dominanta = dominanta_image_sources(
            {
                "id": "2",
                "plans": {
                    "default": [
                        {"name": "С мебелью", "url": "/with.jpg"},
                        {"name": "Без мебели", "url": "/without.jpg"},
                    ]
                },
            },
            {"jk_name": "Свет", "base_url": "https://d-a.ru"},
        )
        self.assertEqual(dominanta, ("https://d-a.ru/without.jpg", "https://d-a.ru/with.jpg"))

        aeon = aeon_image_sources(
            {"lotcode": "3", "layout": "/layout.svg", "plan": "/floor.pdf"}
        )
        self.assertNotEqual(*aeon)

    def test_svg_is_rendered_to_stable_png(self):
        source_url = "https://example.com/layout.svg"
        svg = (
            b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="20">'
            b'<rect width="10" height="20" fill="#222"/></svg>'
        )
        with TemporaryDirectory() as directory:
            destination = Path(directory) / media_filename(source_url)
            session = session_with(svg)
            self.assertTrue(ensure_media_png(source_url, destination, session=session))
            self.assertTrue(destination.read_bytes().startswith(PNG_SIGNATURE))
            with Image.open(destination) as image:
                self.assertEqual(image.width, 1200)
            self.assertFalse(ensure_media_png(source_url, destination, session=session))
            session.get.assert_called_once()

    def test_pdf_is_rendered_to_png(self):
        document = pymupdf.open()
        page = document.new_page(width=200, height=100)
        page.insert_text((20, 50), "floor plan")
        pdf = document.tobytes()
        document.close()

        with TemporaryDirectory() as directory:
            destination = Path(directory) / "floor.png"
            self.assertTrue(
                ensure_media_png(
                    "https://example.com/floor.pdf",
                    destination,
                    session=session_with(pdf),
                )
            )
            with Image.open(destination) as image:
                self.assertEqual(image.size, (1200, 600))

    def test_feed_contains_exactly_two_distinct_pngs(self):
        obj = Element("object")
        add_two_feed_images(
            obj,
            "https://example.com/layout.png",
            "https://example.com/floor.png",
            label="test",
        )
        self.assertEqual(len(obj.findall("LayoutPhoto")), 1)
        self.assertEqual(len(obj.findall("Photos/PhotoSchema")), 1)
        with self.assertRaises(FeedGenerationError):
            add_two_feed_images(
                Element("object"),
                "https://example.com/same.png",
                "https://example.com/same.png",
                label="test",
            )


if __name__ == "__main__":
    unittest.main()
