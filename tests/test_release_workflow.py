from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


class ReleaseWorkflowTest(unittest.TestCase):
	def test_release_tag_comes_from_plugin_version(self):
		source = WORKFLOW.read_text(encoding="utf-8")

		self.assertIn('Path("core/constants.py")', source)
		self.assertIn('target.id == "VERSION"', source)
		self.assertNotIn("git tag --list '1.0.*'", source)

	def test_existing_release_skips_publish(self):
		source = WORKFLOW.read_text(encoding="utf-8")

		self.assertIn('gh release view "$next_tag"', source)
		self.assertIn('echo "publish=false"', source)
		self.assertIn("if: steps.release.outputs.publish == 'true'", source)

	def test_existing_version_tag_does_not_skip_publish(self):
		source = WORKFLOW.read_text(encoding="utf-8")

		self.assertNotIn('git rev-parse -q --verify "refs/tags/$next_tag"', source)
		self.assertIn('$0 != next_tag', source)


if __name__ == "__main__":
	unittest.main()
