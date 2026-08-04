"""Server-side attachment storage.

Attachment payloads (base64) cross the wire exactly once, at upload time via
``POST /api/attachments``. From then on, chat/agent/edit requests reference
attachments by id only; this module resolves those ids back to content at
injection time. This is what makes an attachment survive thread switch /
reload / retry / fork / edit — the browser never needs to re-send the bytes.

Disk layout (inside the active profile folder):

    <profile>/attachments/<conversation_id>/
        index.json                      # {"<id>": {"filename":..., "kind":"text"|"image",
                                         #            "stored_name":..., "chars": int}}
        Reviews_KMIS__3f9a1c.txt         # parsed text, UTF-8, newline="\n"
        figure1__7b2d40.png              # images: original bytes, unparsed

Parsed text is stored **untruncated**; the per-file char limit
(``attachment_char_limit``) is applied at injection time
(``file_processing.compose_user_content``) so changing the setting later
affects old messages too.

The module-level configurable dir mirrors ``pricing.configure_model_costs_path``
/ ``effort.configure_model_efforts_path``: ``configure_attachments_dir`` is
called once at startup and again on every profile switch.
"""
from __future__ import annotations

import base64
import json
import os
import re
import secrets
import shutil
import threading
from pathlib import Path

try:
    from . import file_processing
except ImportError:  # direct execution (python main.py)
    import file_processing


# Total decoded-byte cap per upload call. Measured on decoded bytes, not the
# base64 string length, so the real on-disk/network cost is what's enforced.
MAX_ATTACHMENTS_BYTES = 50 * 1024 * 1024  # 50 MB total

_ATTACHMENTS_DIR: Path | None = None
# Guards read-modify-write of any conversation's index.json against concurrent
# requests (e.g. two uploads for the same conversation in flight at once).
_lock = threading.Lock()

_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_STEM_LEN = 60


def configure_attachments_dir(path: Path) -> None:
    """Point the store at the active profile's attachments/ folder (called from main)."""
    global _ATTACHMENTS_DIR
    _ATTACHMENTS_DIR = Path(path)


def _root() -> Path:
    if _ATTACHMENTS_DIR is None:
        raise RuntimeError(
            "attachment_store not configured — call configure_attachments_dir() first"
        )
    return _ATTACHMENTS_DIR


def _sanitize_conversation_id(conversation_id: str) -> str:
    """Reject a conversation id that could escape the attachments root as a path.

    conversation_id ends up as a bare path-segment folder name; a value
    containing separators or '..' must never be allowed to reach Path().
    """
    if not conversation_id or "/" in conversation_id or "\\" in conversation_id or ".." in conversation_id:
        raise ValueError(f"Invalid conversation_id: {conversation_id!r}")
    return conversation_id


def _conv_dir(conversation_id: str) -> Path:
    return _root() / _sanitize_conversation_id(conversation_id)


def _index_path(conversation_id: str) -> Path:
    return _conv_dir(conversation_id) / "index.json"


