from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from core.modules.auto_dumping.module import MODULE, create_services
from core.modules.auto_dumping.settings import DEFAULT_AUTO_DUMPING_SETTINGS


class AutoDumpingModuleTest(unittest.TestCase):
	def test_registers_auto_dumping_settings_section(self):
		self.assertEqual(MODULE.name, "auto_dumping")
		self.assertEqual(MODULE.settings_sections[0].key, "auto_dumping")

	def test_creates_service_scheduler_and_telegram_flow(self):
		host = SimpleNamespace(
			cardinal=SimpleNamespace(),
			settings={"auto_dumping": DEFAULT_AUTO_DUMPING_SETTINGS.copy()},
			send_telegram_admin_message=Mock(),
		)

		services = create_services(host)

		self.assertIn("auto_dumping_service", services)
		self.assertIn("auto_dumping_scheduler", services)
		self.assertIn("auto_dumping_flow", services)
		self.assertIs(services["auto_dumping_flow"].service, services["auto_dumping_service"])


if __name__ == "__main__":
	unittest.main()
