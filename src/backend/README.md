# Python Backend for WordLLMs

FastAPI backend that handles all LLM/AI calls, replacing browser-based LangChain with server-side Python. Supports chat, single-agent, and multi-agent modes with unified conversation history.

## Setup

```bash
# Install dependencies (from project root)
pip install -r requirements.txt
```

## Running

### Option 1: Command Line
```bash
# From project root
uvicorn src.backend.main:app --host 0.0.0.0 --port 8000

# With auto-reload for development
uvicorn src.backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### Option 2: VSCode Tasks
Press `Ctrl+Shift+P` → "Tasks: Run Task" → Select:
- **Start Python Backend** - Run without reload
- **Start Python Backend (Reload)** - Run with auto-reload

### Option 3: VSCode Debug
Press `F5` or go to Run & Debug panel, select:
- **Python: Debug Backend** - Debug mode
- **Python: Debug Backend (Reload)** - Debug with auto-reload

## API Endpoints

### Chat & Agent
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chat` | POST | Chat completion (SSE streaming, no tools) |
| `/api/agent` | POST | LangGraph agent with tools (SSE streaming) |
| `/api/agent/continue` | POST | Resume agent after client-side tool execution |
| `/api/multiagent` | POST | Multi-expert orchestration (parallel or collaborative) |
| `/api/multiagent/continue` | POST | Resume multiagent after client tool results |

### Thread & Conversation Management
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/threads` | GET | List conversation threads |
| `/api/threads/{thread_id}` | GET | Retrieve a single thread |
| `/api/threads` | POST | Save/update a thread |
| `/api/threads/{thread_id}` | DELETE | Delete a thread |
| `/api/conversation/edit` | POST | Edit user message at specific turn |
| `/api/conversation/truncate` | POST | Truncate conversation from given turn |
| `/api/conversation/fork` | POST | Fork conversation up to specific turn |
| `/api/context-stats/{id}` | GET | Get character and token counts |

### History Database
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/history/path` | GET | Get current conversation history DB path |
| `/api/history/path` | POST | Switch to different DB path |
| `/api/history/browse-dir` | GET | Browse directories for .db files |

