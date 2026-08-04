# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project Overview

WordLLMs is a Microsoft Word Add-in (Vue 3 + TypeScript front end, Python FastAPI backend) that
brings chat, single-agent and multi-agent LLM workflows into Word, with tools that read and edit
the document via Office.js.

Stack: Vue 3 (Composition API) + Vite + TailwindCSS v4, Office.js, Dexie/IndexedDB,
FastAPI + LangGraph/LangChain, litellm for provider access and pricing.

## Run environment

Windows 11, sandboxed. **Always** use the repo virtualenv explicitly — `.venv\Scripts\python.exe`
and `.venv\Scripts\pip.exe`. Never a bare `python`/`pip` or a global interpreter.

## Commands

```bash
yarn dev | build | serve          # frontend (port 3000)
yarn lint | lint:fix | lint:style | lint:dpdm
.venv\Scripts\python.exe src/backend/main.py    # backend (port 8000)
```

## Live LLM testing

If a test makes **real** API calls, use the cheapest Haiku model and the minimum number of calls
needed to prove the point. Never loop, benchmark or fan out against a paid model to verify
something a stub or a single call can show. Costs are real.

## Architecture

All LLM work runs on the Python backend and streams to the frontend over SSE.
`src/frontend/api/union.ts` is a thin shim that forwards to the backend — **browser mode is
deprecated**; no client-side LangChain models or tools remain.

Key files:
- `src/frontend/api/backend.ts` — API client, `parseSSEStream()`. Events: `text`, `tool_call`,
  `tool_result`, `error`, `done`. Text events carry accumulated content.
- `src/frontend/pages/HomePage.vue` — main chat/agent UI, builds provider configs.
- `src/frontend/utils/wordTools.ts` — Office.js executors (`wordToolExecutors`).
- `src/frontend/utils/settingPreset.ts`, `utils/enum.ts` — settings schema + localStorage keys.
- `src/backend/main.py` — FastAPI app, SSE endpoints (`/api/chat`, `/api/agent`, `/api/multiagent`).
- `src/backend/agents/chat_agent.py` — `stream_chat`, `stream_agent`, `resume_agent`.
- `src/backend/agents/chat_multiagent.py` — parallel & collaborative expert orchestration.
- `src/backend/prompts/system_prompts.py` — **all** system prompts, `generate_*_prompt()`.
- `src/backend/providers/base.py` — `create_model()` factory.
- `src/backend/conversation_store.py` — server-side LLM history (see below).

Path alias `@/` → `src/frontend/`. App boots inside `Office.onReady()` in `main.ts`.
i18n locale keys must stay sorted (ESLint rule). The codebase has Chinese locale files, but
development targets English only.

## Error handling

**Fail loudly.** Errors propagate to the user with the real message — no silent catches, no
generic "Something went wrong". SSE parse failures break the loop and surface. HTTP errors include
status and body. The only deliberate exceptions are cost computation and `litellm.drop_params`.

## Agent system

LangGraph `StateGraph` with an `agent` → `tools` loop and a `MemorySaver` checkpointer.
`tool_node` runs server tools inline and uses `interrupt()` for client-side Word tools, resumed via
`resume_agent()`. Iteration cap is the `recursion_limit` param (default 25, GUI: General → Agent
Max Iterations).

System prompt injection: if the request carries `language`, the backend generates the default
prompt; if absent, the frontend supplied a custom system message (first message, `role='system'`).
See `inject_system_prompt_if_needed`.

**Never** give a local wrapper the same name as an imported library function (e.g. a local
`create_agent` shadowing `langchain.agents.create_agent`) — it causes infinite recursion.

## Tools — single source of truth

`src/backend/tools/word_tools.py` owns every Word tool's name, description, JSON schema and
category (`read`/`select`/`write`). Nothing else defines them. `GET /api/tools` publishes the
manifest; `src/frontend/api/toolManifest.ts` caches it and asserts parity against
`wordToolExecutors` in both directions, failing loudly on drift. The frontend holds executors only
— no schemas, descriptions or i18n keys for tool names.

Server-side tools live in `src/backend/tools/`: `web_search`, `fetch_url`, `calculate`,
`get_current_date`. Name conversion camelCase ↔ snake_case in `src/frontend/api/toolNames.ts`.

## Conversation history (consigliere model)

Chat LLM, single agent, overseer and synthesizer are one "consigliere" persona sharing a long-term
history in `ConversationStore`. Experts are task-scoped workers whose messages never enter it.

Two histories exist: the frontend `history` array (GUI display, shows everything including expert
and intermediate messages) and the backend `ConversationStore` (LLM context only).

Visibility:
- `public` — user messages + consigliere final responses.
- `consigliere` — tool interactions (AIMessage with tool_calls + ToolMessage) from
  chat/agent/overseer/synthesizer. Never visible to experts.
- Expert messages are not stored at all; they live only in LangGraph state during the task.

Consigliere personas read everything via `get_history_for_consigliere()`. Experts see only the
current task's user query, peer discussion and their own tool chain.

Key methods: `start_turn`, `add_user_message`, `add_public_response`, `add_consigliere_messages`,
`get_history_for_consigliere`, `rollback_turn`, `delete_thread`.

The frontend sends **only the new user message** (plus a system message for custom prompts); all
prior context comes from `ConversationStore`, keyed by `conversationId` (from `threadId`).

## Settings

Declarative: defined in `settingPreset.ts` with type (`input`, `select`, `inputNum`, `checkbox`),
default and localStorage key; `SettingsPage.vue` renders them. A provider prefix (e.g.
`lmstudio*`) makes a setting appear only for that provider.

