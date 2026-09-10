import unittest
from pathlib import Path
import re

from feed_common import FeedGenerationError
from legenda.fetch_feed import generate_project
from sync_legacy_feeds import aliases_for_sources
from validate_feeds import FEED_GROUPS


class WorkflowIsolationTests(unittest.TestCase):
    FEED_WORKFLOWS = {
        "generate_marusino_feed.yml": "CIAN_ID_MARUSINO",
        "generate_korenevo_feed.yml": "CIAN_ID_KORENEVO",
        "generate_nekrasovka_feed.yml": None,
        "generate_svet_feed.yml": "CIAN_ID_SVET",
        "generate_aeon_feed.yml": "CIAN_ID_AEON",
        "generate_sezar_feed.yml": "CIAN_ID_SEZAR_CITY",
    }

    def test_every_canonical_feed_belongs_to_one_group(self):
        paths = [path for group in FEED_GROUPS.values() for path in group]
        self.assertEqual(len(paths), len(set(paths)))

    def test_alias_selection_does_not_include_other_feeds(self):
        source = Path("legenda/marusino_feed.xml")
        self.assertEqual(
            aliases_for_sources({source}),
            {Path("marusino_feed.xml"): source},
        )

    def test_empty_alias_selection_preserves_legacy_full_sync(self):
        self.assertGreater(len(aliases_for_sources()), 1)

    def test_unknown_legenda_project_fails_before_network_access(self):
        with self.assertRaises(FeedGenerationError):
            generate_project("unknown", "2026-01-01T00:00:00Z")

    def test_feed_workflows_have_isolated_secrets_and_concurrency(self):
        workflow_dir = Path(".github/workflows")
        groups = set()
        for filename, expected_secret in self.FEED_WORKFLOWS.items():
            content = (workflow_dir / filename).read_text(encoding="utf-8")
            secrets = set(re.findall(r"secrets\.(CIAN_ID_[A-Z_]+)", content))
            self.assertEqual(secrets, {expected_secret} if expected_secret else set())
            match = re.search(r"^  group: (feed-[a-z-]+)$", content, re.MULTILINE)
            self.assertIsNotNone(match)
            groups.add(match.group(1))

        self.assertEqual(len(groups), len(self.FEED_WORKFLOWS))
        self.assertFalse((workflow_dir / "generate_feed.yml").exists())


if __name__ == "__main__":
    unittest.main()
