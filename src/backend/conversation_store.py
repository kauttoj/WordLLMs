"""Unified conversation history store for the consigliere model.

Chat, single-agent, overseer, and synthesizer are all the same "consigliere"
persona. Experts are temporary workers scoped to a single multiagent task.

Visibility rules:
- "public" = user messages + consigliere text responses (user queries and
  final assistant answers).
- "consigliere" = consigliere tool interactions (AIMessage with tool_calls +
  ToolMessage results). Visible to all consigliere personas but never to
  experts.
- Expert tool calls and intermediate messages are never stored here — they
  live only in LangGraph state during the active task and are discarded.

Persistence:
- All conversation entries and threads are persisted to a SQLite database.
- The DB file path is configurable and can be switched at runtime.
- In-memory caches are used for fast reads; DB is the source of truth.
"""

import json
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from litellm import token_counter


# ---------------------------------------------------------------------------
# Token / character counting helpers
# ---------------------------------------------------------------------------

def _msg_to_litellm(msg: BaseMessage) -> dict[str, Any]:
    """Convert a LangChain message to litellm dict format."""
    if isinstance(msg, HumanMessage):
        role = "user"
    elif isinstance(msg, AIMessage):
        role = "assistant"
    elif isinstance(msg, ToolMessage):
        role = "tool"
    else:
        role = "user"
    # Pass content as-is (str or multimodal list) so litellm can handle it properly
    d: dict[str, Any] = {"role": role, "content": msg.content}
    if isinstance(msg, ToolMessage):
        d["tool_call_id"] = msg.tool_call_id
    if isinstance(msg, AIMessage) and msg.tool_calls:
        d["tool_calls"] = [
            {"id": tc["id"], "type": "function",
             "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])}}
            for tc in msg.tool_calls
        ]
    return d


# Approximate tokens per image — most providers charge 800-1600 tokens per image.
_IMAGE_TOKENS_ESTIMATE = 1200


def _count_image_parts(msg: BaseMessage) -> int:
    """Count image_url parts in multimodal message content."""
    if not isinstance(msg.content, list):
        return 0
    return sum(1 for p in msg.content if isinstance(p, dict) and p.get("type") == "image_url")


def _count_msg_chars(msg: BaseMessage) -> int:
    """Count text characters in a message's content (images excluded)."""
    c = msg.content
    if isinstance(c, str):
        return len(c)
    if isinstance(c, list):
        return sum(len(p.get("text", "")) for p in c if isinstance(p, dict))
    return 0


def _count_msg_tokens(msg: BaseMessage) -> int:
    """Estimate tokens for a single message, averaged across two tokenizers."""
    m = _msg_to_litellm(msg)
    image_tokens = _count_image_parts(msg) * _IMAGE_TOKENS_ESTIMATE
    try:
        c1 = token_counter(model="gpt-5", messages=[m])
        c2 = token_counter(model="claude-sonnet-4-5", messages=[m])
        return (c1 + c2) // 2 + image_tokens
    except Exception:
        return _count_msg_chars(msg) // 4 + image_tokens


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ConversationEntry:
    """A single message entry in the conversation store."""
    turn: int
    persona: str        # "user", "chat", "agent", "synthesizer", "overseer"
    mode: str           # "chat", "agent", "parallel", "collaborative"
    message: BaseMessage
    visibility: Literal["public", "consigliere"]


@dataclass
class Conversation:
    """A single conversation's full state."""
    entries: list[ConversationEntry] = field(default_factory=list)
    turn_counter: int = 0
    system_prompt: str | None = None
    total_chars: int = 0
    total_tokens: int = 0


@dataclass
class ThreadMapping:
    """Maps an internal LangGraph thread_id to its parent conversation context."""
    conversation_id: str
    turn: int
    pre_turn_message_count: int


# ---------------------------------------------------------------------------
# Message serialization helpers
# ---------------------------------------------------------------------------

def _serialize_message(msg: BaseMessage) -> dict[str, Any]:
    """Serialize a LangChain message to a JSON-safe dict."""
    msg_type = msg.__class__.__name__  # HumanMessage, AIMessage, ToolMessage, etc.
    content = msg.content  # str or list[dict] for multimodal
    data: dict[str, Any] = {
        "type": msg_type,
        "content": content,
    }
    if isinstance(msg, AIMessage) and msg.tool_calls:
        data["tool_calls"] = msg.tool_calls
    if isinstance(msg, ToolMessage):
        data["tool_call_id"] = msg.tool_call_id
    return data


def _deserialize_message(data: dict[str, Any]) -> BaseMessage:
    """Reconstruct a LangChain message from a serialized dict."""
    msg_type = data["type"]
    content = data["content"]
    if msg_type == "HumanMessage":
        return HumanMessage(content=content)
    elif msg_type == "AIMessage":
        kwargs: dict[str, Any] = {"content": content}
        if data.get("tool_calls"):
            kwargs["tool_calls"] = data["tool_calls"]
        return AIMessage(**kwargs)
    elif msg_type == "ToolMessage":
        return ToolMessage(content=content, tool_call_id=data.get("tool_call_id", ""))
    else:
        # Fallback: treat as HumanMessage
        return HumanMessage(content=content)


# ---------------------------------------------------------------------------
# Default DB path
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_DIR = Path(os.environ.get("DATA_DIR", str(_PROJECT_ROOT / "data")))
DEFAULT_DB_PATH = str(_DATA_DIR / "conversations.db")
MAX_THREADS = 500


# ---------------------------------------------------------------------------
# ConversationStore
# ---------------------------------------------------------------------------

class ConversationStore:
    """SQLite-backed conversation store with consigliere / expert separation.

    What gets stored after each mode:
    - Chat:          user message (public) + assistant response (public)
    - Single agent:  user message (public) + final response (public) +
                     tool interactions (consigliere)
    - Parallel:      user message (public) + synthesizer final response (public) +
                     synthesizer tool interactions (consigliere)
    - Collaborative: user message (public) + overseer final answer (public) +
                     overseer tool interactions (consigliere)
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        # In-memory caches for fast reads
        self._conversations: dict[str, Conversation] = {}
        # Thread mappings are session-scoped (not persisted)
        self._thread_mappings: dict[str, ThreadMapping] = {}
        # SQLite
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._open_database(db_path)

    # --- Database lifecycle ---

    def _open_database(self, db_path: str) -> None:
        """Open (or create) SQLite database at the given path."""
        path = Path(db_path)
        is_new = not path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()
        self._db_path = db_path
        self._log_db_stats(path, is_new)

    def _create_tables(self) -> None:
        assert self._conn is not None
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                turn INTEGER NOT NULL,
                persona TEXT NOT NULL,
                mode TEXT NOT NULL,
                message_json TEXT NOT NULL,
                visibility TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_entries_conv
                ON entries(conversation_id, turn);

            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY,
                turn_counter INTEGER DEFAULT 0,
                system_prompt TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS threads (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                messages_json TEXT NOT NULL,
                mode TEXT NOT NULL,
                provider TEXT,
                model TEXT,
                message_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_threads_updated
                ON threads(updated_at DESC);
        """)
        # Migration: add token tracking columns if missing
        for col in ("total_chars", "total_tokens"):
            try:
                self._conn.execute(
                    f"ALTER TABLE conversations ADD COLUMN {col} INTEGER DEFAULT 0"
                )
            except sqlite3.OperationalError:
                pass  # column already exists
        self._conn.commit()

    def _log_db_stats(self, path: Path, is_new: bool) -> None:
        """Log database open status with basic statistics."""
        assert self._conn is not None
        thread_count = self._conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
        conv_count = self._conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        entry_count = self._conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        size_bytes = path.stat().st_size if path.exists() else 0
        if size_bytes < 1024:
            size_str = f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            size_str = f"{size_bytes / 1024:.1f} KB"
        else:
            size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
        status = "Created new" if is_new else "Opened"
        print(
            f"[ConversationStore] {status} database: {path}\n"
            f"  {thread_count} threads, {conv_count} conversations, "
            f"{entry_count} entries, size {size_str}"
        )

    def switch_database(self, new_path: str) -> None:
        """Close current DB, clear caches, open a new DB file."""
        old_path = self._db_path
        if self._conn:
            self._conn.close()
            self._conn = None
        self._conversations.clear()
        # Thread mappings are session-scoped — clear them too since
        # any in-flight agent sessions belong to the old DB.
        self._thread_mappings.clear()
        print(f"[ConversationStore] Switching database: {old_path} -> {new_path}")
        self._open_database(new_path)

    @property
    def db_path(self) -> str:
        return self._db_path

    # --- Conversation entry persistence ---

    def _db_insert_entry(
        self, conversation_id: str, turn: int, persona: str, mode: str,
        message: BaseMessage, visibility: str,
    ) -> None:
        assert self._conn is not None
        msg_json = json.dumps(_serialize_message(message), ensure_ascii=False)
        self._conn.execute(
            "INSERT INTO entries (conversation_id, turn, persona, mode, message_json, visibility) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (conversation_id, turn, persona, mode, msg_json, visibility),
        )
        self._conn.commit()

    def _db_upsert_conversation(self, conversation_id: str, conv: Conversation) -> None:
        assert self._conn is not None
        self._conn.execute(
            "INSERT INTO conversations "
            "(conversation_id, turn_counter, system_prompt, total_chars, total_tokens, updated_at) "
            "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(conversation_id) DO UPDATE SET "
            "turn_counter=excluded.turn_counter, system_prompt=excluded.system_prompt, "
            "total_chars=excluded.total_chars, total_tokens=excluded.total_tokens, "
            "updated_at=CURRENT_TIMESTAMP",
            (conversation_id, conv.turn_counter, conv.system_prompt,
             conv.total_chars, conv.total_tokens),
        )
        self._conn.commit()

    def _load_conversation_from_db(self, conversation_id: str) -> Conversation | None:
        """Load a full conversation from SQLite into memory."""
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT turn_counter, system_prompt, total_chars, total_tokens "
            "FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            return None

        conv = Conversation(
            turn_counter=row[0], system_prompt=row[1],
            total_chars=row[2] or 0, total_tokens=row[3] or 0,
        )

        entry_rows = self._conn.execute(
            "SELECT turn, persona, mode, message_json, visibility "
            "FROM entries WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()

        for erow in entry_rows:
            msg_data = json.loads(erow[3])
            msg = _deserialize_message(msg_data)
            conv.entries.append(ConversationEntry(
                turn=erow[0], persona=erow[1], mode=erow[2],
                message=msg, visibility=erow[4],
            ))

        # Migration: recompute stats for conversations created before tracking
        if conv.entries and conv.total_chars == 0 and conv.total_tokens == 0:
            conv.total_chars = sum(_count_msg_chars(e.message) for e in conv.entries)
            conv.total_tokens = sum(_count_msg_tokens(e.message) for e in conv.entries)
            self._db_upsert_conversation(conversation_id, conv)

        return conv

    # --- Public API (same signatures as before) ---

    def get_or_create(self, conversation_id: str) -> Conversation:
        if conversation_id not in self._conversations:
            # Try loading from DB
            loaded = self._load_conversation_from_db(conversation_id)
            if loaded:
                self._conversations[conversation_id] = loaded
            else:
                conv = Conversation()
                self._conversations[conversation_id] = conv
                self._db_upsert_conversation(conversation_id, conv)
        return self._conversations[conversation_id]

    def start_turn(self, conversation_id: str) -> int:
        conv = self.get_or_create(conversation_id)
        conv.turn_counter += 1
        self._db_upsert_conversation(conversation_id, conv)
        return conv.turn_counter

    def add_user_message(
        self, conversation_id: str, turn: int, message: HumanMessage, mode: str,
    ) -> None:
        conv = self.get_or_create(conversation_id)
        conv.entries.append(ConversationEntry(
            turn=turn, persona="user", mode=mode,
            message=message, visibility="public",
        ))
        self._db_insert_entry(conversation_id, turn, "user", mode, message, "public")

    def add_public_response(
        self, conversation_id: str, turn: int, persona: str, mode: str,
        message: AIMessage,
    ) -> None:
        conv = self.get_or_create(conversation_id)
        conv.entries.append(ConversationEntry(
            turn=turn, persona=persona, mode=mode,
            message=message, visibility="public",
        ))
        self._db_insert_entry(conversation_id, turn, persona, mode, message, "public")
        # Update context stats for ALL entries in this turn (user + tools + response)
        turn_entries = [e for e in conv.entries if e.turn == turn]
        conv.total_chars += sum(_count_msg_chars(e.message) for e in turn_entries)
        conv.total_tokens += sum(_count_msg_tokens(e.message) for e in turn_entries)
        self._db_upsert_conversation(conversation_id, conv)

    def add_consigliere_messages(
        self, conversation_id: str, turn: int, persona: str, mode: str,
        messages: list[BaseMessage],
    ) -> None:
        """Store consigliere tool interactions (AIMessage+tool_calls, ToolMessage)."""
        conv = self.get_or_create(conversation_id)
        for msg in messages:
            conv.entries.append(ConversationEntry(
                turn=turn, persona=persona, mode=mode,
                message=msg, visibility="consigliere",
            ))
            self._db_insert_entry(conversation_id, turn, persona, mode, msg, "consigliere")

    def get_history_for_consigliere(self, conversation_id: str) -> list[BaseMessage]:
        """Full consigliere history: public messages + consigliere tool interactions.

        Used by chat, agent, overseer, and synthesizer.
        """
        conv = self._conversations.get(conversation_id)
        if not conv:
            # Try loading from DB (lazy hydration)
            loaded = self._load_conversation_from_db(conversation_id)
            if loaded:
                self._conversations[conversation_id] = loaded
                conv = loaded
        if not conv:
            return []
        return [e.message for e in conv.entries]

    def get_context_stats(self, conversation_id: str) -> tuple[int, int]:
        """Return (total_chars, total_tokens) for the conversation."""
        conv = self.get_or_create(conversation_id)
        return conv.total_chars, conv.total_tokens

    # --- Thread mapping for interrupt/resume (session-scoped, not persisted) ---

    def register_thread(
        self, internal_thread_id: str, conversation_id: str, turn: int,
        pre_turn_message_count: int,
    ) -> None:
        self._thread_mappings[internal_thread_id] = ThreadMapping(
            conversation_id=conversation_id,
            turn=turn,
            pre_turn_message_count=pre_turn_message_count,
        )

    def lookup_thread(self, internal_thread_id: str) -> ThreadMapping | None:
        return self._thread_mappings.get(internal_thread_id)

    def unregister_thread(self, internal_thread_id: str) -> None:
        self._thread_mappings.pop(internal_thread_id, None)

    # --- System prompt caching ---

    def set_system_prompt(self, conversation_id: str, prompt: str) -> None:
        conv = self.get_or_create(conversation_id)
        conv.system_prompt = prompt
        self._db_upsert_conversation(conversation_id, conv)

    def get_system_prompt(self, conversation_id: str) -> str | None:
        conv = self._conversations.get(conversation_id)
        if conv:
            return conv.system_prompt
        # Try DB
        loaded = self._load_conversation_from_db(conversation_id)
        if loaded:
            self._conversations[conversation_id] = loaded
            return loaded.system_prompt
        return None

    # --- Error rollback ---

    def rollback_turn(self, conversation_id: str, turn: int) -> None:
        """Remove all entries from a failed turn and decrement the counter."""
        conv = self._conversations.get(conversation_id)
        if conv:
            conv.entries = [e for e in conv.entries if e.turn != turn]
            if conv.turn_counter >= turn:
                conv.turn_counter = turn - 1
            # Recompute stats from remaining entries
            conv.total_chars = sum(_count_msg_chars(e.message) for e in conv.entries)
            conv.total_tokens = sum(_count_msg_tokens(e.message) for e in conv.entries)
            self._db_upsert_conversation(conversation_id, conv)

        # Also remove from DB
        assert self._conn is not None
        self._conn.execute(
            "DELETE FROM entries WHERE conversation_id = ? AND turn = ?",
            (conversation_id, turn),
        )
        self._conn.commit()

    def rollback_response(self, conversation_id: str, turn: int) -> None:
        """Remove non-user entries from a failed turn, preserving the user message.

        Unlike rollback_turn(), this keeps the HumanMessage so the user's query
        remains in LLM context for subsequent turns. The turn counter is NOT
        decremented because the turn still exists (with a user message).
        """
        conv = self._conversations.get(conversation_id)
        if conv:
            conv.entries = [
                e for e in conv.entries
                if not (e.turn == turn and not isinstance(e.message, HumanMessage))
            ]
            conv.total_chars = sum(_count_msg_chars(e.message) for e in conv.entries)
            conv.total_tokens = sum(_count_msg_tokens(e.message) for e in conv.entries)
            self._db_upsert_conversation(conversation_id, conv)

        assert self._conn is not None
        self._conn.execute(
            "DELETE FROM entries WHERE conversation_id = ? AND turn = ? AND persona != 'user'",
            (conversation_id, turn),
        )
        self._conn.commit()

    # --- Edit / Truncate / Fork (edit / retry / fork support) ---

    def edit_user_message(self, conversation_id: str, turn: int, new_content: str) -> None:
        """Replace the content of a turn's user message in-place.

        Used by Edit: modifies the stored user message so future LLM context
        reflects the edit. All other messages remain untouched.
        """
        conv = self.get_or_create(conversation_id)
        new_msg = HumanMessage(content=new_content)
        found = False
        for entry in conv.entries:
            if entry.turn == turn and entry.persona == "user":
                entry.message = new_msg
                found = True
                break
        if not found:
            raise ValueError(
                f"No user message found for conversation {conversation_id} turn {turn}"
            )

        # Recompute stats
        conv.total_chars = sum(_count_msg_chars(e.message) for e in conv.entries)
        conv.total_tokens = sum(_count_msg_tokens(e.message) for e in conv.entries)
        self._db_upsert_conversation(conversation_id, conv)

        # Update DB entry
        assert self._conn is not None
        msg_json = json.dumps(_serialize_message(new_msg), ensure_ascii=False)
        self._conn.execute(
            "UPDATE entries SET message_json = ? "
            "WHERE conversation_id = ? AND turn = ? AND persona = 'user'",
            (msg_json, conversation_id, turn),
        )
        self._conn.commit()

    def truncate_from_turn(self, conversation_id: str, from_turn: int) -> None:
        """Remove all entries where turn >= from_turn and reset turn counter.

        Used by Retry: truncate the conversation so the turn can be
        re-sent fresh via the normal processChat flow.
        """
        conv = self._conversations.get(conversation_id)
        if not conv:
            loaded = self._load_conversation_from_db(conversation_id)
            if loaded:
                self._conversations[conversation_id] = loaded
                conv = loaded
        if conv:
            conv.entries = [e for e in conv.entries if e.turn < from_turn]
            conv.turn_counter = from_turn - 1
            conv.total_chars = sum(_count_msg_chars(e.message) for e in conv.entries)
            conv.total_tokens = sum(_count_msg_tokens(e.message) for e in conv.entries)
            self._db_upsert_conversation(conversation_id, conv)

        assert self._conn is not None
        self._conn.execute(
            "DELETE FROM entries WHERE conversation_id = ? AND turn >= ?",
            (conversation_id, from_turn),
        )
        self._conn.commit()

    def fork_conversation(
        self, source_id: str, target_id: str, up_to_turn: int,
    ) -> None:
        """Clone conversation entries into a new conversation, excluding the fork-point turn.

        Copies all complete turns strictly before up_to_turn. The user message
        from up_to_turn is NOT included — the frontend returns it to the input
        box so the user can re-edit and re-send.
        """
        source = self.get_or_create(source_id)

        target = Conversation(
            turn_counter=up_to_turn - 1,
            system_prompt=source.system_prompt,
        )
        for entry in source.entries:
            if entry.turn < up_to_turn:
                target.entries.append(ConversationEntry(
                    turn=entry.turn,
                    persona=entry.persona,
                    mode=entry.mode,
                    message=entry.message,
                    visibility=entry.visibility,
                ))
        target.total_chars = sum(_count_msg_chars(e.message) for e in target.entries)
        target.total_tokens = sum(_count_msg_tokens(e.message) for e in target.entries)

        self._conversations[target_id] = target
        self._db_upsert_conversation(target_id, target)

        assert self._conn is not None
        for entry in target.entries:
            self._db_insert_entry(
                target_id, entry.turn, entry.persona, entry.mode,
                entry.message, entry.visibility,
            )
        self._conn.commit()

    # --- Thread CRUD (GUI display history) ---

    def save_thread(self, thread_data: dict) -> None:
        """Save or update a thread (GUI display history).

        thread_data keys: id, title, messages (list of dicts), mode,
        provider, model, messageCount, createdAt, updatedAt
        """
        assert self._conn is not None
        messages_json = json.dumps(thread_data["messages"], ensure_ascii=False)
        self._conn.execute(
            "INSERT INTO threads (id, title, messages_json, mode, provider, model, "
            "message_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "title=excluded.title, messages_json=excluded.messages_json, "
            "mode=excluded.mode, provider=excluded.provider, model=excluded.model, "
            "message_count=excluded.message_count, updated_at=excluded.updated_at",
            (
                thread_data["id"],
                thread_data["title"],
                messages_json,
                thread_data["mode"],
                thread_data.get("provider", ""),
                thread_data.get("model", ""),
                thread_data.get("messageCount", 0),
                thread_data.get("createdAt", ""),
                thread_data.get("updatedAt", ""),
            ),
        )
        self._conn.commit()
        self._prune_threads()

    def get_thread(self, thread_id: str) -> dict | None:
        """Get a thread by ID. Returns dict with parsed messages or None."""
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT id, title, messages_json, mode, provider, model, "
            "message_count, created_at, updated_at FROM threads WHERE id = ?",
            (thread_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "title": row[1],
            "messages": json.loads(row[2]),
            "mode": row[3],
            "provider": row[4],
            "model": row[5],
            "messageCount": row[6],
            "createdAt": row[7],
            "updatedAt": row[8],
        }

    def list_threads(self, limit: int = 50) -> list[dict]:
        """List threads ordered by most recently updated."""
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT id, title, messages_json, mode, provider, model, "
            "message_count, created_at, updated_at "
            "FROM threads ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        result = []
        for row in rows:
            messages = json.loads(row[2])
            result.append({
                "id": row[0],
                "title": row[1],
                "messages": messages,
                "mode": row[3],
                "provider": row[4],
                "model": row[5],
                "messageCount": row[6],
                "createdAt": row[7],
                "updatedAt": row[8],
            })
        return result

    def delete_thread(self, thread_id: str) -> bool:
        """Delete a thread and its associated conversation entries."""
        assert self._conn is not None
        cursor = self._conn.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
        # Also delete conversation entries for this thread
        self._conn.execute("DELETE FROM entries WHERE conversation_id = ?", (thread_id,))
        self._conn.execute("DELETE FROM conversations WHERE conversation_id = ?", (thread_id,))
        self._conn.commit()
        # Clear from memory cache
        self._conversations.pop(thread_id, None)
        return cursor.rowcount > 0

    def _prune_threads(self) -> None:
        """Remove oldest threads if count exceeds MAX_THREADS."""
        assert self._conn is not None
        count = self._conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
        if count <= MAX_THREADS:
            return
        to_delete = count - MAX_THREADS
        old_ids = self._conn.execute(
            "SELECT id FROM threads ORDER BY updated_at ASC LIMIT ?",
            (to_delete,),
        ).fetchall()
        for (tid,) in old_ids:
            self.delete_thread(tid)
