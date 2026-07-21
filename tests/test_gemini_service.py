from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from core.gemini.service import (
	OUTCOME_COMPLETED,
	OUTCOME_IGNORED,
	OUTCOME_SEND_FAILED,
	OUTCOME_WAITING_STOCK,
	GeminiDeliveryService,
	has_gemini_marker,
	normalize_order_amount,
)
from core.gemini.storage import (
	GeminiDeliveryStorage,
	STATUS_COMPLETED,
	STATUS_GIST_CREATED,
	STATUS_SEND_FAILED,
	STATUS_WAITING_STOCK,
)


LINK_ONE = "https://one.google.com/activate-plan/subscription/new/one"
LINK_TWO = "https://serviceactivation.google.com/subscription/new/two"


class GeminiDeliveryServiceTest(unittest.TestCase):
	def setUp(self):
		self.temp_dir = TemporaryDirectory()
		self.storage = GeminiDeliveryStorage(Path(self.temp_dir.name) / "delivery.json")
		self.settings = {
			"gemini_delivery": {
				"enabled": True,
				"shortage_mode": "partial",
				"message_template": "Delivery: {link}",
			},
			"gist": {
				"token": "token",
				"visibility": "public",
				"filename": {"mode": "custom", "custom": "manual.md"},
			},
		}
		self.account = Mock()
		self.cardinal = SimpleNamespace(account=self.account, send_message=Mock(return_value=True), telegram=None)
		self.gist_creator = Mock(return_value=SimpleNamespace(url="raw-url"))
		self.topic_notifier = Mock(return_value=True)
		self.admin_notifier = Mock()
		self.service = GeminiDeliveryService(
			self.cardinal,
			lambda: self.settings,
			self.storage,
			gist_creator=self.gist_creator,
			topic_notifier=self.topic_notifier,
			admin_notifier=self.admin_notifier,
		)

	def tearDown(self):
		self.temp_dir.cleanup()

	def order(
		self,
		order_id="ORDER-1",
		amount=1,
		full_description="#GeminiLink",
		description="Short description",
		chat_id=77,
		buyer_username="buyer",
	):
		return SimpleNamespace(
			id=order_id,
			amount=amount,
			full_description=full_description,
			description=description,
			title="Title",
			chat_id=chat_id,
			buyer_username=buyer_username,
		)

	def event(self, order=None):
		order = order or self.order()
		self.account.get_order.return_value = order
		return SimpleNamespace(order=order)

	def test_detects_marker_case_insensitively(self):
		self.assertTrue(has_gemini_marker("Text #GeminiLink text"))
		self.assertTrue(has_gemini_marker("#geminilink"))
		self.assertFalse(has_gemini_marker("#GeminiLinks"))

	def test_normalizes_order_amount(self):
		self.assertEqual(normalize_order_amount(3), 3)
		self.assertEqual(normalize_order_amount("2"), 2)
		self.assertEqual(normalize_order_amount(0), 1)
		self.assertEqual(normalize_order_amount(True), 1)
		self.assertEqual(normalize_order_amount("bad"), 1)

	def test_ignores_order_without_marker(self):
		outcome = self.service.handle_new_order(self.event(self.order(full_description="Other")))

		self.assertEqual(outcome.status, OUTCOME_IGNORED)
		self.gist_creator.assert_not_called()

	def test_uses_fetched_full_description(self):
		event_order = self.order(full_description="", description="Short")
		full_order = self.order(full_description="Details #GeminiLink")
		self.account.get_order.return_value = full_order
		self.storage.add_links((LINK_ONE,))

		outcome = self.service.handle_new_order(SimpleNamespace(order=event_order))

		self.assertEqual(outcome.status, OUTCOME_COMPLETED)

	def test_falls_back_to_event_description_when_fetch_fails(self):
		order = self.order(full_description="", description="Short #GeminiLink")
		self.account.get_order.side_effect = RuntimeError("offline")
		self.storage.add_links((LINK_ONE,))

		outcome = self.service.handle_new_order(SimpleNamespace(order=order))

		self.assertEqual(outcome.status, OUTCOME_COMPLETED)

	def test_disabled_delivery_does_nothing(self):
		self.settings["gemini_delivery"]["enabled"] = False
		self.storage.add_links((LINK_ONE,))

		outcome = self.service.handle_new_order(self.event())

		self.assertEqual(outcome.status, OUTCOME_IGNORED)
		self.assertEqual(self.storage.stock_count(), 1)

	def test_creates_secret_gist_and_sends_template(self):
		self.storage.add_links((LINK_ONE, LINK_TWO))

		outcome = self.service.handle_new_order(self.event(self.order(amount=2)))

		self.assertEqual(outcome.status, OUTCOME_COMPLETED)
		gist_settings, text = self.gist_creator.call_args.args[:2]
		self.assertEqual(gist_settings["token"], "token")
		self.assertEqual(gist_settings["visibility"], "secret")
		self.assertEqual(text, f"{LINK_ONE}\n{LINK_TWO}")
		self.assertEqual(self.gist_creator.call_args.kwargs["filename"], "ORDER-1.txt")
		self.cardinal.send_message.assert_called_once_with(
			chat_id=77,
			message_text="Delivery: raw-url",
		)
		self.assertEqual(self.storage.get_order("ORDER-1")["status"], STATUS_COMPLETED)

	def test_partial_delivery_warns_chat_sync(self):
		self.storage.add_links((LINK_ONE,))

		outcome = self.service.handle_new_order(self.event(self.order(amount=2)))

		self.assertEqual(outcome.status, OUTCOME_COMPLETED)
		warning = self.topic_notifier.call_args.args[1]
		self.assertIn("Требуется: 2", warning)
		self.assertIn("Выдано: 1", warning)

	def test_shortage_warns_buyer_topic_and_administrators(self):
		self.storage.add_links((LINK_ONE,))

		self.service.handle_new_order(self.event(self.order(amount=2)))

		warning = self.shortage_warning()
		self.cardinal.send_message.assert_any_call(chat_id=77, message_text=warning)
		self.assertEqual(self.topic_notifier.call_args.args[1], warning)
		self.admin_notifier.assert_called_once_with(warning)

	def test_shortage_continues_when_buyer_notification_fails(self):
		self.storage.add_links((LINK_ONE,))
		self.cardinal.send_message.side_effect = RuntimeError("offline")

		self.service.handle_new_order(self.event(self.order(amount=2)))

		self.assertEqual(self.topic_notifier.call_args_list[0].args[1], self.shortage_warning())
		self.admin_notifier.assert_called_once()

	def test_empty_stock_waits_and_warns_only_once(self):
		event = self.event(self.order(amount=2))

		first = self.service.handle_new_order(event)
		second = self.service.handle_new_order(event)

		self.assertEqual(first.status, OUTCOME_WAITING_STOCK)
		self.assertEqual(second.status, OUTCOME_WAITING_STOCK)
		self.assertEqual(self.topic_notifier.call_count, 1)
		self.assertEqual(self.storage.get_order("ORDER-1")["status"], STATUS_WAITING_STOCK)

	def test_all_or_nothing_warning_reports_available_stock(self):
		self.settings["gemini_delivery"]["shortage_mode"] = "all_or_nothing"
		self.storage.add_links((LINK_ONE,))

		outcome = self.service.handle_new_order(self.event(self.order(amount=2)))

		self.assertEqual(outcome.status, OUTCOME_WAITING_STOCK)
		self.assertIn("Осталось в стоке: 1", self.topic_notifier.call_args.args[1])
		self.assertEqual(self.storage.stock_links(), (LINK_ONE,))

	def test_missing_token_does_not_reserve_stock(self):
		self.settings["gist"]["token"] = ""
		self.storage.add_links((LINK_ONE,))

		outcome = self.service.handle_new_order(self.event())

		self.assertEqual(outcome.status, OUTCOME_IGNORED)
		self.assertEqual(self.storage.stock_count(), 1)
		self.assertIn("GitHub token", self.storage.get_order("ORDER-1")["last_error"])
		self.topic_notifier.assert_called_once()

	def test_missing_token_warning_is_not_repeated(self):
		self.settings["gist"]["token"] = ""
		event = self.event()

		self.service.handle_new_order(event)
		self.service.handle_new_order(event)

		self.topic_notifier.assert_called_once()

	def test_gist_failure_restores_stock(self):
		self.storage.add_links((LINK_ONE, LINK_TWO))
		self.gist_creator.side_effect = RuntimeError("GitHub failed")

		outcome = self.service.handle_new_order(self.event(self.order(amount=2)))

		self.assertEqual(outcome.status, OUTCOME_IGNORED)
		self.assertEqual(self.storage.stock_links(), (LINK_ONE, LINK_TWO))
		self.assertIn("GitHub failed", self.storage.get_order("ORDER-1")["last_error"])
		self.cardinal.send_message.assert_not_called()

	def test_send_failure_keeps_gist_and_warns_chat_sync(self):
		self.storage.add_links((LINK_ONE,))
		self.cardinal.send_message.side_effect = RuntimeError("send failed")

		outcome = self.service.handle_new_order(self.event())

		self.assertEqual(outcome.status, OUTCOME_SEND_FAILED)
		order = self.storage.get_order("ORDER-1")
		self.assertEqual(order["status"], STATUS_SEND_FAILED)
		self.assertEqual(order["raw_url"], "raw-url")
		self.assertEqual(self.storage.stock_count(), 0)
		self.assertIn("raw-url", self.topic_notifier.call_args.args[1])

	def test_completed_order_event_is_idempotent(self):
		self.storage.add_links((LINK_ONE, LINK_TWO))
		event = self.event()
		self.service.handle_new_order(event)

		outcome = self.service.handle_new_order(event)

		self.assertEqual(outcome.status, OUTCOME_COMPLETED)
		self.assertEqual(self.gist_creator.call_count, 1)
		self.assertEqual(self.storage.stock_links(), (LINK_TWO,))

	def test_resumes_gist_created_order_without_new_gist(self):
		self.storage.add_links((LINK_ONE,))
		request = self.service.order_request(self.order())
		self.storage.reserve(request, "partial")
		self.storage.mark_gist_created("ORDER-1", "saved-raw")

		outcome = self.service.handle_new_order(self.event())

		self.assertEqual(outcome.status, OUTCOME_COMPLETED)
		self.gist_creator.assert_not_called()
		self.cardinal.send_message.assert_called_once_with(
			chat_id=77,
			message_text="Delivery: saved-raw",
		)

	def test_retry_waiting_order_after_restock(self):
		self.service.handle_new_order(self.event())
		self.storage.add_links((LINK_ONE,))

		outcome = self.service.retry_order("ORDER-1")

		self.assertEqual(outcome.status, OUTCOME_COMPLETED)
		self.gist_creator.assert_called_once()

	def test_send_failed_order_event_is_not_retried(self):
		self.storage.add_links((LINK_ONE,))
		self.cardinal.send_message.return_value = False
		event = self.event()
		self.service.handle_new_order(event)
		self.cardinal.send_message.reset_mock()

		outcome = self.service.handle_new_order(event)

		self.assertEqual(outcome.status, OUTCOME_SEND_FAILED)
		self.cardinal.send_message.assert_not_called()

	def test_resolves_funpay_chat_by_buyer_name(self):
		self.storage.add_links((LINK_ONE,))
		self.account.get_chat_by_name.return_value = SimpleNamespace(id=88)

		outcome = self.service.handle_new_order(self.event(self.order(chat_id=None)))

		self.assertEqual(outcome.status, OUTCOME_COMPLETED)
		self.cardinal.send_message.assert_called_once_with(
			chat_id=88,
			message_text="Delivery: raw-url",
		)

	@staticmethod
	def shortage_warning():
		return (
			"⚠️ Нехватка Gemini-ссылок для заказа #ORDER-1.\n"
			"Требуется: 2\n"
			"Выдано: 1\n"
			"Осталось в стоке: 0"
		)


if __name__ == "__main__":
	unittest.main()
