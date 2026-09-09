import json
import unittest
from pathlib import Path

import requests

from aeon.fetch_aeon import fetch_all_lots
from dominanta.fetch_dominanta import PROJECTS as DOMINANTA_PROJECTS, fetch_dominanta
from feed_common import FeedGenerationError
from legenda.fetch_feed import PROJECTS as LEGENDA_PROJECTS, fetch_legenda


FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    def request(self, method, url, **kwargs):
        if self.error:
            raise self.error
        return FakeResponse(self.payload)


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FetcherTests(unittest.TestCase):
    def test_fixture_responses_are_loaded(self):
        self.assertEqual(
            len(fetch_legenda(LEGENDA_PROJECTS[0], FakeSession(fixture("legenda_response.json")))),
            1,
        )
        self.assertEqual(
            len(fetch_dominanta(DOMINANTA_PROJECTS[0], FakeSession(fixture("dominanta_response.json")))),
            1,
        )
        self.assertEqual(
            len(fetch_all_lots(FakeSession(fixture("aeon_response.json")))),
            4,
        )

    def test_network_error_is_fatal_for_every_source(self):
        error = requests.ConnectionError("offline")
        for callback in (
            lambda: fetch_legenda(LEGENDA_PROJECTS[0], FakeSession(error=error)),
            lambda: fetch_dominanta(DOMINANTA_PROJECTS[0], FakeSession(error=error)),
            lambda: fetch_all_lots(FakeSession(error=error)),
        ):
            with self.subTest(callback=callback):
                with self.assertRaises(FeedGenerationError):
                    callback()


if __name__ == "__main__":
    unittest.main()
