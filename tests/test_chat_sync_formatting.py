from __future__ import annotations

from types import SimpleNamespace
import unittest

from core.chat_sync.formatting import (
	MAX_MESSAGE_LENGTH,
	RenderOptions,
	SPECIAL_SYMBOL,
	admin_tags,
	render_messages,
	strip_special_symbol,
)


class Message:
	def __init__(self, text="hello", author="buyer", author_id=7, chat_name="buyer", raw=None, **extra):
		self.text = text
		self.raw = raw
		self.author = author
		self.author_id = author_id
		self.chat_name = chat_name
		self.chat_id = 77
		self.badge = None
		self.by_bot = False
		self.by_vertex = False
		self.is_autoreply = False
		self.is_employee = False
		self.image_name = None
		self.interlocutor_id = 7
		for key, value in extra.items():
			setattr(self, key, value)

	def __str__(self):
		return self.raw if self.raw is not None else (self.text or "")


OPTIONS = RenderOptions(account_id=1)


class AuthorLabelTest(unittest.TestCase):
	def test_labels_the_interlocutor(self):
		chunks = render_messages([Message()], OPTIONS)

		self.assertIn("👤 buyer", chunks[0].text)
		self.assertIn("hello", chunks[0].text)

	def test_labels_own_messages(self):
		chunks = render_messages([Message(author="me", author_id=1, chat_name="buyer")], OPTIONS)

		self.assertIn("🫵 Вы", chunks[0].text)

	def test_labels_own_bot_messages(self):
		chunks = render_messages([Message(author="me", author_id=1, by_bot=True)], OPTIONS)

		self.assertIn("🤖 FPC", chunks[0].text)

	def test_labels_blacklisted_buyer(self):
		options = RenderOptions(account_id=1, blacklist=("buyer",))

		chunks = render_messages([Message()], options)

		self.assertIn("🚷 buyer", chunks[0].text)

	def test_repeats_are_grouped_under_one_label(self):
		chunks = render_messages([Message(text="one"), Message(text="two")], OPTIONS)

		self.assertEqual(chunks[0].text.count("👤 buyer"), 1)
		self.assertIn("one", chunks[0].text)
		self.assertIn("two", chunks[0].text)

	def test_switching_author_repeats_the_label(self):
		messages = [Message(text="one"), Message(text="two", author="me", author_id=1)]

		chunks = render_messages(messages, OPTIONS)

		self.assertIn("👤 buyer", chunks[0].text)
		self.assertIn("🫵 Вы", chunks[0].text)

	def test_hides_funpay_ads_when_disabled(self):
		advert = Message(text="реклама", author="FunPay", author_id=500, is_employee=True, badge="реклама", interlocutor_id=7)

		visible = render_messages([advert], RenderOptions(account_id=1, show_ads=True))
		hidden = render_messages([advert], RenderOptions(account_id=1, show_ads=False))

		self.assertIn("📣", visible[0].text)
		self.assertEqual(hidden, [])


class MessageBodyTest(unittest.TestCase):
	def test_escapes_html(self):
		chunks = render_messages([Message(text="<b>bold</b> & co")], OPTIONS)

		self.assertIn("&lt;b&gt;bold&lt;/b&gt; &amp; co", chunks[0].text)

	def test_renders_images_as_links_with_preview(self):
		image = Message(text=None, image_name="screenshot.png", raw="https://funpay.com/img/1.png")

		chunks = render_messages([image], OPTIONS)

		self.assertEqual(chunks[0].preview_url, "https://funpay.com/img/1.png")
		self.assertTrue(chunks[0].text.startswith(f'<a href="https://funpay.com/img/1.png">{SPECIAL_SYMBOL}</a>'))
		self.assertIn("screenshot.png", chunks[0].text)

	def test_applies_mono_font(self):
		chunks = render_messages([Message(text="plain")], RenderOptions(account_id=1, mono=True))

		self.assertIn("<code>plain</code>", chunks[0].text)

	def test_hides_watermark_for_own_bot_messages(self):
		options = RenderOptions(account_id=1, hide_watermark=True, watermark="🐦")
		message = Message(text="🐦\nreply", author_id=1, by_bot=True)

		chunks = render_messages([message], options)

		self.assertIn("<tg-spoiler>🐦</tg-spoiler>", chunks[0].text)
		self.assertIn("reply", chunks[0].text)

	def test_system_messages_are_emphasised(self):
		chunks = render_messages([Message(text="Заказ оплачен", author="FunPay", author_id=0)], OPTIONS)

		self.assertIn("<b><i>Заказ оплачен</i></b>", chunks[0].text)


class ChunkingTest(unittest.TestCase):
	def test_splits_long_conversations(self):
		messages = [Message(text="x" * 1000, author=f"user{index}", author_id=index + 10) for index in range(8)]

		chunks = render_messages(messages, OPTIONS)

		self.assertGreater(len(chunks), 1)
		for chunk in chunks:
			self.assertLessEqual(len(chunk.text), MAX_MESSAGE_LENGTH)

	def test_marks_chunks_containing_foreign_messages(self):
		own = render_messages([Message(author_id=1)], OPTIONS)
		foreign = render_messages([Message(author_id=7)], OPTIONS)

		self.assertTrue(own[0].only_self)
		self.assertFalse(foreign[0].only_self)

	def test_tags_admins_on_the_last_chunk_only(self):
		messages = [Message(text="y" * 1000, author=f"user{index}", author_id=index + 10) for index in range(8)]

		chunks = render_messages(messages, OPTIONS, tag_admins=True)

		self.assertTrue(chunks[-1].tag_admins)
		self.assertFalse(any(chunk.tag_admins for chunk in chunks[:-1]))

	def test_prefix_is_placed_first(self):
		chunks = render_messages([Message()], OPTIONS, prefix="Смотрит: лот\n\n")

		self.assertTrue(chunks[0].text.startswith("Смотрит: лот"))

	def test_empty_input_renders_nothing(self):
		self.assertEqual(render_messages([], OPTIONS), [])


class HelpersTest(unittest.TestCase):
	def test_strips_the_outgoing_marker(self):
		self.assertEqual(strip_special_symbol(f"{SPECIAL_SYMBOL}text"), "text")
		self.assertEqual(strip_special_symbol(None), "")

	def test_builds_admin_mentions(self):
		self.assertEqual(admin_tags([]), "")
		self.assertIn("tg://user?id=42", admin_tags([42]))


if __name__ == "__main__":
	unittest.main()
