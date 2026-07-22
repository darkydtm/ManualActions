from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any


class AtomicWriteError(RuntimeError):
	pass


def atomic_write_json(path: str | Path, data: Any, indent: int | str = 4) -> None:
	target = Path(path)
	temporary_path = None
	try:
		target.parent.mkdir(parents=True, exist_ok=True)
		with tempfile.NamedTemporaryFile(
			"w",
			encoding="utf-8",
			dir=target.parent,
			prefix=f".{target.name}.",
			delete=False,
		) as file:
			temporary_path = Path(file.name)
			json.dump(data, file, indent=indent, ensure_ascii=False)
			file.write("\n")
			file.flush()
			os.fsync(file.fileno())
		os.replace(temporary_path, target)
	except Exception as exc:
		if temporary_path:
			temporary_path.unlink(missing_ok=True)
		raise AtomicWriteError(f"Failed to write {target}.") from exc
