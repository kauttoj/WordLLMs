<div align="center">
  <a href="https://github.com/kauttoj/WordLLMs">
    <img src="./public/logo.svg" alt="Logo" height="100">
  </a>

  <h2 align="center">WordLLMs</h2>
  <p align="center">
    AI Agents and Multi-Agent collaboration inside Microsoft Word
    <br />
    <a href="https://github.com/kauttoj/WordLLMs/blob/master/LICENSE">
      <img src="https://img.shields.io/github/license/kauttoj/WordLLMs?style=flat-square" alt="license" />
    </a>
    <a href="https://github.com/kauttoj/WordLLMs/releases">
      <img src="https://img.shields.io/github/v/release/kauttoj/WordLLMs?style=flat-square" alt="release" />
    </a>
    <a href="https://github.com/kauttoj/WordLLMs/stargazers">
      <img src="https://img.shields.io/github/stars/kauttoj/WordLLMs?style=flat-square" alt="stars" />
    </a>
    <br />
    <a href="#features">Features</a> •
    <a href="#getting-started">Getting Started</a> •
    <a href="#installation">Installation</a> •
    <a href="#usage">Usage</a>
  </p>
</div>

> **Warning**: This is the first release of WordLLMs. The application is still under active development and testing. Expect bugs, breaking changes, and incomplete features. Bug reports and feedback are welcome via [Issues](https://github.com/kauttoj/WordLLMs/issues).

> Starting from [Word GPT Plus](https://github.com/Kuingsmile/word-GPT-Plus), WordLLMs is a complete overhaul with a Python backend, multi-agent orchestration, revised tools, file attachments, GUI enchancements and support for all major Large Language Model (LLM) providers including local models.

WordLLMs is self-hosted, running locally on your machine storing all data on your device. No data is shared or stored elsewhere, except in two situations:

- LLM API calls: You must choose some providers for LLMs, which can include official OpenAI, Anthropic, Google endpoints, or their Azure counterparts. You can also use a local, self-hosted models.

- Web search: If you enable web search tool, LLM sends web queries to Tavily service (https://app.tavily.com). You can disable web search tool completely.

If you use a self-hosted LLM running LMstudio or Ollama, you can run the WordLLM fully offline.

## Introduction

WordLLMs brings the full power of modern LLMs directly into Microsoft Word. It's a free alternative to MS Copilot. Chat with any model, let an autonomous agent read and edit your document, or have multiple AI experts collaborate on a task — all without leaving Word.

The application is powered by a **Python/FastAPI backend** using **LangChain** and **LangGraph** for agent orchestration, with a **Vue 3** frontend that communicates via Server-Sent Events for real-time streaming.

![Image](https://github.com/kauttoj/WordLLMs/blob/master/public/screenshot.png)

## Features

### 7 AI Providers, All Latest Models (updated regularly)

| Provider | Example Models | Notes |
|----------|---------------|-------|
| **OpenAI** | GPT-5.2 Pro, GPT-5.2, GPT-5.1, GPT-5 Mini/Nano, GPT-4.1 | Compatible with DeepSeek and other OpenAI-compatible APIs via custom base URL |
| **Anthropic** | Claude Opus 4.6/4.5, Claude Sonnet 4.6/4.5, Claude Haiku 4.5 | |
| **Google Gemini** | Gemini 3.1 Pro, Gemini 3 Pro/Flash, Gemini 2.5 Pro/Flash | |
| **Azure OpenAI** | Custom deployment names | Full Azure integration with configurable API versions |
| **Groq** | Llama 3.3/4, Qwen3, Kimi-K2, GPT-OSS | Ultra-fast inference |
| **Ollama** | Any locally loaded model | Local deployment, fully private |
| **LM Studio** | Any locally loaded model | Local deployment, fully private |

All providers support **custom model names** — enter any model your endpoint serves.

### Three Operating Modes

#### Chat Mode
Straightforward conversation with any LLM without any tools. LLM only sees what you tell it. Use it for Q&A, brainstorming, translation, or content generation. 

#### Agent Mode
An autonomous LangGraph agent with access to **25+ tools** that can read, write, search, and format your Word document. The agent plans multi-step actions, executes them, and reports results — all in a single conversation turn.

- Reads your document or selection, then makes targeted edits
- Multi-step reasoning with up to 100 iterations (configurable)
- Web search and URL fetching for research tasks

#### Multi-Agent Mode
 **2-4 LLM experts collaborate** on your document, each potentially from a different provider. Two collaboration strategies are available:

**Parallel Mode** — All experts analyze the document independently and in parallel. A synthesizer agent aggregates their feedback and makes the final edits. Best for getting diverse perspectives quickly.

**Collaborative Mode** — Experts engage in a multi-round (Round Robin -type) discussion (up to 10 rounds), building on each other's points. An overseer agent evaluates after each round and decides whether to continue or conclude. Best for iterative refinement of complex tasks.

Key multi-agent capabilities:
- **Mix providers freely**: e.g., Expert 1 = Claude Opus, Expert 2 = GPT-5.2, Overseer = Gemini
- **Tool access control**: Experts get read-only document access; only the overseer/synthesizer can write
- **Per-expert memory**: In collaborative mode, each expert maintains notes across rounds

### 25+ Document Tools

The agent (and multi-agent) modes can manipulate your Word document through Office.js:

**Reading** — Get selected text, full document content, document properties, table structures, text search with context

**Writing** — Insert/replace/append text, create paragraphs with styles, insert tables, lists, images, page breaks, bookmarks, content controls

**Formatting** — Bold, italic, underline, font changes, color, highlighting, paragraph alignment/spacing/indentation, Word styles (Heading 1, etc.), clear formatting, search-and-replace

**General** — Web search (Tavily), URL fetching, math calculations, date/time

### Quick Actions

One-click operations on selected text via customizable toolbar buttons, for example:

- **Translate** — Using LLM capabilities
- **Polish** — Professional writing improvement
- **Academic** — Scholarly writing enhancement
- **Summarize** — Concise summaries
- **Grammar** — Proofread and correct
- **3 custom slots** — Define your own actions with custom system/user prompts
- **Custom role** — Define custom instructions to steer LLMs (added to system prompt)

### Conversation Management

- **Persistent history** stored in SQLite (configurable database path)
- **Edit** past messages, **retry** from any turn, **fork** conversations into branches
- **File attachments** — Upload text files or images into the conversation
- Cross-mode continuity: switch between chat, agent, and multi-agent modes within the same conversation thread

### Customization

- **System prompt presets** — Save and switch between multiple system prompts (steer responses)
- **Per-provider settings** — Temperature, max tokens, custom base URLs, API versions
- **Custom models** — Add any model name for any provider
- **Agent iteration limit** — 1 to 500 steps (default 100)
- **Configurable timeouts** — 5 to 900 seconds per LLM call (default 90s)

## Getting Started

### Requirements

#### Software

- Microsoft Word 2016/2019 (retail version), Word 2021, or Microsoft 365
- [Edge WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)
- Python 3.10+ (for the backend)
- Node.js 20+ (only for building from source)

> **Note**: Works only with .docx files (not compatible with older .doc format)

#### API Access

You need an API key from at least one provider:

- **OpenAI**: [OpenAI Platform](https://platform.openai.com/account/api-keys)
- **Anthropic**: [Anthropic Console](https://console.anthropic.com/)
- **Azure OpenAI**: [Azure OpenAI Service](https://go.microsoft.com/fwlink/?linkid=2222006)
- **Google Gemini**: [Google AI Studio](https://developers.generativeai.google/)
- **Groq**: [Groq Console](https://console.groq.com/keys)
- **Ollama / LM Studio**: No API key needed — runs locally

## Installation

WordLLMs is essentially a "mini" website inside Word, Word only presents it. As results, you need to serve WordLLMs application outside Word. Choose the method that best suits your needs:

### Method 1: Docker Deployment (Recommended)

0. **Install Docker desktop** https://www.docker.com/products/docker-desktop

1. **Choose a folder on your PC** where WordLLMs will store your conversation history. For example: `C:\Users\YourName\WordLLMs`

   Create the folder first if it doesn't exist.

2. Pull and run the Docker image. Open **Command Prompt** and at the FIRST time, run:

   ```
   docker pull kauttoj/wordllms
   docker run --name wordllms -p 3000:8000 -v "C:\Users\YourName\WordLLMs:/app/data" kauttoj/wordllms
   ```

   Replace `C:\Users\YourName\WordLLMs` with the folder you chose in step 1. Keep the `:/app/data` part exactly as shown — that is the path inside the container and must not be changed.

   Later, when you restart your app, run
   
   ```
   docker start wordllms
   ```

   which restart the old container without creating a new one. You can also start the image from Docker Desktop by clicking the image. You can learn more at https://www.docker.com/blog/getting-started-with-docker-desktop

   > **Why this matters**: Your conversation history is stored in a file on your PC. The `-v` flag is how Docker links your chosen Windows folder to the app running inside the container. Without it, all conversations are permanently lost every time the container stops. The app's file browser can only access folders that were linked this way at startup — you cannot change the folder later from inside the app.

3. Open WordLLMs in Word, go to **Settings** and set **History Database Path** to:
   ```
   /app/data/conversations.db
   ```
   Click the folder icon to browse existing `.db` files, or type the path directly. This path always uses the `/app/data` form regardless of what Windows folder you chose — Docker translates it automatically.

4. Download [manifest.xml](https://github.com/kauttoj/WordLLMs/blob/master/release/self-hosted/manifest.xml).
5. [Optional: Edit `manifest.xml` if you changed the host port in the `docker run` command (e.g., if you used `-p 8080:8000`, replace `localhost:3000` with `localhost:8080`).]
6. Proceed to the [Add-in Installation Guide](#add-in-installation-guide).

> All processing happens in the container, it's the "brains" of the app. You need to run the Docker image (or Python app) each time you use WordLLMs. Your either do this via terminal OR Docker desktop client.

### Method 2: Build from Source

*Requires Node.js 20+ and Python 3.10+*

1. Clone and install dependencies:

   ```bash
   git clone https://github.com/kauttoj/WordLLMs.git
   cd WordLLMs
   yarn install
   pip install -r requirements.txt
   ```

2. Build the frontend:

   ```bash
   yarn build
   ```

3. Start the backend (serves both the API and built frontend static files):

   ```bash
   uvicorn src.backend.main:app --host 0.0.0.0 --port 3000
   ```

4. Download [manifest.xml](https://github.com/kauttoj/WordLLMs/blob/master/release/self-hosted/manifest.xml) and update the URLs to match your server address.
5. Proceed to the [Add-in Installation Guide](#add-in-installation-guide).

## Add-in Installation Guide

You will need to sideload the add-in into Microsoft Word.

Full instructions from Microsoft: [Sideload Office Add-ins](https://learn.microsoft.com/en-us/office/dev/add-ins/testing/create-a-network-shared-folder-catalog-for-task-pane-and-content-add-ins)

1. Go to the folder where you saved the `manifest.xml` file, for example `C:\Users\username\Documents\WordLLMs`.
2. Open the context menu for the folder (right-click the folder) and select **Properties**.
3. Within the **Properties** dialog box, select the **Sharing** tab, and then select **Share**.
![image](https://learn.microsoft.com/en-us/office/dev/add-ins/images/sideload-windows-properties-dialog.png)
4. Within the **Network access** dialog box, add yourself and any other users you want to share, choose the **Share** button. When you see confirmation that your folder is shared, note the **full network path** displayed immediately following the folder name.
![image](https://learn.microsoft.com/en-us/office/dev/add-ins/images/sideload-windows-network-access-dialog.png)
5. Open a new document in Word, choose the **File** tab, and then choose **Options**.
6. Choose **Trust Center**, and then choose the **Trust Center Settings** button.
7. Choose **Trusted Add-in Catalogs**.
8. In the **Catalog Url** box, enter the **full network path** and then choose **Add Catalog**.
9. Select the **Show in Menu** check box, and then choose **OK**.
![image](https://learn.microsoft.com/en-us/office/dev/add-ins/images/sideload-windows-trust-center-dialog.png)
10. Close and then restart Word.
11. For older Word: Click **Insert** > **My Add-ins** > **Shared Folder**, choose **WordLLMs**, and then choose **Add**.  
    For current Word: Click **Home** > **Add-ins** > **Advanced** at bottom > click **WordLLMs**. See images.  
![Image](https://github.com/kauttoj/WordLLMs/blob/master/public/addins_option_1.png)
![Image](https://github.com/kauttoj/WordLLMs/blob/master/public/addins_option_2.png)
![Image](https://github.com/kauttoj/WordLLMs/blob/master/public/addins_option_3.png)
12. Enjoy!

## Usage

### Getting Started

After opening WordLLMs, click the **Settings** button on the homepage to configure your preferred AI providers and API keys.

### Chat Mode

Type your message and press Enter. Responses stream in real time. Use the quick action buttons for common tasks like translation or polishing.

### Agent Mode

Switch to Agent mode and give the AI instructions that involve your document:

- *"Read the entire document and create a summary at the beginning"*
- *"Format all section headings as Heading 2 and make them blue"*
- *"Search the web for recent statistics on X and insert them after paragraph 3"*
- *"Create a table comparing the three approaches mentioned in the document"*

The agent will plan its steps, use the appropriate tools, and report back. You can watch tool calls and results in real time.

### Multi-Agent Mode

Switch to Multi-Agent mode and configure:

1. **Number of experts** (2-4)
2. **Strategy**: Parallel or Collaborative
3. **Model per expert**: Pick a different provider/model for each expert
4. **Max rounds** (collaborative mode): 1-10

Then give your task. Examples:

- *"Review this document for logical consistency, grammar, and tone"* (parallel — each expert focuses on a different aspect)
- *"Debate the pros and cons of the approach described in this document"* (collaborative — experts discuss across rounds)
- *"Rewrite the introduction to be more engaging"* (parallel — get multiple rewrites, synthesizer picks the best)

### Quick Actions

Click the toolbar buttons for instant operations on selected text. The first 5 slots come pre-configured (Translate, Polish, Academic, Summarize, Grammar). The remaining 3 slots are fully customizable with your own system and user prompts.

### Custom Models

For each AI provider:

1. Go to **Settings** > select your provider
2. Enter a custom model name and click **Add**
3. The model appears in the model dropdown

### Configuration Tips

- **Temperature**: Lower (0.3-0.5) for factual tasks, higher (0.7-1.0) for creative tasks (only for non-reasoning, legacy LLMs)
- **Max Tokens**: Increase for longer responses, decrease for concise answers
- **Custom Base URL**: Use for OpenAI-compatible services (DeepSeek, local proxies, etc.)
- **Agent Max Iterations**: Increase for complex multi-step tasks

## Architecture

```mermaid
graph TD
    subgraph Word["Microsoft Word (Office.js)"]
        FE["Vue 3 Frontend (TypeScript)\nChat · Agent · Multi-Agent UI\n25+ Word tools via Office.js\nSSE streaming client"]
    end

    FE -- "SSE (Server-Sent Events)" --> Agents

    subgraph Backend["Python Backend (FastAPI)"]
        Agents["LangGraph Agents\nSingle Agent · Multi-Agent parallel/collab"]
        Providers["LangChain Providers\nOpenAI · Anthropic · Gemini · Azure\nGroq · Ollama · LM Studio"]
        Tools["Server Tools\nWeb search · URL fetch · Math · Date"]
        DB["SQLite Conversation Store\nUnified history across all modes"]
        Agents --> Providers
        Agents --> Tools
        Agents --> DB
    end
```

## Privacy & Security

- **Local storage**: API keys are stored in browser localStorage within the Word add-in sandbox. They are never sent to any server other than the AI provider you configured.
- **Direct connection**: The backend communicates directly with AI providers. There are no intermediary servers.
- **Local models**: Ollama and LM Studio run entirely on your machine — your data never leaves your network.
- **Conversation history**: Stored in a local SQLite database at a path you control.

## Contributing

If you have a suggestion that would make this better, please fork the repo and create a pull request.

## Acknowledgements

WordLLMs started from [Word GPT Plus](https://github.com/Kuingsmile/word-GPT-Plus) by [Kuingsmile](https://github.com/Kuingsmile). Thanks for the original project that provided the foundation for this work.

## License

MIT License

## Show your support

Give a star if you find this app useful.