def _read_index(conversation_id: str) -> dict:
    path = _index_path(conversation_id)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_index(conversation_id: str, index: dict) -> None:
    path = _index_path(conversation_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _sanitize_stem(filename: str) -> str:
    """Sanitize the filename stem for use inside a stored filename.

    Keeps alnum/./_/- , collapses everything else to '_', caps length.
    """
    stem = Path(filename).stem
    cleaned = _SANITIZE_RE.sub("_", stem).strip("_.")
    if not cleaned:
        cleaned = "file"
    return cleaned[:_MAX_STEM_LEN]


def save_attachments(conversation_id: str, files: list[dict]) -> list[dict]:
    """Persist uploaded files for a conversation. `files` are {"filename","data"(base64)}.

    Images are written as raw decoded bytes. Everything else is parsed via
    `file_processing.parse_file` (char_limit=0, i.e. untruncated) and the
    resulting text is written as UTF-8 with newline="\\n".

    A parse failure raises ValueError immediately — before any stored file or
    index entry is written for that item — so the caller (a 400 response)
    never leaves a partial/corrupt index entry behind. Files already
    successfully persisted earlier in the same batch remain persisted and
    indexed.

    Returns [{"id","filename","kind","chars"}] in input order.
    """
    conversation_id = _sanitize_conversation_id(conversation_id)

    total_bytes = sum(len(base64.b64decode(f["data"])) for f in files)
    if total_bytes > MAX_ATTACHMENTS_BYTES:
        raise ValueError(
            f"Total attachment size ({total_bytes} bytes) exceeds the "
            f"{MAX_ATTACHMENTS_BYTES} byte limit"
        )

    conv_dir = _conv_dir(conversation_id)
    conv_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    with _lock:
        index = _read_index(conversation_id)
        for f in files:
            filename = f["filename"]
            data_b64 = f["data"]
            attachment_id = secrets.token_hex(6)
            stem = _sanitize_stem(filename)

            if file_processing.is_image(filename):
                raw = base64.b64decode(data_b64)
                ext = Path(filename).suffix or ""
                stored_name = f"{stem}__{attachment_id}{ext}"
                (conv_dir / stored_name).write_bytes(raw)
                kind = "image"
                chars = 0
            else:
                # Untruncated: char_limit is applied at injection time instead,
                # so a later change to the setting affects already-stored files.
                text, _trunc_info = file_processing.parse_file(filename, data_b64, char_limit=0)
                stored_name = f"{stem}__{attachment_id}.txt"
                # newline="" on both write and read disables Python's universal-newline
                # translation, so a CRLF source round-trips to the exact same string the
                # parser produced. Anything else would make a restored message differ
                # from a freshly-sent one.
                with (conv_dir / stored_name).open("w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
                kind = "text"
                chars = len(text)

            index[attachment_id] = {
                "filename": filename,
                "kind": kind,
                "stored_name": stored_name,
                "chars": chars,
            }
            # Written after every successful file so a mid-batch failure only
            # loses the entry for the file that actually failed.
            _write_index(conversation_id, index)

            results.append({
                "id": attachment_id, "filename": filename, "kind": kind, "chars": chars,
            })

    return results


def load_for_injection(conversation_id: str, refs: list[dict]) -> tuple[list[dict], list[str]]:
    """Resolve attachment refs ({"id","filename"}) to content, in ref order.

    Returns (items, missing_ids). An id absent from the index, or present but
    whose backing file is missing on disk, is reported in missing_ids and
    excluded from items — the caller must fail loudly rather than silently
    sending a message with the attachment dropped.

    items: {"filename","kind":"text","text"} or {"filename","kind":"image","data_b64"}.
    "filename" always comes from the index (authoritative), not the ref.
    """
    conversation_id = _sanitize_conversation_id(conversation_id)
    conv_dir = _conv_dir(conversation_id)
    with _lock:
        index = _read_index(conversation_id)

    items: list[dict] = []
    missing_ids: list[str] = []
    for ref in refs:
        ref_id = ref["id"]
        entry = index.get(ref_id)
        if entry is None:
            missing_ids.append(ref_id)
            continue
        stored_path = conv_dir / entry["stored_name"]
        if not stored_path.exists():
            missing_ids.append(ref_id)
            continue

        filename = entry["filename"]
        if entry["kind"] == "image":
            data_b64 = base64.b64encode(stored_path.read_bytes()).decode("ascii")
            items.append({"filename": filename, "kind": "image", "data_b64": data_b64})
        else:
            # newline="" — see save_attachments: no newline translation, exact round-trip.
            with stored_path.open("r", encoding="utf-8", newline="") as fh:
                text = fh.read()
            items.append({"filename": filename, "kind": "text", "text": text})

    return items, missing_ids


def available_ids(conversation_id: str) -> set[str]:
    """ids whose index entry AND backing file both exist for this conversation."""
    conversation_id = _sanitize_conversation_id(conversation_id)
    conv_dir = _conv_dir(conversation_id)
    with _lock:
        index = _read_index(conversation_id)
    return {
        aid for aid, entry in index.items()
        if (conv_dir / entry["stored_name"]).exists()
    }


def copy_conversation(src_id: str, dst_id: str) -> None:
    """Clone a conversation's attachment folder (used by fork). No-op if source is absent."""
    src_dir = _conv_dir(src_id)
    dst_dir = _conv_dir(dst_id)
    if not src_dir.exists():
        return
    with _lock:
        shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)


def delete_conversation(conversation_id: str) -> None:
    """Remove a conversation's attachment folder entirely. No-op if absent."""
    conv_dir = _conv_dir(conversation_id)
    with _lock:
        if conv_dir.exists():
            shutil.rmtree(conv_dir)


def sweep_orphans(known_ids: set[str]) -> int:
    """Delete attachment folders whose name is not a known conversation id.

    Run at startup and on profile switch, after the DB is opened, so
    `known_ids` reflects the conversations/threads that still exist.
    """
    root = _root()
    if not root.exists():
        return 0
    removed = 0
    with _lock:
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            if entry.name not in known_ids:
                shutil.rmtree(entry)
                removed += 1
                print(f"[AttachmentStore] removed orphaned attachment folder: {entry.name}")
    return removed
