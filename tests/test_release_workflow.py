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

	def test_existing_release_bumps_plugin_version(self):
		source = WORKFLOW.read_text(encoding="utf-8")

		self.assertIn('gh release view "$1"', source)
		self.assertIn('while version_exists "$next_tag"; do', source)
		self.assertIn('VERSION = "{next_version}"', source)
		self.assertIn('git commit -m "chore bump plugin version to $next_tag"', source)
		self.assertIn('git push origin "HEAD:main"', source)
		self.assertNotIn('echo "publish=false"', source)
		self.assertIn("if: steps.release.outputs.publish == 'true'", source)

	def test_existing_version_tag_bumps_before_publish(self):
		source = WORKFLOW.read_text(encoding="utf-8")

		self.assertIn('git rev-parse --verify --quiet "refs/tags/$1"', source)
		self.assertIn('$0 != next_tag', source)

	def test_release_artifact_is_built_after_version_bump(self):
		source = WORKFLOW.read_text(encoding="utf-8")

		self.assertNotIn("uses: actions/download-artifact@v4", source)
		self.assertIn("python build_plugin.py", source)
		self.assertIn('manual_actions-${{ steps.release.outputs.target }}.py', source)
		self.assertIn('--target "${{ steps.release.outputs.target }}"', source)


if __name__ == "__main__":
	unittest.main()
