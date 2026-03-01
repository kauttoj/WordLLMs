# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Word GPT Plus is a Microsoft Word Add-in that integrates AI and LLM Agent capabilities directly into Microsoft Word. It supports multiple AI providers (OpenAI, Azure OpenAI, Google Gemini, Groq, Ollama, LMStudio) and provides both chat mode and agent mode with document manipulation tools.

## Development Commands

### Frontend (Vue 3 Add-in)
```bash
yarn dev          # Start dev server on port 3000
yarn build        # Production build to /dist
yarn serve        # Preview production build on port 3000
yarn lint         # Run ESLint
yarn lint:fix     # Run ESLint with auto-fix
yarn lint:style   # Run Stylelint on Vue/CSS files
yarn lint:dpdm    # Check for circular dependencies
```

### Backend (Python FastAPI Server)
```bash
cd src/backend
pip install -r requirements.txt  # Install dependencies
python main.py                   # Start backend on port 8000
# or
uvicorn main:app --reload        # Start with auto-reload
```

## Architecture

### Core Technologies
- **Vue 3** with Composition API and TypeScript
- **LangChain** for AI model orchestration and agent system
- **FastAPI** (Python) for optional backend server execution
- **Office.js** for Word document interaction
- **Dexie/IndexedDB** for conversation checkpoint persistence
- **Vite** + **TailwindCSS v4** for build and styling

### Execution Modes

The application supports **two execution modes**:

1. **Backend Mode (Default)**: LLM requests are processed by a Python FastAPI server
   - Controlled by `isBackendEnabled()` in `src/frontend/api/union.ts` (defaults to `true`)
   - Backend URL configurable via `setBackendUrl()`, defaults to same origin
   - Uses Server-Sent Events (SSE) for streaming responses
   - Better for production: reduces browser memory usage, enables server-side tools

2. **Browser Mode (Fallback)**: LLM requests execute directly in the browser
   - Uses LangChain.js running client-side
   - Useful for development/debugging or when backend unavailable
   - Toggle with `setBackendEnabled(false)` in localStorage

### Key Directories

#### Frontend (Vue/TypeScript)
```
src/frontend/
├── api/
│   ├── union.ts        # Execution mode routing (backend vs browser)
│   ├── backend.ts      # Backend API client with SSE streaming
│   ├── checkpoints.ts  # IndexedDBSaver - persists LangGraph checkpoints via Dexie
│   ├── common.ts       # Word document insertion helpers
│   └── types.ts        # Provider option interfaces
├── utils/
│   ├── wordTools.ts    # 25+ Word manipulation tools for agent (createWordTools)
│   ├── generalTools.ts # General agent tools (web search, fetch, math, date)
│   ├── settingPreset.ts # Settings schema with localStorage persistence
│   └── constant.ts     # Available models per provider
├── pages/
│   ├── HomePage.vue    # Main chat/agent interface
│   └── SettingsPage.vue
├── components/         # Reusable UI components
└── i18n/locales/       # en.json, zh-cn.json (ESLint enforces sorted keys)
```

#### Backend (Python/FastAPI)
```
src/backend/
├── main.py             # FastAPI app with SSE endpoints (/api/chat, /api/agent, /api/multiagent)
├── schemas.py          # Pydantic request/response models
├── conversation_store.py  # Unified consigliere conversation history (in-memory)
├── prompts/
│   ├── __init__.py     # Package init
│   └── system_prompts.py  # All system prompt generation functions (chat, agent, multiagent)
├── agents/
│   ├── chat_agent.py   # LangGraph agent execution (stream_chat, stream_agent)
│   └── chat_multiagent.py  # Multi-expert orchestration (parallel & collaborative modes)
├── providers/
│   ├── base.py         # Model factory (create_model)
│   ├── provider_openai.py
│   ├── provider_azure.py
│   ├── provider_gemini.py
│   ├── provider_groq.py
│   ├── provider_ollama.py
│   └── provider_lmstudio.py
└── tools/
    ├── __init__.py     # Tool registry (AVAILABLE_TOOLS)
    ├── web.py          # web_search_tool, fetch_url_tool
    ├── calculator.py   # calculate_tool (safe math eval)
    └── date.py         # get_current_date_tool
```

