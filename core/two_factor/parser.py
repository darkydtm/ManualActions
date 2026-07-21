from __future__ import annotations


def extract_secret(description: str, label: str) -> str | None:
	if not label:
		return None

	for line in (description or "").splitlines():
		if line.startswith(label):
			secret = line[len(label):].strip()
			return secret or None
	return None
