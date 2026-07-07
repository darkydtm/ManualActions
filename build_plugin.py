from __future__ import annotations

import argparse
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ENTRY_FILE = ROOT / "manual_actions.py"
OUTPUT_FILE = ROOT / "dist" / "manual_actions.py"
PACKAGE_MODULES = [
	"constants",
	"status",
	"settings",
	"storage",
	"funpay",
	"blacklist",
	"orders",
	"chat_sync",
	"telegram_settings",
	"telegram_commands",
	"plugin",
]
LOCAL_IMPORT_PREFIXES = (
	"from .",
	"from manual_actions_core.",
)


def read_source(path: Path) -> str:
	return path.read_text(encoding="utf-8")


def strip_local_imports(source: str) -> str:
	lines = []
	skipping_local_import = False
	parentheses = 0

	for line in source.splitlines():
		stripped = line.strip()
		if skipping_local_import:
			parentheses += stripped.count("(") - stripped.count(")")
			if parentheses <= 0:
				skipping_local_import = False
			continue

		if stripped == "from __future__ import annotations":
			continue
		if stripped.startswith(LOCAL_IMPORT_PREFIXES):
			parentheses = stripped.count("(") - stripped.count(")")
			skipping_local_import = parentheses > 0
			continue
		lines.append(line)
	return "\n".join(lines).strip()


def build_source() -> str:
	sections = [
		"from __future__ import annotations",
		"",
		"# Do not edit this generated file directly.",
	]

	for module_name in PACKAGE_MODULES:
		path = ROOT / "manual_actions_core" / f"{module_name}.py"
		section = strip_local_imports(read_source(path))
		if section:
			sections.extend(["", "", section])

	entry_section = strip_local_imports(read_source(ENTRY_FILE))
	if entry_section:
		sections.extend(["", "", entry_section])

	return "\n".join(sections).rstrip() + "\n"


def write_output(source: str) -> None:
	OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
	OUTPUT_FILE.write_text(source, encoding="utf-8")


def main() -> int:
	parser = argparse.ArgumentParser(description="Build one Cardinal-compatible Manual Actions plugin file.")
	parser.add_argument(
		"--check",
		action="store_true",
		help="Validate generated source without writing dist output.",
	)
	args = parser.parse_args()

	source = build_source()
	ast.parse(source)

	if args.check:
		print(f"Generated source is valid: {len(source.splitlines())} lines")
		return 0

	write_output(source)
	print(f"Built {OUTPUT_FILE.relative_to(ROOT)}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