### Discovery & Static
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/tools` | GET | List available tools with descriptions |
| `/` | GET | Serve frontend (after `yarn build`) |

## Architecture

```
src/backend/
├── main.py                  # FastAPI app, all endpoints, CORS, static serving
├── schemas.py               # Pydantic request/response models
├── conversation_store.py    # SQLite-backed unified conversation history
├── file_processing.py       # File attachment handling (MarkItDown converter)
├── agents/
│   ├── chat_agent.py        # Single agent: LangGraph StateGraph with ReAct loop
│   ├── chat_multiagent.py   # Multi-expert: parallel & collaborative modes
│   ├── context.py           # Token counting, message trimming
│   ├── llm_retry.py         # Timeout enforcement, tenacity retry
│   └── utils.py             # Text extraction helpers
├── prompts/
│   └── system_prompts.py    # All system prompt generation functions
├── providers/
│   ├── base.py              # Model factory (create_model)
│   ├── provider_openai.py   # OpenAI
│   ├── provider_azure.py    # Azure OpenAI
│   ├── provider_gemini.py   # Google Gemini
│   ├── provider_groq.py     # Groq
│   ├── provider_ollama.py   # Ollama (local)
│   ├── provider_lmstudio.py # LM Studio (OpenAI-compatible)
│   └── provider_anthropic.py # Anthropic Claude
├── tools/
│   ├── __init__.py          # Tool registry & categorization
│   ├── web.py               # web_search (Tavily), fetch_url
│   ├── calculator.py        # Safe math eval
│   ├── date.py              # Current date/time
│   └── word_tools.py        # 27 client-side Word tool schemas
└── data/                    # Runtime: SQLite DBs, config.json
```

### Providers

| Provider | Module | LangChain Class |
|----------|--------|-----------------|
| OpenAI | `provider_openai.py` | `ChatOpenAI` |
| Azure OpenAI | `provider_azure.py` | `AzureChatOpenAI` |
| Google Gemini | `provider_gemini.py` | `ChatGoogleGenerativeAI` |
| Groq | `provider_groq.py` | `ChatGroq` |
| Ollama | `provider_ollama.py` | `ChatOllama` |
| LM Studio | `provider_lmstudio.py` | `ChatOpenAI` (custom base_url) |
| Anthropic | `provider_anthropic.py` | `ChatAnthropic` |

### Tools

**Server-side tools** (run on backend):
- `web_search` - Tavily API search (requires API key)
- `fetch_url` - HTTP fetch with HTML-to-text conversion
- `calculate` - Safe math expression evaluation
- `get_current_date` - Current date/time info

**Client-side Word tools** (27 tools, executed in browser via Office.js):
- **Read-only**: `get_selected_text`, `get_document_content`, `get_document_properties`, `get_range_info`, `get_table_info`, `find_text`, `find_and_select_text`, `select_between_text`, `select_text`, `go_to_bookmark`
- **Write**: `insert_text`, `replace_selected_text`, `append_text`, `insert_paragraph`, `delete_text`, `search_and_replace`, `search_and_replace_in_selection`, `format_text`, `clear_formatting`, `set_paragraph_format`, `set_style`, `insert_table`, `insert_list`, `insert_page_break`, `insert_image`, `insert_bookmark`, `insert_content_control`

Tool categorization (`READ_ONLY_WORD_TOOLS` vs `WRITE_WORD_TOOLS`) is used in multiagent mode to restrict expert access.

### Execution Modes

**Single Agent** (`chat_agent.py`):
- LangGraph `StateGraph` with agent → tools loop
- `stream_chat()` for simple chat, `stream_agent()` for tool-enabled agent
- `resume_agent()` to continue after client-side Word tool execution
- ThinkingRouter filters `<think>...</think>` blocks for reasoning models

**Multi-Agent** (`chat_multiagent.py`):
- **Parallel mode**: Experts run concurrently, synthesizer combines results
- **Collaborative mode**: Experts iterate with overseer evaluation over multiple rounds
- Expert/supervisor tool separation (experts get read-only, supervisor gets all)

### Conversation History

SQLite-backed unified "consigliere" model (`conversation_store.py`) maintains cross-mode history:
- **Public entries**: User messages + final assistant responses (visible to all)
- **Consigliere entries**: Tool interactions from chat/agent/overseer/synthesizer
- Expert messages are task-scoped and never stored in long-term history
- Linked across mode switches via `conversation_id`

### SSE Streaming

All endpoints stream responses using Server-Sent Events:
- Event types: `text`, `tool_call`, `tool_result`, `client_tool_call`, `error`, `done`
- Configurable timeout per request (5–900 seconds)
- Retry with tenacity (3 attempts, 1s initial interval)

## Debugging

Set breakpoints in Python files and use the debug configurations:

**Breakpoint locations:**
- [main.py](main.py) - API endpoints, SSE streaming
- [agents/chat_agent.py](agents/chat_agent.py) - Agent logic, tool execution
- [agents/chat_multiagent.py](agents/chat_multiagent.py) - Multi-expert orchestration
- [providers/*.py](providers/) - LLM provider setup
- [tools/*.py](tools/) - Tool implementations

### Disable Streaming for Easier Debugging

1. Open [agents/chat_agent.py](agents/chat_agent.py)
2. Change `ENABLE_STREAM = True` to `ENABLE_STREAM = False` (line 17)
3. Restart the server

With streaming disabled, responses return all at once instead of token-by-token, making step-through debugging easier. Remember to re-enable before production use.

## Development Workflow

1. **Start backend in debug mode**: `F5` → "Python: Debug Backend (Reload)"
2. **Set breakpoints** in Python files
3. **Test with curl**:
   ```bash
   curl http://localhost:8000/api/health
   ```
4. **Or build & test with frontend**:
   ```bash
   yarn build
   # Frontend now served at http://localhost:8000/
   ```

## Environment Variables

None required — all config (API keys, model selection, parameters) is passed via API request body.

## Logs

Server logs appear in the integrated terminal. Look for:
- `INFO: Started server process` - Server started
- `INFO: 127.0.0.1 - "POST /api/chat"` - Request received
- Python exceptions with full stack traces