### AI Provider Integration

**Backend Mode (Default)**:
- `src/frontend/api/backend.ts` handles all API communication via SSE streaming
- `streamChatFromBackend()` and `streamAgentFromBackend()` send requests to FastAPI endpoints
- Backend `create_model()` in `src/backend/providers/base.py` instantiates LangChain models
- Supports: OpenAI, Azure OpenAI, Google Gemini, Groq, Ollama, LMStudio

**Browser Mode (Fallback)**:
- `src/frontend/api/union.ts` contains `ModelCreators` factory for browser-side LangChain models
- Direct browser execution of LangChain.js
- Used when backend is disabled or unavailable

### Agent Tools System

**Backend Mode**:
- Server-side tools in `src/backend/tools/`:
  - `web_search` - DuckDuckGo search
  - `fetch_url` - HTTP requests with HTML-to-text conversion
  - `calculate` - Safe math evaluation
  - `get_current_date` - Date/time information
- Tool names mapped from frontend (`src/frontend/api/backend.ts:mapToolName()`)
- Word manipulation tools remain browser-side (Office.js requires browser context)

**Browser Mode**:
- All tools run client-side defined in `src/frontend/utils/`:
  - **Word Tools** (`wordTools.ts`): 25+ document manipulation tools via Office.js
  - **General Tools** (`generalTools.ts`): Web search, fetch, math, date
- Tools created using LangChain's `tool()` helper with Zod schemas

### Conversation History (Consigliere Model)

The backend uses a unified "consigliere" model for cross-mode message history, implemented in `src/backend/conversation_store.py`. This allows seamless switching between chat, agent, and multiagent modes within the same conversation session.

**Core concept**: Chat LLM, single agent, overseer, and synthesizer are all the same "consigliere" persona sharing one long-term history. Experts are temporary workers scoped to a single multiagent task — their messages never enter long-term history.

**Two separate histories exist**:
- **Frontend `history` array** (`HomePage.vue`): GUI display only. Shows everything including expert messages, tool calls, intermediate overseer decisions. This is what the user sees.
- **Backend `ConversationStore`**: LLM context. Only stores consigliere-relevant messages. This is what gets sent to models.

**Visibility rules** (`ConversationStore`):
- `"public"` — User messages + consigliere final text responses. Visible to all consigliere personas.
- `"consigliere"` — Tool interactions (AIMessage with tool_calls + ToolMessage results) from chat/agent/overseer/synthesizer. Visible to consigliere personas but never to experts.
- Expert tool calls and intermediate messages are never stored in ConversationStore — they live only in LangGraph state during the active task.

**What gets stored per mode**:
| Mode | Stored in ConversationStore |
|------|----------------------------|
| Chat | user message (public) + assistant response (public) |
| Agent | user message (public) + final response (public) + tool interactions (consigliere) |
| Parallel | user message (public) + synthesizer final response (public) + synthesizer tool interactions (consigliere) |
| Collaborative | user message (public) + overseer final answer (public) + overseer tool interactions (consigliere) |

**What each persona sees**:
- **Chat/Agent/Overseer/Synthesizer**: Full consigliere history via `get_history_for_consigliere()` — all `public` + `consigliere` entries from all past turns
- **Experts**: Only the current task's user query + peer discussion + own tool chain (no cross-turn history, no other persona's tool calls)

**Example conversation flow**:
```
Turn 1 (agent mode):
  [user] "Write me a title"           → stored as public
  [agent tool calls]                   → stored as consigliere
  [agent] "I wrote a title"           → stored as public

Turn 2 (parallel multiagent):
  [user] "Suggest an abstract"        → stored as public
  [expert 1 tools + response]         → NOT stored (task-scoped only)
  [expert 2 tools + response]         → NOT stored (task-scoped only)
  [synthesizer tool calls]            → stored as consigliere
  [synthesizer] "Combined response"   → stored as public

Turn 3 (chat mode):
  Chat LLM sees: turn 1 user + agent tools + agent response
                 + turn 2 user + synthesizer tools + synthesizer response
  Experts would see: ONLY the new user query
```

