from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.application.updater import (
	ManualActionsUpdater,
	UpdaterError,
	asset_download_url,
	fetch_latest_release,
	install_plugin_update,
	is_newer_version,
	should_offer_release,
)


class FakeResponse:
	def __init__(self, data):
		self.data = data

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc, traceback):
		return False

	def read(self):
		if isinstance(self.data, bytes):
			return self.data
		return json.dumps(self.data).encode("utf-8")


def release(version="1.3.1", draft=False, asset_name="manual_actions.py"):
	return {
		"tag_name": version,
		"name": f"V{version}",
		"html_url": f"https://github.com/darkydtm/ManualActions/releases/tag/{version}",
		"draft": draft,
		"prerelease": True,
		"assets": [
			{
				"name": asset_name,
				"browser_download_url": f"https://github.com/darkydtm/ManualActions/releases/download/{version}/{asset_name}",
			},
		],
	}


class UpdaterTest(unittest.TestCase):
	def test_compares_semantic_versions(self):
		self.assertTrue(is_newer_version("1.3.0", "1.3.1"))
		self.assertTrue(is_newer_version("v1.3.0", "1.4.0"))
		self.assertFalse(is_newer_version("1.3.0", "1.3.0"))
		self.assertFalse(is_newer_version("1.3.0", "1.2.9"))
		self.assertFalse(is_newer_version("1.3.0", "build-12"))

	def test_selects_manual_actions_asset(self):
		data = release(asset_name="manual_actions.py")

		self.assertEqual(
			asset_download_url(data, "manual_actions.py"),
			"https://github.com/darkydtm/ManualActions/releases/download/1.3.1/manual_actions.py",
		)

	def test_fetches_sha_named_manual_actions_asset(self):
		def request_func(request, timeout=15):
			return FakeResponse([release("1.3.1", asset_name="manual_actions-abc123.py")])

		result = fetch_latest_release(request_func)

		self.assertEqual(
			result.asset_url,
			"https://github.com/darkydtm/ManualActions/releases/download/1.3.1/manual_actions-abc123.py",
		)

	def test_fetches_first_non_draft_release(self):
		requests = []

		def request_func(request, timeout=15):
			requests.append((request, timeout))
			return FakeResponse([release("1.3.2", draft=True), release("1.3.1")])

		result = fetch_latest_release(request_func)

		self.assertEqual(result.version, "1.3.1")
		self.assertEqual(result.asset_url, "https://github.com/darkydtm/ManualActions/releases/download/1.3.1/manual_actions.py")
		self.assertIn("api.github.com", requests[0][0].full_url)
		self.assertEqual(requests[0][1], 15)

	def test_rejects_release_without_plugin_asset(self):
		def request_func(request, timeout=15):
			return FakeResponse([release(asset_name="other.py")])

		with self.assertRaises(UpdaterError):
			fetch_latest_release(request_func)

	def test_should_offer_release_uses_release_identity(self):
		self.assertTrue(should_offer_release("1.3.0", {}, "1.3.1"))
		self.assertFalse(should_offer_release("1.3.0", {}, "1.0.5"))
		self.assertTrue(should_offer_release("1.3.0", {}, "build-12"))
		self.assertFalse(should_offer_release("1.3.0", {}, "1.3.0"))
		self.assertFalse(should_offer_release("1.3.0", {"installed_version": "1.0.5"}, "1.0.5"))
		self.assertFalse(should_offer_release("1.3.0", {"skipped_version": "1.0.5"}, "1.0.5"))

	def test_installs_update_as_canonical_manual_actions_file(self):
		with tempfile.TemporaryDirectory() as directory:
			current = Path(directory) / "manual_actions91238.py"
			target = Path(directory) / "manual_actions.py"
			current.write_text("OLD = True\n", encoding="utf-8")

			result = install_plugin_update(current, b"NEW = True\n")

			self.assertEqual(result, target)
			self.assertFalse(current.exists())
			self.assertEqual(target.read_text(encoding="utf-8"), "NEW = True\n")

	def test_installs_update_from_main_py_to_canonical_file(self):
		with tempfile.TemporaryDirectory() as directory:
			current = Path(directory) / "main.py"
			target = Path(directory) / "manual_actions.py"
			current.write_text("OLD = True\n", encoding="utf-8")

			result = install_plugin_update(current, b"NEW = True\n")

			self.assertEqual(result, target)
			self.assertFalse(current.exists())
			self.assertEqual(target.read_text(encoding="utf-8"), "NEW = True\n")

	def test_replaces_current_canonical_manual_actions_file(self):
		with tempfile.TemporaryDirectory() as directory:
			current = Path(directory) / "manual_actions.py"
			current.write_text("OLD = True\n", encoding="utf-8")

			result = install_plugin_update(current, b"NEW = True\n")

			self.assertEqual(result, current)
			self.assertEqual(current.read_text(encoding="utf-8"), "NEW = True\n")

	def test_rejects_invalid_python_update(self):
		with tempfile.TemporaryDirectory() as directory:
			current = Path(directory) / "manual_actions.py"
			current.write_text("OLD = True\n", encoding="utf-8")

			with self.assertRaises(UpdaterError):
				install_plugin_update(current, b"def bad(:\n")

			self.assertEqual(current.read_text(encoding="utf-8"), "OLD = True\n")

	def test_enabled_mode_installs_latest_release(self):
		with tempfile.TemporaryDirectory() as directory:
			current = Path(directory) / "manual_actions91238.py"
			current.write_text("OLD = True\n", encoding="utf-8")
			settings = {"updater": {"mode": "enabled", "installed_version": "", "skipped_version": ""}}
			saved = []

			def request_func(request, timeout=15):
				if request.full_url.endswith("releases?per_page=10"):
					return FakeResponse([release("1.3.1")])
				return FakeResponse(b"NEW = True\n")

			installed = []
			updater = ManualActionsUpdater(
				settings,
				lambda: saved.append(settings["updater"].copy()),
				current,
				"1.3.0",
				on_update_installed=lambda found, path: installed.append((found.version, path.name)),
				request_func=request_func,
			)

			result = updater.check_once()

			self.assertTrue(result.update_available)
			self.assertEqual(settings["updater"]["installed_version"], "1.3.1")
			self.assertEqual(settings["updater"]["last_checked_version"], "1.3.1")
			self.assertEqual(installed, [("1.3.1", "manual_actions.py")])
			self.assertTrue(saved)

	def test_ask_mode_notifies_without_installing(self):
		settings = {"updater": {"mode": "ask", "installed_version": "", "skipped_version": "", "notified_version": ""}}
		available = []

		def request_func(request, timeout=15):
			return FakeResponse([release("1.3.1")])

		updater = ManualActionsUpdater(
			settings,
			lambda: None,
			"manual_actions.py",
			"1.3.0",
			on_update_available=lambda found: available.append(found.version),
			request_func=request_func,
		)

		result = updater.check_once()

		self.assertTrue(result.update_available)
		self.assertEqual(available, ["1.3.1"])
		self.assertEqual(settings["updater"]["notified_version"], "1.3.1")

		result = updater.check_once()

		self.assertFalse(result.update_available)
		self.assertEqual(available, ["1.3.1"])

	def test_disabled_mode_does_not_poll_github(self):
		settings = {"updater": {"mode": "disabled", "installed_version": "", "skipped_version": ""}}

		def request_func(request, timeout=15):
			raise AssertionError("disabled updater must not poll GitHub")

		updater = ManualActionsUpdater(
			settings,
			lambda: None,
			"manual_actions.py",
			"1.3.0",
			request_func=request_func,
		)

		result = updater.check_once()

		self.assertFalse(result.update_available)
		self.assertEqual(result.message, "disabled")

	def test_manual_check_polls_when_updater_is_disabled(self):
		settings = {"updater": {"mode": "disabled", "installed_version": "", "skipped_version": "", "notified_version": ""}}

		def request_func(request, timeout=15):
			return FakeResponse([release("1.3.1")])

		updater = ManualActionsUpdater(
			settings,
			lambda: None,
			"manual_actions.py",
			"1.3.0",
			request_func=request_func,
		)

		result = updater.check_manually()

		self.assertTrue(result.update_available)
		self.assertEqual(result.message, "available")
		self.assertEqual(settings["updater"]["last_checked_version"], "1.3.1")

	def test_manual_check_reports_release_after_automatic_notification(self):
		settings = {"updater": {"mode": "ask", "installed_version": "", "skipped_version": "", "notified_version": ""}}

		def request_func(request, timeout=15):
			return FakeResponse([release("1.5.3")])

		updater = ManualActionsUpdater(
			settings,
			lambda: None,
			"manual_actions.py",
			"1.5.2",
			request_func=request_func,
		)

		self.assertEqual(updater.check_once().message, "available")
		self.assertEqual(settings["updater"]["notified_version"], "1.5.3")
		self.assertEqual(updater.check_manually().message, "available")

	def test_poll_interval_reads_settings_value(self):
		settings = {"updater": {"mode": "ask", "check_interval_seconds": 1800}}
		updater = ManualActionsUpdater(
			settings,
			lambda: None,
			"manual_actions.py",
			"1.3.0",
		)

		self.assertEqual(updater.poll_interval(), 1800)

	def test_poll_interval_falls_back_to_default(self):
		settings = {"updater": {"mode": "ask", "check_interval_seconds": 0}}
		updater = ManualActionsUpdater(
			settings,
			lambda: None,
			"manual_actions.py",
			"1.3.0",
			poll_interval=120,
		)

		self.assertEqual(updater.poll_interval(), 120)

	def test_skipped_release_is_not_reported_again(self):
		settings = {"updater": {"mode": "ask", "installed_version": "", "skipped_version": "1.3.1"}}
		available = []

		def request_func(request, timeout=15):
			return FakeResponse([release("1.3.1")])

		updater = ManualActionsUpdater(
			settings,
			lambda: None,
			"manual_actions.py",
			"1.3.0",
			on_update_available=lambda found: available.append(found.version),
			request_func=request_func,
		)

		result = updater.check_once()

		self.assertFalse(result.update_available)
		self.assertEqual(available, [])


if __name__ == "__main__":
	unittest.main()
