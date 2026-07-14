from __future__ import annotations

import ast
import json
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


RELEASES_API_URL = "https://api.github.com/repos/darkydtm/ManualActions/releases?per_page=10"
PLUGIN_ASSET_NAME = "manual_actions.py"
PLUGIN_ASSET_PREFIX = "manual_actions"
TARGET_PLUGIN_NAME = "manual_actions.py"
UPDATER_USER_AGENT = "ManualActionsUpdater/1.0"
POLL_INTERVAL_SECONDS = 3600
MODE_ENABLED = "enabled"
MODE_DISABLED = "disabled"
MODE_ASK = "ask"


class UpdaterError(Exception):
	pass


@dataclass(frozen=True)
class UpdaterRelease:
	version: str
	title: str
	url: str
	asset_url: str


@dataclass(frozen=True)
class ReleaseCheckResult:
	release: UpdaterRelease | None
	update_available: bool
	message: str = ""


class ManualActionsUpdater:
	def __init__(
		self,
		settings: dict[str, Any],
		save_settings: Callable[[], None],
		plugin_file_path: str | Path,
		current_version: str,
		on_update_available: Callable[[UpdaterRelease], None] | None = None,
		on_update_installed: Callable[[UpdaterRelease, Path], None] | None = None,
		on_update_error: Callable[[Exception], None] | None = None,
		request_func: Callable[..., Any] = urlopen,
		poll_interval: int = POLL_INTERVAL_SECONDS,
	):
		self.settings = settings
		self.save_settings = save_settings
		self.plugin_file_path = Path(plugin_file_path).resolve()
		self.current_version = current_version
		self.on_update_available = on_update_available
		self.on_update_installed = on_update_installed
		self.on_update_error = on_update_error
		self.request_func = request_func
		self.poll_interval = poll_interval
		self._stop = threading.Event()
		self._thread: threading.Thread | None = None

	def start(self) -> None:
		if self.mode() == MODE_DISABLED:
			return
		if self._thread and self._thread.is_alive():
			return

		self._stop.clear()
		self._thread = threading.Thread(target=self._run, name="ManualActionsUpdater", daemon=True)
		self._thread.start()

	def stop(self) -> None:
		self._stop.set()
		if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
			self._thread.join(timeout=2)

	def check_once(self) -> ReleaseCheckResult:
		mode = self.mode()
		if mode == MODE_DISABLED:
			return ReleaseCheckResult(None, False, "disabled")

		release = fetch_latest_release(self.request_func)
		config = self.config()
		config["last_checked_version"] = release.version
		self.save_settings()

		if not should_offer_release(self.current_version, config, release.version):
			return ReleaseCheckResult(release, False, "not_new")

		if mode == MODE_ENABLED:
			path = self.install_release(release)
			if self.on_update_installed:
				self.on_update_installed(release, path)
			return ReleaseCheckResult(release, True, "installed")

		if self.on_update_available:
			self.on_update_available(release)
		return ReleaseCheckResult(release, True, "available")

	def install_latest(self, expected_version: str | None = None, notify: bool = True) -> Path:
		release = fetch_latest_release(self.request_func)
		if expected_version and release.version != expected_version:
			raise UpdaterError("Найден другой релиз. Откройте обновление заново.")
		path = self.install_release(release)
		if notify and self.on_update_installed:
			self.on_update_installed(release, path)
		return path

	def skip_version(self, version: str) -> None:
		self.config()["skipped_version"] = version.strip()
		self.save_settings()

	def install_release(self, release: UpdaterRelease) -> Path:
		source = download_release_asset(release.asset_url, self.request_func)
		path = install_plugin_update(self.plugin_file_path, source)
		config = self.config()
		config["installed_version"] = release.version
		if config.get("skipped_version") == release.version:
			config["skipped_version"] = ""
		self.save_settings()
		return path

	def mode(self) -> str:
		return str(self.config().get("mode", MODE_DISABLED))

	def config(self) -> dict[str, str]:
		return self.settings.setdefault("updater", {})

	def _run(self) -> None:
		while not self._stop.is_set():
			try:
				self.check_once()
			except Exception as exc:
				if self.on_update_error:
					self.on_update_error(exc)
			if self._stop.wait(self.poll_interval):
				break


def fetch_latest_release(request_func: Callable[..., Any] = urlopen, timeout: int = 15) -> UpdaterRelease:
	data = read_github_json(RELEASES_API_URL, request_func, timeout)
	release_data = first_public_release(data)
	if not release_data:
		raise UpdaterError("GitHub не вернул доступные релизы.")

	version = str(release_data.get("tag_name") or "").strip()
	if not version:
		raise UpdaterError("В релизе GitHub нет tag_name.")

	asset_url = plugin_asset_download_url(release_data)
	if not asset_url:
		raise UpdaterError(f"В релизе {version} нет файла manual_actions*.py.")

	return UpdaterRelease(
		version=version,
		title=str(release_data.get("name") or version),
		url=str(release_data.get("html_url") or ""),
		asset_url=asset_url,
	)


