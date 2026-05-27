"""Profile store — owns the active profile folder and its JSON files.

A profile is a single folder containing:
  conversations.db    (managed by ConversationStore)
  settings.json       (provider creds, agent params, tool prefs, language, multiAgentConfig, proxy)
  prompts.json        (quick actions, system prompt presets, defaults)
  mcp_servers.json    (managed by MCPClientManager)
  data_version.json   (schema version stamp)

The active profile folder is tracked by a pointer file at
  ~/.wordllms/profile.json   →   {"profile_dir": "/abs/path"}

Resolution order on startup:
  WORDLLMS_PROFILE_DIR env  →  DATA_DIR env (legacy)  →  pointer file
  →  default ~/.wordllms/default
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

DATA_VERSION = 1

# Hidden config dir holds only the pointer to the active profile.
# The profile itself defaults to a user-visible folder in Documents so
# Windows users can find it without knowing about dotfiles or Docker mounts.
POINTER_DIR = Path.home() / ".wordllms"
POINTER_PATH = POINTER_DIR / "profile.json"
DEFAULT_PROFILE_DIR = Path.home() / "Documents" / "WordLLMs"


def _running_in_docker() -> bool:
    return os.environ.get("RUNNING_IN_DOCKER") == "1"


def get_browse_root() -> Path | None:
    """Return the directory that limits profile-folder browsing/selection.

    In Docker we lock browsing to the volume mount so the user can't pick a
    container-only path that would disappear on rebuild. In source mode we
    return None (no restriction).
    """
    if not _running_in_docker():
        return None
    mount = os.environ.get("WORDLLMS_PROFILE_DIR") or os.environ.get("DATA_DIR")
    return Path(mount).resolve() if mount else None


def get_host_path() -> str | None:
    """Host-side filesystem path that the volume mount maps to (Docker only).

    Set by the launcher scripts via `-e WORDLLMS_HOST_PATH=<host_dir>`.
    Used by the frontend to show users the Windows path their data lives at.
    """
    return os.environ.get("WORDLLMS_HOST_PATH") or None


def resolve_initial_profile_dir() -> Path:
    """Decide which profile folder to use on startup.

    Order: WORDLLMS_PROFILE_DIR env → DATA_DIR env (legacy / Docker) →
    pointer file → default `~/Documents/WordLLMs`.
    """
    env_path = os.environ.get("WORDLLMS_PROFILE_DIR") or os.environ.get("DATA_DIR")
    if env_path:
        return Path(env_path).expanduser().resolve()
    if POINTER_PATH.exists():
        data = json.loads(POINTER_PATH.read_text(encoding="utf-8"))
        stored = data.get("profile_dir")
        if stored:
            return Path(stored).expanduser().resolve()
    return DEFAULT_PROFILE_DIR


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read_json_or_empty(path: Path) -> dict:
    """Read a JSON dict file, returning {} if the file is absent.

    Crashes hard if the file exists but is malformed (per project policy).
    """
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


class ProfileStore:
    """Owns the active profile folder and round-trips its JSON config files."""

    def __init__(self, profile_dir: Path):
        self._dir = profile_dir.expanduser().resolve()
        self._active_streams = 0
        self._init_dir(self._dir)
        self._settings = _read_json_or_empty(self._dir / "settings.json")
        self._prompts = _read_json_or_empty(self._dir / "prompts.json")
        # Stamp pointer file on first successful init so the next startup honors it.
        self._write_pointer()
        print(f"[ProfileStore] Active profile: {self._dir}")

    # --- Directory init / version check ---

    @staticmethod
    def _init_dir(d: Path) -> None:
        d.mkdir(parents=True, exist_ok=True)
        ProfileStore._check_data_compatibility(d)

    @staticmethod
    def _check_data_compatibility(d: Path) -> None:
        version_file = d / "data_version.json"
        if version_file.exists():
            stored = json.loads(version_file.read_text(encoding="utf-8")).get("version", 0)
            if stored != DATA_VERSION:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                archive_dir = d / f"archive_{timestamp}"
                archive_dir.mkdir(parents=True)
                for f in (
                    list(d.glob("*.db"))
                    + list(d.glob("*.db-*"))
                    + list(d.glob("*.json"))
                ):
                    shutil.move(str(f), str(archive_dir / f.name))
                print(
                    f"[ProfileStore] Data version mismatch (stored={stored}, "
                    f"current={DATA_VERSION}). Old data archived to {archive_dir}"
                )
        _atomic_write_json(version_file, {"version": DATA_VERSION})

    # --- Paths ---

    @property
    def path(self) -> Path:
        return self._dir

    @property
    def db_path(self) -> Path:
        return self._dir / "conversations.db"

    @property
    def mcp_config_path(self) -> Path:
        return self._dir / "mcp_servers.json"

    # --- In-flight stream tracking (used by SSE handlers) ---

    def increment_active_streams(self) -> None:
        self._active_streams += 1

    def decrement_active_streams(self) -> None:
        if self._active_streams <= 0:
            raise RuntimeError("active_streams counter underflow")
        self._active_streams -= 1

    @property
    def active_streams(self) -> int:
        return self._active_streams

    # --- Settings / prompts ---

    @property
    def settings(self) -> dict:
        return self._settings

    @property
    def prompts(self) -> dict:
        return self._prompts

    def save_settings(self, payload: dict) -> None:
        self._settings = payload
        target = self._dir / "settings.json"
        _atomic_write_json(target, payload)
        # API keys live here — restrict permissions on POSIX (no-op on Windows).
        os.chmod(target, 0o600)

    def save_prompts(self, payload: dict) -> None:
        self._prompts = payload
        _atomic_write_json(self._dir / "prompts.json", payload)

    # --- Profile switching ---

    def rebind(self, new_dir: Path) -> None:
        """Re-point at a different profile folder.

        Does NOT touch ConversationStore or MCPClientManager — caller orchestrates
        their close/reopen against the new `db_path` / `mcp_config_path`.
        Raises RuntimeError if any SSE stream is active.
        """
        if self._active_streams > 0:
            raise RuntimeError(
                f"Cannot switch profile while {self._active_streams} stream(s) active"
            )
        new_dir = new_dir.expanduser().resolve()
        self._init_dir(new_dir)
        self._dir = new_dir
        self._settings = _read_json_or_empty(new_dir / "settings.json")
        self._prompts = _read_json_or_empty(new_dir / "prompts.json")
        self._write_pointer()
        print(f"[ProfileStore] Switched to: {self._dir}")

    def _write_pointer(self) -> None:
        POINTER_DIR.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(POINTER_PATH, {"profile_dir": str(self._dir)})

    def _host_view_of(self, container_path: Path) -> str | None:
        """Translate a container-side path to its host-side equivalent.

        Only meaningful in Docker, where the volume mount maps a host folder
        (e.g. C:\\Users\\X\\Documents\\WordLLMs) to a container path
        (e.g. /app/data). Returns None outside Docker or if the path is
        outside the mount.
        """
        host_path = get_host_path()
        root = get_browse_root()
        if not host_path or not root:
            return None
        try:
            rel = container_path.resolve().relative_to(root)
        except ValueError:
            return None
        # Use the host's native separator since this string is for display.
        if not str(rel) or str(rel) == ".":
            return host_path
        sep = "\\" if "\\" in host_path else "/"
        return host_path.rstrip("/\\") + sep + str(rel).replace("/", sep).replace("\\", sep)

    def snapshot(self) -> dict:
        """Full snapshot for GET /api/profile."""
        browse_root = get_browse_root()
        return {
            "path": str(self._dir),
            "host_path": self._host_view_of(self._dir),
            "browse_root": str(browse_root) if browse_root else None,
            "settings": self._settings,
            "prompts": self._prompts,
            "active_streams": self._active_streams,
        }