**Key methods** (`ConversationStore`):
- `start_turn(conversation_id)` → increments turn counter, returns turn number
- `add_user_message(...)` → stores user message as `public`
- `add_public_response(...)` → stores final assistant response as `public`
- `add_consigliere_messages(...)` → stores tool interactions as `consigliere`
- `get_history_for_consigliere(conversation_id)` → returns all entries (public + consigliere)
- `rollback_turn(conversation_id, turn)` → removes all entries from a failed turn

**Frontend sends only the new user message** (+ system message if custom prompt). All prior context comes from ConversationStore on the backend. The `conversationId` parameter (derived from `threadId` in `HomePage.vue`) links requests across mode switches.

### Checkpoint Persistence

`IndexedDBSaver` in `src/frontend/api/checkpoints.ts` implements LangGraph's `BaseCheckpointSaver` to persist conversation state in IndexedDB via Dexie, enabling conversation history restoration.

### Backend Communication & Error Handling

**Server-Sent Events (SSE) Streaming**:
- Backend streams responses using SSE format: `event: <type>\ndata: <json>\n\n`
- Event types: `text`, `tool_call`, `tool_result`, `error`, `done`
- `parseSSEStream()` in `src/frontend/api/backend.ts` parses events and invokes callbacks
- Accumulates `fullContent` for text events (backend sends accumulated content per event)

**Error Handling Philosophy** (per CLAUDE.md coding principles):
- **Fail loudly**: All errors propagate to user, no silent catches
- Network errors display actual error messages (not generic "Something went wrong")
- SSE parse failures break processing loop and show error
- HTTP errors include status code and response text
- Diagnostic logging at each pipeline stage for debugging

**Streaming Control**:
- `ENABLE_STREAM` flag in `src/backend/agents/chat_agent.py` (line 17)
- When `False`: Full response accumulated before sending (easier debugging)
- When `True`: Incremental chunks streamed as generated (better UX)

**Thinking Tag Filtering** (for reasoning models like DeepSeek-R1):
- `ThinkingFilter` class filters `<think>...</think>` blocks from LLM responses
- Controlled by `filter_thinking` parameter (boolean, default: `true`)
- For LMStudio provider, configurable via GUI checkbox: Settings → LMStudio → "Filter Thinking Blocks"
- When enabled: Removes internal reasoning tokens from streamed responses
- When disabled: Shows full reasoning process including thinking blocks
- Works in both streaming and non-streaming modes

## Important Patterns

### Frontend
- The app initializes inside `Office.onReady()` callback in `main.ts`
- Path alias `@/` maps to `src/frontend/` directory
- Settings use localStorage with keys defined in `src/frontend/utils/enum.ts`
- i18n locale files must have sorted keys (ESLint rule enforced)
- `async_hook.js` is a polyfill stub for LangChain browser compatibility

### Settings System
**Declarative Settings Architecture**:
- Settings defined in `src/frontend/utils/settingPreset.ts` with type, default value, and localStorage keys
- `SettingsPage.vue` dynamically renders settings based on provider prefix and setting type
- Settings flow: GUI → localStorage → provider options → request body → backend

**Setting Types**:
- `'input'`: Text input fields
- `'select'`: Dropdown menus
- `'inputNum'`: Number input fields
- `'checkbox'`: Boolean checkboxes (added for `lmstudioFilterThinking`)

**Provider-Specific Settings**:
- Settings with provider prefix (e.g., `lmstudio*`) automatically appear only for that provider
- Example: `lmstudioFilterThinking` only shows when LMStudio is selected
- Helper functions: `inputSetting()`, `selectSetting()`, `inputNumSetting()`, `checkboxSetting()`

**Adding New Settings**:
1. Add localStorage key to `src/frontend/utils/enum.ts`
2. Register setting in `Setting_Names` array and `settingPreset` object
3. Add i18n labels to `src/frontend/i18n/locales/{en,zh-cn}.json`
4. Add TypeScript type to relevant interface in `src/frontend/api/types.ts`
5. Include in provider options in `src/frontend/pages/HomePage.vue`
6. Add to request body interfaces in `src/frontend/api/backend.ts`
7. Add to Pydantic schema in `src/backend/schemas.py`
8. Use in backend logic (e.g., `src/backend/agents/chat_agent.py`)