def read_github_json(url: str, request_func: Callable[..., Any], timeout: int) -> Any:
	request = Request(
		url,
		headers={
			"Accept": "application/vnd.github+json",
			"User-Agent": UPDATER_USER_AGENT,
		},
	)
	try:
		with request_func(request, timeout=timeout) as response:
			return json.loads(response.read().decode("utf-8"))
	except HTTPError as exc:
		raise UpdaterError(f"GitHub вернул HTTP {exc.code}.") from exc
	except URLError as exc:
		raise UpdaterError(f"Не удалось подключиться к GitHub: {exc.reason}") from exc
	except json.JSONDecodeError as exc:
		raise UpdaterError("GitHub вернул некорректный JSON.") from exc
	except Exception as exc:
		raise UpdaterError(f"Не удалось получить релиз GitHub: {exc}") from exc


def first_public_release(data: Any) -> dict[str, Any] | None:
	if isinstance(data, dict):
		return data if not data.get("draft") else None
	if not isinstance(data, list):
		return None

	for item in data:
		if isinstance(item, dict) and not item.get("draft"):
			return item
	return None


def asset_download_url(release_data: dict[str, Any], asset_name: str) -> str:
	assets = release_data.get("assets")
	if not isinstance(assets, list):
		return ""

	for asset in assets:
		if not isinstance(asset, dict):
			continue
		if asset.get("name") == asset_name and isinstance(asset.get("browser_download_url"), str):
			return asset["browser_download_url"]
	return ""


def plugin_asset_download_url(release_data: dict[str, Any]) -> str:
	exact = asset_download_url(release_data, PLUGIN_ASSET_NAME)
	if exact:
		return exact

	assets = release_data.get("assets")
	if not isinstance(assets, list):
		return ""

	for asset in assets:
		if not isinstance(asset, dict):
			continue
		name = asset.get("name")
		url = asset.get("browser_download_url")
		if (
			isinstance(name, str)
			and isinstance(url, str)
			and name.startswith(PLUGIN_ASSET_PREFIX)
			and name.endswith(".py")
		):
			return url
	return ""


def download_release_asset(
	asset_url: str,
	request_func: Callable[..., Any] = urlopen,
	timeout: int = 30,
) -> bytes:
	request = Request(
		asset_url,
		headers={
			"Accept": "application/octet-stream",
			"User-Agent": UPDATER_USER_AGENT,
		},
	)
	try:
		with request_func(request, timeout=timeout) as response:
			data = response.read()
	except HTTPError as exc:
		raise UpdaterError(f"GitHub вернул HTTP {exc.code} при скачивании.") from exc
	except URLError as exc:
		raise UpdaterError(f"Не удалось скачать обновление: {exc.reason}") from exc
	except Exception as exc:
		raise UpdaterError(f"Не удалось скачать обновление: {exc}") from exc

	if not data:
		raise UpdaterError("GitHub вернул пустой файл обновления.")
	return data


def install_plugin_update(current_path: str | Path, source_bytes: bytes) -> Path:
	current = Path(current_path).resolve()
	target = current.with_name(TARGET_PLUGIN_NAME)
	source = decode_plugin_source(source_bytes)
	validate_plugin_source(source)

	tmp_path = write_temp_plugin(target.parent, source)
	try:
		os.replace(tmp_path, target)
		if current != target and current.exists():
			current.unlink()
	except Exception as exc:
		raise UpdaterError(f"Не удалось заменить файл плагина: {exc}") from exc
	finally:
		if tmp_path.exists():
			try:
				tmp_path.unlink()
			except Exception:
				pass

	return target


def decode_plugin_source(source_bytes: bytes) -> str:
	try:
		return source_bytes.decode("utf-8")
	except UnicodeDecodeError as exc:
		raise UpdaterError("Файл обновления не является UTF-8 Python-файлом.") from exc


def validate_plugin_source(source: str) -> None:
	try:
		ast.parse(source)
	except SyntaxError as exc:
		raise UpdaterError(f"Файл обновления содержит ошибку Python: {exc}") from exc


def write_temp_plugin(directory: Path, source: str) -> Path:
	fd, tmp_name = tempfile.mkstemp(prefix=".manual_actions.", suffix=".tmp", dir=str(directory))
	tmp_path = Path(tmp_name)
	try:
		with os.fdopen(fd, "w", encoding="utf-8") as file:
			file.write(source)
	except Exception:
		try:
			os.close(fd)
		except Exception:
			pass
		raise
	return tmp_path


def should_offer_release(current_version: str, settings: dict[str, str], release_version: str) -> bool:
	version = release_version.strip()
	if not version:
		return False
	if version in (settings.get("installed_version", ""), settings.get("skipped_version", "")):
		return False
	if is_newer_version(current_version, version):
		return True
	if parse_version(current_version) is not None and parse_version(version) is not None:
		return False
	return normalize_version_text(version) != normalize_version_text(current_version)


def is_newer_version(current_version: str, latest_version: str) -> bool:
	current = parse_version(current_version)
	latest = parse_version(latest_version)
	if current is None or latest is None:
		return False
	return latest > current


def parse_version(version: str) -> tuple[int, ...] | None:
	value = normalize_version_text(version)
	if not value:
		return None

	parts = value.split(".")
	if not parts or any(not part.isdigit() for part in parts):
		return None
	return tuple(int(part) for part in parts)


def normalize_version_text(version: str) -> str:
	return version.strip().lower().removeprefix("v")
