from __future__ import annotations

import ast
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

import build_plugin


class ValidationError(Exception):
	pass


def module_exists(path: Path) -> bool:
	return path.with_suffix(".py").is_file() or (path / "__init__.py").is_file()


def validate_local_imports(core_path: Path) -> None:
	for path in core_path.rglob("*.py"):
		tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
		for node in ast.walk(tree):
			if not isinstance(node, ast.ImportFrom):
				continue
			if node.level:
				target = path.parent
				for _ in range(node.level - 1):
					target = target.parent
				if node.module:
					target = target.joinpath(*node.module.split("."))
			elif node.module and (node.module == "core" or node.module.startswith("core.")):
				target = core_path.parent.joinpath(*node.module.split("."))
			else:
				continue
			if not module_exists(target):
				raise ValidationError(f"Missing local module for {path}: {node.module or '.'}")


def validate_package_modules(root: Path) -> None:
	for name in build_plugin.PACKAGE_MODULES:
		if not (root / "core" / f"{name}.py").is_file():
			raise ValidationError(f"Missing builder module: {name}")


def validate_generated_source() -> None:
	source = build_plugin.build_source()
	try:
		tree = ast.parse(source)
	except SyntaxError as exc:
		raise ValidationError(f"Generated source is invalid: {exc}") from exc
	for node in ast.walk(tree):
		if isinstance(node, ast.ImportFrom) and (node.level or (node.module or "").startswith("core")):
			raise ValidationError("Generated source contains a local import.")


def validate_public_annotations(package_path: Path) -> None:
	for path in package_path.glob("*.py"):
		if path.name == "__init__.py":
			continue
		tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
		for node in ast.walk(tree):
			if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name.startswith("_"):
				continue
			arguments = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
			for argument in arguments:
				if argument.arg not in {"self", "cls"} and argument.annotation is None:
					raise ValidationError(f"Missing annotation for {path}:{node.name}:{argument.arg}")
			if node.returns is None:
				raise ValidationError(f"Missing return annotation for {path}:{node.name}")


def validate_project(root: Path = ROOT) -> None:
	validate_local_imports(root / "core")
	validate_package_modules(root)
	validate_generated_source()
	validate_public_annotations(root / "core" / "runtime")
	validate_public_annotations(root / "core" / "delivery")


def main() -> int:
	try:
		validate_project()
	except ValidationError as exc:
		print(f"Validation failed: {exc}", file=sys.stderr)
		return 1
	print("Project validation passed.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