Adding a setting — touch all of: `utils/enum.ts` key → `Setting_Names` + `settingPreset` →
`i18n/locales/{en,zh-cn}.json` → `api/types.ts` → `HomePage.vue` provider options →
`api/backend.ts` request body → `src/backend/schemas.py` → backend logic.

## File attachments

Attachment content lives **server-side** in the profile folder; base64 crosses the wire once, at
upload. Everything downstream carries `{id, filename}` refs only, which is why attachments survive
thread switch, reload, retry, fork and edit.

```
<profile>/attachments/<conversation_id>/
    index.json                 # {"<id>": {filename, kind, stored_name, chars}}
    Reviews__3f9a1c.txt        # parsed text, UTF-8, exact round-trip (newline="")
    figure1__7b2d40.png        # images: original bytes, unparsed
```

- `POST /api/attachments` parses each file once via `parse_file(char_limit=0)` — untruncated. A
  parse failure is a 400 at upload, not a dead chat request later.
- `inject_attachments` (`main.py`) resolves refs and builds the user message through the single
  composer `file_processing.compose_user_content`, shared with `POST /api/conversation/edit`, so
  restored and fresh messages are byte-identical. `attachment_char_limit` is applied here.
- An unresolvable id is a **400**, never a silent send with files dropped.
- `GET /api/threads[/{id}]` annotates refs with `available: bool`; `loadThreadHistory` hides
  unavailable ones and warns once per thread.
- Lifecycle: fork → `copy_conversation`, thread delete → folder removed, startup and profile switch
  → `sweep_orphans`.

## API cost display

Cost renders as a footer on the **last bubble** of a response. `src/backend/pricing.py` uses
`litellm.cost_per_token()` with token counts from `usage_metadata` (final streaming chunk; a
`token_counter` fallback marks the result `estimated`). The dict
`{amount, currency, model, provider, source, estimated, effort}` rides the SSE `done` event for
chat/agent mode. `source` is `auto` | `manual` | `unknown` (unknown → UI shows `-`, never `$0`).
Multiagent instead prices each LLM call individually and stashes the dict onto that call's own
response (`response_metadata["wordllms_cost"]`); the stream processor reads it back and rides it on
that bubble's own `"message"`/`"overseer_decision"` SSE event, so every expert/overseer/synthesizer
bubble shows its own price — multiagent's `done` event carries no cost at all. A same-bubble,
multi-call turn (e.g. an expert's own tool-round retries, or the legacy-mode formatter fallback)
merges via `pricing.aggregate_costs`, but costs are never merged *across* different bubbles. The
agent path accumulates in `_session_usage` so cost survives resume cycles.
**All cost computation is wrapped in try/except** — pricing must never break a working response.

Display: General settings `costDisplayCurrency` (USD/EUR) and `costCurrencyRate` (EUR per USD);
`formatCost` in `HomePage.vue` converts. Token counts are not shown. Cost persists via
`SerializedMessage.cost`. The effort tier is appended (`0.014€ (high)`) only when the backend can
confirm it took effect.

## Reasoning effort

`src/backend/providers/effort.py` is the single source of truth for which tiers a model supports,
backing both the Settings dropdown (`GET /api/model-capabilities`) and the runtime clamp in
`providers/base.py`. Ladder: `none, low, medium, high, xhigh, max`.

Why it exists: for a model name litellm doesn't know, `reasoning_effort` drops out of supported
params and `drop_params=True` discards it **silently**. `effort.py` makes that visible (`source`,
`warnings`) and forces the param through via `allowed_openai_params`.

Precedence: (1) `model_efforts.json` `supported_efforts` → `override`; (2) its `base_model` alias;
(3) litellm capability hit → `litellm`; (4) base-model inference from the name → `inferred`;
(5) conservative `none/low/medium/high` → `fallback`. Cases 4–5 can't confirm the target honored
it, so Settings shows a notice and the cost footer omits the effort label. `togetherai` is carved
out — litellm tracks no reasoning data there, so a miss is never evidence of absence.

Multiagent roles inherit credentials, temperature and context limit from each provider's settings
sheet (`buildProviderConfigForRole`). Effort is inherited too *unless* the role sets its own tier
in Settings → Multi-Agent, since the ladder belongs to the model and a role often runs a different
one. `reasoningEffort: ''`/absent means inherit; values are clamped per role by `resolve_effort`.

## Data persistence (Docker)

`ENV DATA_DIR=/app/data`; the host volume **must** mount there:
`docker run -d -p 3000:8000 -v "C:\path:/app/data" kauttoj/wordllms`

Persisted: `conversations.db`, `attachments/<conversation_id>/`, `config.json`,
`mcp_servers.json`, `model_costs.json`, `model_efforts.json`, `data_version.json`.
Not persisted (browser-side, survives rebuilds anyway): localStorage (API keys, settings) and
IndexedDB (LangGraph checkpoints, thread display history).

`model_costs.json` and `model_efforts.json` are hand-edited (no GUI), keyed `"<provider>:<bare_model>"`
(split on first colon, so `llama4:latest` survives) and read fresh per use (no restart). Costs are
per 1M tokens (`input_per_1m`, `output_per_1m`, optional `currency`). A malformed `model_efforts.json`
is logged and ignored, never fatal.

Compatibility: bump the `DATA_VERSION` constant in `main.py` on a breaking schema change.
`_check_data_compatibility()` runs at startup; on mismatch all `*.db`/`*.json` and `attachments/`
move to `archive_<timestamp>/` and the app starts fresh.

## Deployment

- `release/instant-use/manifest.xml` (hosted) and `release/self-hosted/manifest.xml` (local/Docker).
- Backend serves the built frontend from `/dist`. CORS currently `allow_origins=["*"]` — restrict
  in production.
