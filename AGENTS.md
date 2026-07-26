# Project Notes For Agents

## Project

This repository contains `Manual Actions`, a FunPay Cardinal plugin.

The plugin entry point is `main.py`. Keep this file small because Cardinal loads it directly. Implementation lives in `core/`.

## Current Features

- Built-in Chat Sync mirrors FunPay chats into Telegram forum topics using only the Cardinal bot.
- Chat Sync can import the group, settings, and topic links from the standalone `745ed27e-...` plugin, offers that
  import once on startup, and warns admins while the standalone plugin is still installed.
- Telegram `/refund [order_id]` refunds an order after confirmation.
- Telegram `/refund` inside a Chat Sync topic resolves the buyer from the topic and offers pending paid orders.
- Telegram `/bl [username]` toggles Cardinal blacklist state.
- Telegram `/bl` inside a Chat Sync topic resolves the username from the topic.
- Telegram `/bl_list` opens the blacklist page.
- Telegram `/profit` and the settings page count profit for day, week, month, all time, or a custom date range. Closed orders always count; paid orders count while `profit.include_paid` is enabled.
- FunPay `!status` sends the configured text for the current status.
- Telegram `/status [0/1/2]` sets the current status.
- Telegram `/status` without an argument toggles only between `0` and `1`; if the current status is `2`, it switches to `0`.
- Status `2` is only selected manually with `/status 2` or through the settings page.
- Automatic FunPay status messages are configured separately for each status and can be enabled or disabled per status.

## Status States

- `0` - `Недоступен`
- `1` - `Доступен`
- `2` - `Сильная загруженность`

Settings are stored in `storage/plugins/manual_actions/settings.json`.

## Source Layout

- `main.py` - Cardinal metadata and `BIND_TO_PRE_INIT`.
- `core/application/` - plugin lifecycle and updater.
- `core/config/` - metadata, settings, callback IDs, and paths.
- `core/runtime/` - atomic persistence, settings transactions, locks, effects, and structured logging.
- `core/delivery/` - auto-delivery orchestration.
- `core/gemini/` and `core/gpt_accounts/` - supported auto-delivery providers.
- `core/chat_sync/` - the Chat Sync implementation: settings, topic storage, rate-limited dispatcher, message formatting, service, Telegram handlers, and settings UI.
- `core/funpay/` - event extraction, Chat Sync lookup helpers, orders, blacklist, and lots.
- `core/gist/`, `core/two_factor/`, `core/status/`, and `core/telegram/` - domain services and Telegram UI.
- `build_plugin.py` - optional single-file builder for generated `dist/manual_actions.py`.
- `tests/` - unit, integration-boundary, and generated-source tests.
- `examples/` - ignored reference plugins. Do not edit unless explicitly asked.

## Chat Sync

Chat Sync is native to this plugin - the standalone `745ed27e-...` plugin is no longer required. It needs exactly one
Telegram bot: the Cardinal bot, added to a forum group as an administrator with the "Manage topics" right.

- `core/chat_sync/registry.py` holds the active service. `core/funpay/chat_sync.py` reads it and keeps the old lookup
  API (`find_chat_sync_topic`, `get_topic_context`, `is_in_sync_chat`) working for orders, lots, gist, and delivery.
  If the standalone plugin is still installed, that lookup falls back to its `cs_obj`.
- Topic creation is serialized per FunPay chat through `KeyedLockRegistry` and re-checked inside the lock, then saved
  immediately. This is what prevents two topics for one chat.
- `ChatSyncStorage` drops entries that share a `thread_id` when loading, cleaning up duplicates written by old versions.
- A new topic is backfilled with the last `history_depth` messages, and `last_message_id` per topic keeps those
  messages from being posted twice when a live event arrives for the same message.
- One bot means Telegram rate limits apply. `TelegramRateLimiter` is a token bucket (`messages_per_minute`, default 20)
  and `TelegramSender` retries on 429 using `retry_after`. `ChatSyncQueue` keeps deliveries ordered on one worker.
- Cardinal notifications for the sync group should stay off, otherwise messages are duplicated in "General".

Topics are stored in `storage/plugins/manual_actions/chat_sync_topics.json`.

## Chat Sync Import

`core/chat_sync/importer.py` reads the standalone plugin's `storage/plugins/745ed27e-.../settings.json` and
`threads.json`, maps its setting names to the built-in ones, and builds an `ImportPlan`. Nothing touches disk until
`ChatSyncService.apply_import` runs.

- Bots and tokens are never imported - the built-in Chat Sync runs on the Cardinal bot only.
- A legacy thread is skipped when its FunPay chat or its `thread_id` is already linked, so re-importing is safe.
- When the legacy group differs from the bound one, the import replaces the group and drops the current topic links -
  they belong to another group.
- `ImportPlan.settings` keeps only the flags that differ from the current config, so `changes` reports real work.
- Imported records have no username until `resolve_usernames` (one `get_chats` call) or `remember_username` fills it in
  from a delivered message.
- `import_offered` in the Chat Sync settings keeps the startup offer from repeating. `register_telegram` calls
  `announce_legacy_plugin`, which warns admins while the standalone plugin is still loaded (`legacy_plugin_installed`
  scans `sys.modules` for its UUID) and offers the import once.

## Important Behavior

`!status` must not trigger the automatic status message. It sends only the configured response text.

Automatic status messages must run only for incoming non-system FunPay messages from the other participant. They must not run for seller messages, bot messages, system messages, or `!status`.

If a status response text is empty, `!status` falls back to `Текущий статус: <label>`.

Blacklist response behavior follows Cardinal state: if the author is blacklisted and `bl_response_enabled` is set, the status response is skipped.

## Git And Ignored Files

`docs/superpowers/` is ignored and must stay out of git.

Generated or local runtime paths are ignored:

- `dist/`
- `__pycache__/`
- `*.pyc`
- `storage/plugins/manual_actions/`
- `examples/`

Do not introduce the removed `chatgpt_accounts` package. The supported package is `core/gpt_accounts/`.

## Verification

Use these checks after code changes:

```bash
python -m unittest discover -s tests
python -m py_compile main.py build_plugin.py $(rg --files core tools -g '*.py')
python tools/validate_project.py
rg -n "chatgpt_accounts|ChatGPT Accounts" -g '!AGENTS.md' -g '!docs/superpowers/**' -g '!examples/**'
```

Do not run a local build unless the user explicitly asks. If a generated plugin is needed, use `build_plugin.py` only after explicit approval.

## Style Rules

- Use tabs for Python indentation.
- Keep code identifiers in English.
- Keep comments in English and use them only for non-obvious code.
- Use hyphen `-`, not long dash characters.
- Keep user-facing Russian text consistent with the existing plugin.
