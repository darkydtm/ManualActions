from __future__ import annotations

from dataclasses import dataclass, field
from html import escape as html_escape
from typing import Any, Iterable, Sequence


SPECIAL_SYMBOL = "⁢"
MAX_MESSAGE_LENGTH = 4096

YOU_LABEL = "Вы"
SUPPORT_LABEL = "поддержка"
PHOTO_LABEL = "Фото"


@dataclass(frozen=True)
class RenderOptions:
	account_id: Any = None
	blacklist: tuple[str, ...] = ()
	chat_url: bool = False
	mono: bool = False
	show_ads: bool = True
	show_image_name: bool = True
	hide_watermark: bool = False
	watermark: str = ""


@dataclass
class RenderedChunk:
	text: str
	preview_url: str = ""
	only_self: bool = True
	tag_admins: bool = False


@dataclass
class _Block:
	author: str
	body: str
	preview_url: str = ""
	is_self: bool = False
	signature: tuple = field(default_factory=tuple)


def escape(text: Any) -> str:
	return html_escape(str(text), quote=False)


def strip_special_symbol(text: str | None) -> str:
	return (text or "").replace(SPECIAL_SYMBOL, "")


def is_own_message(message: Any, options: RenderOptions) -> bool:
	account_id = options.account_id
	return account_id is not None and str(getattr(message, "author_id", None)) == str(account_id)


def author_signature(message: Any) -> tuple:
	return (
		getattr(message, "author_id", None),
		bool(getattr(message, "by_bot", False)),
		getattr(message, "badge", None),
		bool(getattr(message, "by_vertex", False)),
	)


def author_label(message: Any, options: RenderOptions) -> str | None:
	author = str(getattr(message, "author", "") or "")
	chat_id = getattr(message, "chat_id", "")
	author_text = (
		f"<a href='https://funpay.com/chat/?node={chat_id}'>{escape(author)}</a>"
		if options.chat_url
		else escape(author)
	)
	badge = getattr(message, "badge", None)
	author_id = getattr(message, "author_id", None)

	if is_own_message(message, options):
		if getattr(message, "is_autoreply", False):
			return f"<i><b>📦 {YOU_LABEL} ({escape(badge)}):</b></i> "
		if getattr(message, "by_bot", False):
			return f"<i><b>🤖 FPC:</b></i> "
		return f"<i><b>🫵 {YOU_LABEL}:</b></i> "

	if author_id == 0:
		return f"<i><b>🔵 {author_text}: </b></i>"

	if getattr(message, "is_employee", False):
		if author_id == 500 and getattr(message, "interlocutor_id", None) != 500:
			if not options.show_ads:
				return None
			return f"<i><b>📣 {author_text} ({escape(badge)}): </b></i>"
		return f"<i><b>🆘 {author_text} ({escape(badge)}): </b></i>"

	if author == str(getattr(message, "chat_name", "") or ""):
		if getattr(message, "is_autoreply", False):
			return f"<i><b>🛍️ {author_text} ({escape(badge)}):</b></i> "
		if author in options.blacklist:
			return f"<i><b>🚷 {author_text}: </b></i>"
		if getattr(message, "by_bot", False):
			return f"<i><b>🐦 {author_text}: </b></i>"
		if getattr(message, "by_vertex", False):
			return f"<i><b>🐺 {author_text}: </b></i>"
		return f"<i><b>👤 {author_text}: </b></i>"

	return f"<i><b>🆘 {author_text} {SUPPORT_LABEL}: </b></i>"


def message_body(message: Any, options: RenderOptions) -> tuple[str, str]:
	raw = str(message)
	if not getattr(message, "text", None):
		image_name = getattr(message, "image_name", None)
		hide_name = is_own_message(message, options) and getattr(message, "by_bot", False)
		label = image_name if options.show_image_name and not hide_name and image_name else PHOTO_LABEL
		return f'<a href="{raw}">{escape(label)}</a>', raw

	if getattr(message, "author_id", None) == 0:
		return f"<b><i>{escape(raw)}</i></b>", ""

	hidden_watermark = False
	text = raw
	if (
		options.hide_watermark
		and options.watermark
		and is_own_message(message, options)
		and getattr(message, "by_bot", False)
		and text.startswith(f"{options.watermark}\n")
	):
		text = text.replace(options.watermark, "", 1)
		hidden_watermark = True

	body = escape(text)
	if options.mono:
		body = f"<code>{body}</code>"
	if hidden_watermark:
		body = f"<tg-spoiler>🐦</tg-spoiler>{body}"
	return body, ""


def build_blocks(messages: Sequence[Any], options: RenderOptions) -> list[_Block]:
	blocks: list[_Block] = []
	previous_signature: tuple | None = None
	for message in messages:
		author = author_label(message, options)
		if author is None:
			continue

		signature = author_signature(message)
		body, preview_url = message_body(message, options)
		blocks.append(_Block(
			author="" if signature == previous_signature else author,
			body=body,
			preview_url=preview_url,
			is_self=is_own_message(message, options),
			signature=signature,
		))
		previous_signature = signature
	return blocks


def render_messages(
	messages: Sequence[Any],
	options: RenderOptions,
	tag_admins: bool = False,
	prefix: str = "",
) -> list[RenderedChunk]:
	blocks = build_blocks(messages, options)
	if not blocks:
		return []

	chunks: list[RenderedChunk] = []
	current = RenderedChunk(text=prefix)
	for block in blocks:
		piece = f"{block.author}{block.body}\n\n"
		if current.text and len(current.text) + len(piece) > MAX_MESSAGE_LENGTH:
			chunks.append(current)
			current = RenderedChunk(text="")

		current.text += piece
		if not block.is_self:
			current.only_self = False
		if block.preview_url and not current.preview_url:
			current.preview_url = block.preview_url

	chunks.append(current)

	rendered = []
	for chunk in chunks:
		text = chunk.text.rstrip()
		if not text:
			continue
		if chunk.preview_url:
			text = f'<a href="{chunk.preview_url}">{SPECIAL_SYMBOL}</a>{text}'
		rendered.append(RenderedChunk(
			text=text,
			preview_url=chunk.preview_url,
			only_self=chunk.only_self,
			tag_admins=False,
		))

	if rendered and tag_admins:
		rendered[-1].tag_admins = True
	return rendered


def admin_tags(user_ids: Iterable[Any]) -> str:
	links = [f"<a href='tg://user?id={user_id}'>{SPECIAL_SYMBOL}</a>" for user_id in user_ids]
	return (" " + " ".join(links)) if links else ""
