# Task 2 Report

## Status

Task 2 is complete. The implementation is limited to callback constants, callback registration, pagination helpers, and focused tests. No Telegram screens or local blacklist UI were added.

## Implementation

- Replaced the two stale global-blacklist callback constants with six distinct auto-dumping callback prefixes:
  - `CBT_AUTO_DUMPING_STATUS`
  - `CBT_AUTO_DUMPING_PERIOD_PAGE`
  - `CBT_AUTO_DUMPING_RULES_PAGE`
  - `CBT_AUTO_DUMPING_BLACKLIST_PAGE`
  - `CBT_AUTO_DUMPING_BLACKLIST_ADD`
  - `CBT_AUTO_DUMPING_BLACKLIST_DELETE`
- Registered predicates for all six prefixes in `TelegramAutoDumpingFlow.register()`.
- Added `PAGE_SIZE = 5`.
- Added `_page_items()` to slice five items, return total pages, keep empty lists at one page, and clamp requested pages.
- Added `_page_callback()` and `_parse_page_callback()` for context plus zero-based page payloads.
- Added a temporary acknowledgement handler for the newly registered callbacks. Later screen tasks can replace these routes with their actual handlers without changing registration predicates.

## TDD

- RED: `python -m unittest tests.test_auto_dumping_telegram` failed during import because the new callback constants were absent.
- GREEN: focused tests passed after the implementation.
- Added coverage for five-item slicing, empty-list page count, page clamping, callback context/page round-tripping, and all six callback predicates.

## Verification

- Focused tests: `python -m unittest tests.test_auto_dumping_telegram` - 9 tests passed.
- Full suite: `python -m unittest discover -s tests` - 513 tests passed.
- Compilation: `python -m py_compile main.py build_plugin.py $(rg --files core tools -g '*.py')` - passed with exit code 0.
- Project validation: `python tools/validate_project.py` - `Project validation passed.`
- Removed package search: no `chatgpt_accounts` or `ChatGPT Accounts` matches.
- `git diff --check` - passed.

## Self-Review

- Only the three files named by the brief were modified.
- No generated plugin, runtime storage, examples, or unrelated untracked files were staged.
- No screen rendering, status behavior, rule pagination UI, local blacklist UI, or blacklist mutations were implemented.
- Callback page parsing preserves parent context and clamps invalid or negative pages to zero; list rendering clamps pages to the available range.

## Concerns

- The six new callback routes intentionally acknowledge callbacks only. Task 3 and Task 4 must replace `_pending_callback` registrations with their screen and mutation handlers.
- Callback contexts are colon-delimited and therefore should continue using values without unescaped colons, matching the planned rule/list payloads.

## Commit

- `15a9f2c` - `add auto-dumping menu pagination callbacks`

## Reviewer Fix

- Root cause: `_page_callback()` serialized the complete 32-character rule ID. The blacklist callback prefix plus `32-char-id:keywords:0` produced 74 bytes, exceeding Telegram's 64-byte `callback_data` limit.
- Replaced the rule ID segment with unpadded URL-safe base64 of the UUID's 16 raw bytes. The encoding is deterministic, requires no runtime map or unbounded state, and `_parse_page_callback()` expands it back to the original rule ID and list kind.
- Verified the longest required blacklist payload for a 32-character rule ID is exactly 64 UTF-8 bytes.
- Made page generation defensive for non-numeric values and page parsing defensive for wrong prefixes, malformed pages, and negative pages. Invalid values resolve to zero.
- Added focused tests for the 64-byte limit, rule-context round trip, malformed input, negative pages, and non-numeric page generation.

## Reviewer-Fix Verification

- RED: the new compact-payload test failed with a 74-byte callback, and the malformed-page test raised `ValueError` from `int("bad")`.
- GREEN: `python -m unittest tests.test_auto_dumping_telegram` - 11 tests passed.
- Full suite: `python -m unittest discover -s tests` - 515 tests passed.
- Compilation: `python -m py_compile main.py build_plugin.py $(rg --files core tools -g '*.py')` - passed with exit code 0.
- `git diff --check` - passed.

## Reviewer-Fix Concerns

- No runtime token map was introduced. Later tasks must use `_page_callback()` and `_parse_page_callback()` for blacklist page callbacks so rule IDs remain recoverable and within Telegram's limit.

## Reviewer-Fix Follow-Up

- Root cause: UUID raw-byte encoding was only valid for lowercase 32-character hexadecimal IDs and decoded uppercase IDs through `.hex()`, losing case. It also did not cover arbitrary normalized IDs.
- Rule contexts are now encoded as unpadded URL-safe base64 of their UTF-8 text before the list kind, preserving parent context, delimiters, and exact ID casing without runtime state. The blacklist page prefix is compacted to leave room for the encoded context.
- `normalize_rule` rejects IDs over 36 UTF-8 bytes, the maximum accepted size that fits the 64-byte Telegram callback limit with the current payload.
- Added tests for hyphenated/arbitrary IDs, uppercase IDs, exact round trips, malformed encoded input, and byte-length limits.
- Added a delimiter-preserving round-trip test and an exact 64-byte boundary test for the largest accepted ID.

## Reviewer-Fix Follow-Up Verification

- RED: focused tests failed because the hyphenated callback was 75 bytes and uppercase IDs decoded lowercase.
- GREEN: `python -m unittest tests.test_auto_dumping_telegram` - 12 tests passed.
- GREEN: `python -m unittest tests.test_auto_dumping_telegram` - 13 tests passed.
- Full suite: `python -m unittest discover -s tests` - 518 tests passed.
- `git diff --check` - passed.

## Final Verification

- `python -m unittest tests.test_auto_dumping_telegram` - 14 tests passed.
- `python -m unittest discover -s tests` - 519 tests passed.

## Remaining Review Finding Fix

- Root cause: the existing compact rule-context callback still serialized the page as an unbounded decimal suffix, so valid 36-byte rule IDs exceeded Telegram's 64-byte callback limit as page values grew.
- Replaced the page suffix with an unpadded base64url encoding of a bounded four-byte unsigned page number. Rule ID UTF-8 bytes, list kind, and page are encoded together, so decoding is exact without dependencies or runtime state.
- `MAX_CALLBACK_PAGE` is `4,294,967,295`; negative and malformed generated pages become zero, and larger generated pages clamp to the maximum. Parsing accepts the compact token and retains defensive decimal parsing for malformed or legacy payloads.
- Added a regression test for the maximum 36-byte rule ID at pages `0`, `10`, `123456789`, and `MAX_CALLBACK_PAGE`, asserting callback UTF-8 length `<= 64` and exact context/page round trips.

## Remaining Review Finding Verification

- Focused test: `python -m unittest tests.test_auto_dumping_telegram` - 15 tests passed.
- Full suite: `python -m unittest discover -s tests` - 520 tests passed.
- Full-suite output included expected simulated service and Telegram error logs; the command completed with `OK` and zero failures.

## Remaining Review Fix Commit

- `a683f05` - `fix auto-dumping callback page length`.
