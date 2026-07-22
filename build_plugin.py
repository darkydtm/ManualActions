from __future__ import annotations

import argparse
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ENTRY_FILE = ROOT / "main.py"
OUTPUT_FILE = ROOT / "dist" / "manual_actions.py"
PACKAGE_MODULES = [
	"config/constants",
	"runtime/contracts",
	"runtime/locks",
	"runtime/effects",
	"runtime/logging",
	"delivery/contracts",
	"delivery/orchestrator",
	"status/status",
	"gist/settings",
	"gemini/settings",
	"gpt_accounts/settings",
	"lots/scheduling",
	"config/settings",
	"storage/storage",
	"application/updater",
	"common/payloads",
	"gemini/storage",
	"gpt_accounts/storage",
	"two_factor/commands",
	"two_factor/parser",
	"two_factor/totp",
	"two_factor/storage",
	"funpay/chat_sync",
	"funpay/messages",
	"funpay/blacklist",
	"funpay/lots",
	"funpay/orders",
	"telegram/ui",
	"telegram/blacklist",
	"telegram/lots",
	"telegram/orders",
	"gist/client",
	"gist/service",
	"gemini/service",
	"gpt_accounts/service",
	"two_factor/service",
	"gist/ui",
	"gist/telegram",
	"gemini/ui",
	"gpt_accounts/ui",
	"telegram/settings",
	"telegram/templates",
	"telegram/commands",
	"application/plugin",
]
class ImportCollector:
	def __init__(self):
		self.imports: list[tuple[str, str | None]] = []
		self.import_keys: set[tuple[str, str | None]] = set()
		self.from_imports: dict[tuple[int, str], list[tuple[str, str | None]]] = {}
		self.from_import_keys: set[tuple[int, str, str, str | None]] = set()
		self.type_imports: list[tuple[str, str | None]] = []
		self.type_import_keys: set[tuple[str, str | None]] = set()
		self.type_from_imports: dict[tuple[int, str], list[tuple[str, str | None]]] = {}
		self.type_from_import_keys: set[tuple[int, str, str, str | None]] = set()
		self.optional_import_blocks: list[str] = []
		self.optional_import_block_keys: set[str] = set()

	def add_statement(self, statement: ast.stmt, type_checking: bool = False) -> None:
		if isinstance(statement, ast.Import):
			self.add_import(statement.names, type_checking)
		elif isinstance(statement, ast.ImportFrom):
			self.add_from_import(statement.module or "", statement.level, statement.names, type_checking)

	def add_import(self, aliases: list[ast.alias], type_checking: bool = False) -> None:
		target = self.type_imports if type_checking else self.imports
		keys = self.type_import_keys if type_checking else self.import_keys

		for alias in aliases:
			key = (alias.name, alias.asname)
			if type_checking and key in self.import_keys:
				continue
			if key not in keys:
				keys.add(key)
				target.append(key)

	def add_from_import(
		self,
		module: str,
		level: int,
		aliases: list[ast.alias],
		type_checking: bool = False,
	) -> None:
		if module == "__future__":
			return
		target = self.type_from_imports if type_checking else self.from_imports
		keys = self.type_from_import_keys if type_checking else self.from_import_keys

		for alias in aliases:
			key = (level, module, alias.name, alias.asname)
			if type_checking and key in self.from_import_keys:
				continue
			if key not in keys:
				keys.add(key)
				target.setdefault((level, module), []).append((alias.name, alias.asname))

	def add_optional_import_block(self, block: str) -> None:
		if block not in self.optional_import_block_keys:
			self.optional_import_block_keys.add(block)
			self.optional_import_blocks.append(block)

	def ensure_type_checking_import(self) -> None:
		if self.type_imports or self.type_from_imports:
			alias = ast.alias(name="TYPE_CHECKING")
			self.add_from_import("typing", 0, [alias])

	def render_runtime_imports(self) -> list[str]:
		return self.render_imports(self.imports, self.from_imports)

	def render_type_checking_imports(self) -> list[str]:
		imports = [alias for alias in self.type_imports if alias not in self.import_keys]
		from_imports = {}
		for key, aliases in self.type_from_imports.items():
			level, module = key
			filtered_aliases = [
				(name, asname)
				for name, asname in aliases
				if (level, module, name, asname) not in self.from_import_keys
			]
			if filtered_aliases:
				from_imports[key] = filtered_aliases
		return self.render_imports(imports, from_imports)

	@staticmethod
	def render_imports(
		imports: list[tuple[str, str | None]],
		from_imports: dict[tuple[int, str], list[tuple[str, str | None]]],
	) -> list[str]:
		lines = []
		for name, asname in imports:
			lines.append(format_import_alias("import", name, asname))
		for (level, module), aliases in from_imports.items():
			names = ", ".join(format_alias(name, asname) for name, asname in sort_import_aliases(module, aliases))
			prefix = "." * level
			lines.append(f"from {prefix}{module} import {names}")
		return lines