### Backend Integration
- Backend URL defaults to same origin (empty string) for production
- Can be overridden with `setBackendUrl('http://localhost:8000')` for dev
- `isBackendEnabled()` checks localStorage `'useBackend'` key (defaults to `true`)
- Frontend converts provider name `'official'` → `'openai'` for backend
- Tool names mapped: `fetchWebContent` → `fetch_url`, `searchWeb` → `web_search`, etc.
- API credentials extracted from provider option objects and sent to backend
- Console logging with `[Backend]` and `[HomePage]` prefixes for debugging

### Agent System
**Single Agent** (`src/backend/agents/chat_agent.py`):
- LangGraph `StateGraph` with `agent` → `tools` loop, compiled with `MemorySaver` checkpointer
- `agent_node`: Binds server + client tools to model, invokes LLM
- `tool_node`: Executes server tools inline, uses `interrupt()` for client-side Word tools
- Agent execution controlled by `recursion_limit` parameter (default: 25, range: 1-100)
- Configurable via GUI: Settings → General → "Agent Max Iterations"

**Agent Functions**:
- `stream_chat()`: Simple chat streaming (no tools), stores to ConversationStore
- `stream_agent()`: Streams agent responses with tool calls using SSE, stores to ConversationStore
- `resume_agent()`: Resumes paused agent after client tool execution
- All functions accept `conversation_id` + `conversation_store` for unified history

**System Prompts** (`src/backend/prompts/system_prompts.py`):
All system prompts are centralized in a single file for easier maintenance:
- **Chat Mode**: `generate_chat_system_prompt(language)` - Simple 30-word prompt
- **Agent Mode**: `generate_agent_system_prompt(language, surgical_updates)` - Comprehensive 600-word prompt with tool instructions
- **MultiAgent Expert**: `generate_multiagent_expert_prompt(expert_name, expert_index, total_experts, round_num, use_memory, memory_content, mode)` - Context-aware prompts for parallel/collaborative modes
- **MultiAgent Synthesizer**: `generate_multiagent_synthesizer_prompt(expert_responses)` - Aggregation prompts (with or without explicit expert feedback)
- **MultiAgent Overseer**: `generate_multiagent_overseer_prompt(total_experts, current_round, max_rounds)` - Evaluation prompts for collaborative mode
- **Custom Prompts**: Quick actions and saved prompts are sent from frontend as system messages

**Prompt Injection Logic** (`src/backend/agents/chat_agent.py`):
- If `language` parameter provided in request → Backend generates default system prompt
- If `language` absent → Frontend provided custom system prompt (first message with role='system')
- Function: `inject_system_prompt_if_needed(messages, language, prompt_generator)`
- Frontend logic in `src/frontend/pages/HomePage.vue` determines when to use custom vs. default prompts

**Architecture Benefits**:
- **Single Source of Truth**: All system prompts (chat, agent, multiagent) in one file
- **Consistent Naming**: All functions follow `generate_*_prompt()` pattern
- **Easier Maintenance**: Prompt updates in one predictable location (`src/backend/prompts/system_prompts.py`)
- **Better Separation**: Orchestration logic (`src/backend/agents/chat_agent.py`, `src/backend/agents/chat_multiagent.py`) separate from prompt content
- **Reusability**: Prompt functions can be imported and reused across different modes

**Important**: Never name local wrapper functions the same as imported library functions (e.g., don't name a local function `create_agent` when importing `from langchain.agents import create_agent`) to avoid infinite recursion.

## Deployment

### Word Add-in
- `release/instant-use/manifest.xml` - Points to hosted version
- `release/self-hosted/manifest.xml` - For local/Docker deployment
- Docker image: `kuingsmile/word-gpt-plus`

### Python Backend
- **Development**: Run `python src/backend/main.py` on port 8000
- **Production**: Deploy FastAPI app with uvicorn/gunicorn
- **Docker**: Backend can be containerized separately or with frontend
- **CORS**: Currently allows all origins (`allow_origins=["*"]`) - restrict in production
- **Static Assets**: Backend serves frontend static files from `/dist` directory

## Language

- While the codebase has support for chinese, we can concentrate on English for app development, omitting special needs for chinese.
