# Python Backend for WordLLMs

FastAPI backend that handles all LLM/AI calls, replacing browser-based LangChain with server-side Python.

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

## Debugging

Set breakpoints in Python files and use the debug configurations:

**Breakpoint locations:**
- [main.py](main.py) - API endpoints, SSE streaming
- [providers/*.py](providers/) - LLM provider setup
- [agents/chat_agent.py](agents/chat_agent.py) - Agent logic, tool execution
- [tools/*.py](tools/) - Tool implementations

**Useful debug settings:**
- `justMyCode: false` - Step into library code (LangChain, FastAPI)
- `console: integratedTerminal` - See server logs in terminal

### Disable Streaming for Easier Debugging

Async streaming can be difficult to debug. To disable streaming and get complete responses at once:

1. Open [src/backend/agents/chat_agent.py](agents/chat_agent.py)
2. Change `ENABLE_STREAM = True` to `ENABLE_STREAM = False` (line 17)
3. Restart the server

With streaming disabled:
- Chat responses return all at once instead of token-by-token
- Agent responses return complete (including all tool calls)
- Easier to set breakpoints and inspect full responses
- Better for step-through debugging

**Note:** Remember to re-enable streaming (`ENABLE_STREAM = True`) before production use.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/tools` | GET | List available tools |
| `/api/chat` | POST | Chat completion (streaming) |
| `/api/agent` | POST | Agent with tools (streaming) |
| `/` | GET | Serve frontend (after `yarn build`) |

## Architecture

```
FastAPI Server (port 8000)
├── /api/chat - Simple chat (no tools)
├── /api/agent - Agent with tools
├── /api/health - Health check
└── / - Static frontend files

Tools:
├── web_search - DuckDuckGo search
├── fetch_url - Fetch web content
├── calculate - Math expressions
└── get_current_date - Current date/time

Providers:
├── openai - OpenAI (with custom base URL)
├── azure - Azure OpenAI
├── gemini - Google Gemini
├── groq - Groq
└── ollama - Ollama (local)
```

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

None required - all config passed via API request body.

## Logs

Server logs appear in the integrated terminal. Look for:
- `INFO: Started server process` - Server started
- `INFO: 127.0.0.1 - "POST /api/chat"` - Request received
- Python exceptions with full stack traces