def read_source(path: Path) -> str:
	return path.read_text(encoding="utf-8")


def format_alias(name: str, asname: str | None) -> str:
	if asname:
		return f"{name} as {asname}"
	return name


def format_import_alias(prefix: str, name: str, asname: str | None) -> str:
	return f"{prefix} {format_alias(name, asname)}"


def sort_import_aliases(module: str, aliases: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
	if module == "typing":
		return sorted(aliases, key=lambda item: (item[0] != "TYPE_CHECKING", item[0].lower(), item[1] or ""))
	return sorted(aliases, key=lambda item: (item[0].lower(), item[1] or ""))


def is_local_import(statement: ast.stmt) -> bool:
	if isinstance(statement, ast.Import):
		return any(alias.name == "core" or alias.name.startswith("core.") for alias in statement.names)
	if isinstance(statement, ast.ImportFrom):
		module = statement.module or ""
		return statement.level > 0 or module == "core" or module.startswith("core.")
	return False


def is_future_import(statement: ast.stmt) -> bool:
	return isinstance(statement, ast.ImportFrom) and statement.module == "__future__"


def is_type_checking_block(statement: ast.stmt) -> bool:
	return (
		isinstance(statement, ast.If)
		and isinstance(statement.test, ast.Name)
		and statement.test.id == "TYPE_CHECKING"
		and all(isinstance(item, (ast.Import, ast.ImportFrom)) for item in statement.body)
		and not statement.orelse
	)


def is_optional_import_block(statement: ast.stmt) -> bool:
	return (
		isinstance(statement, ast.Try)
		and bool(statement.body)
		and all(isinstance(item, (ast.Import, ast.ImportFrom)) for item in statement.body)
		and not statement.orelse
		and not statement.finalbody
	)


def remove_line_ranges(lines: list[str], ranges: list[tuple[int, int]]) -> str:
	removed = set()
	for start, end in ranges:
		removed.update(range(start, end + 1))
	return "\n".join(line for index, line in enumerate(lines, start=1) if index not in removed).strip()


def statement_source(lines: list[str], statement: ast.stmt) -> str:
	return "\n".join(lines[statement.lineno - 1:statement.end_lineno]).strip()


def extract_module_body(source: str, collector: ImportCollector) -> str:
	tree = ast.parse(source)
	lines = source.splitlines()
	remove_ranges = []

	for statement in tree.body:
		if isinstance(statement, (ast.Import, ast.ImportFrom)):
			if not is_future_import(statement) and not is_local_import(statement):
				collector.add_statement(statement)
			remove_ranges.append((statement.lineno, statement.end_lineno))
			continue

		if is_type_checking_block(statement):
			for item in statement.body:
				if not is_local_import(item):
					collector.add_statement(item, type_checking=True)
			remove_ranges.append((statement.lineno, statement.end_lineno))
			continue

		if is_optional_import_block(statement):
			collector.add_optional_import_block(statement_source(lines, statement))
			remove_ranges.append((statement.lineno, statement.end_lineno))

	return remove_line_ranges(lines, remove_ranges)


def build_source() -> str:
	collector = ImportCollector()
	module_sections = []

	for module_name in PACKAGE_MODULES:
		path = ROOT / "core" / f"{module_name}.py"
		section = extract_module_body(read_source(path), collector)
		if section:
			module_sections.append(section)

	entry_section = extract_module_body(read_source(ENTRY_FILE), collector)
	if entry_section:
		module_sections.append(entry_section)

	collector.ensure_type_checking_import()
	sections = ["from __future__ import annotations"]
	runtime_imports = collector.render_runtime_imports()
	if runtime_imports:
		sections.extend(["", *runtime_imports])

	type_imports = collector.render_type_checking_imports()
	if type_imports:
		sections.extend(["", "if TYPE_CHECKING:"])
		sections.extend(f"\t{line}" for line in type_imports)

	if collector.optional_import_blocks:
		for block in collector.optional_import_blocks:
			sections.extend(["", block])

	sections.extend(["", "# Do not edit this generated file directly."])
	for section in module_sections:
		sections.extend(["", "", section])

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
