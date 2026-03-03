# BOLT

**Built On Local Terrain** — a local-first AI companion that runs on your machine.

BOLT is a hive-mind AI framework powered by Ollama. One personality, multiple brain regions (models) that activate based on what you need. It detects your hardware, pulls the right models, and self-configures. Local by default — cloud optional.

## Quick Install

```bash
curl -fsSL https://raw.githubusercontent.com/Jamescode-cpt/bolt/main/install.sh | bash
```

That's it. BOLT installs system deps, Ollama, pulls models for your hardware, runs setup, and leaves you at a prompt ready to chat.

## GUI Install (No Terminal Required)

If you've never used a terminal, download the graphical installer instead:

1. Download [`install-gui.sh`](https://raw.githubusercontent.com/Jamescode-cpt/bolt/main/install-gui.sh)
2. Right-click the file → **Properties** → **Permissions** → tick **Allow executing as program**
3. Double-click it

The installer walks you through everything with familiar dialog boxes — no typing required. When it's done, a **BOLT icon** appears on your desktop. Click it to launch.

## Requirements

- **Python 3.10+**
- **Ollama** (installed automatically)
- **8GB+ RAM** (more RAM = bigger models = smarter BOLT)

| RAM | Tier | What You Get |
|-----|------|-------------|
| 4-6 GB | minimal | 1.5b router + 3b companion |
| 8-12 GB | standard | + 7b companion, 3b + 7b coders |
| 16-24 GB | full | + 14b coder (stays hot alongside 1.5b + 7b) |
| 32GB+ | beast | + 32b architect/reviewer |

## How the Brain Works

BOLT isn't one model — it's a hive mind. Multiple brain regions, one personality.

### Always-Hot Models
The **1.5b router** is always loaded (~1GB). It classifies every message in milliseconds and routes to the right brain region. You never wait for it.

On **16GB+ systems**, the **7b companion** and **14b coder** also stay hot alongside the router (~13.5GB total). Three brain regions ready instantly — chat, simple code, and complex code all respond without loading delay.

### The 32b Beast
The 32b model is the architect and reviewer — it only loads when you need serious horsepower (`/build` pipeline or hard problems). When the beast activates, the 7b and 14b unload to free RAM. The 1.5b router stays hot the entire time so you can keep chatting. When the beast finishes, the 7b and 14b quietly reload in the background. Nobody notices the switch.

### Cloud Brain (Optional)
BOLT works fully offline. But if you want extra power, set one env var and any cloud LLM becomes another brain region:

```bash
export BOLT_CLOUD_KEY="your-api-key"    # Any provider
```

Cloud is auto-detected from your API key — Anthropic, OpenAI, Groq, OpenRouter, or any OpenAI-compatible endpoint. If the key isn't set or the cloud is unreachable, BOLT falls back to local models seamlessly. No errors, no interruption.

| Key Prefix | Provider | Default Model |
|-----------|----------|---------------|
| `sk-ant-` | Anthropic | Claude Sonnet |
| `sk-` | OpenAI | GPT-4o |
| `gsk_` | Groq | Llama 3.3 70B |
| `sk-or-` | OpenRouter | Claude Sonnet |

Optional overrides:
```bash
export BOLT_CLOUD_MODEL="your-model"    # Override default model
export BOLT_CLOUD_URL="https://..."     # Custom endpoint
```

## Manual Install

```bash
# 1. Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 2. Clone BOLT
git clone https://github.com/Jamescode-cpt/bolt.git ~/bolt
cd ~/bolt

# 3. Install Python deps
pip install -r requirements.txt

# 4. Run (first launch triggers setup wizard)
python3 bolt.py
```

## Usage

```bash
bolt              # CLI mode
bolt --web        # Web UI (phone access)
bolt --setup      # Re-run setup wizard
```

### Commands

| Command | Description |
|---------|-------------|
| `/companion` | Chat mode — just hang out |
| `/code` | Code mode — tools enabled |
| `/build` | Launch multi-model build pipeline |
| `/profile` | See what BOLT knows about you |
| `/forget` | Wipe BOLT's memory of you |
| `/tools` | List all available tools |
| `/web` | Launch web UI |
| `/clear` | New session (keeps profile) |
| `/status` | System status |
| `/help` | Show all commands |

### Web UI

Start with `bolt --web`, then open `https://YOUR_IP:3000` on your phone.

- SSE streaming responses
- Voice input via Whisper STT (`pip install faster-whisper`)
- All slash commands via hamburger menu
- Mobile-first dark theme
- Self-signed SSL certs generated on first run

### Build Pipeline

The `/build` command launches a multi-model code generation pipeline that runs in the background:

1. **Spec** (3b) — turns your conversation into a structured build spec
2. **Architect** (32b) — plans file structure, splits work between workers
3. **Build** (14b + 7b parallel) — workers build their assigned files simultaneously
4. **Review** (32b) — validates everything fits together
5. **Write** — files to disk

You can keep chatting the entire time — the 1.5b router stays loaded throughout.

## Architecture

```
bolt.py          CLI entry point, commands, main loop
brain.py         Router + model orchestration + tool loop
identity.py      User profile learning, context relay
pipeline.py      Multi-model build pipeline (background, parallel)
tools.py         Tool registry + 58 built-in/custom tools
memory.py        SQLite persistence (messages, summaries, tasks)
workers.py       Background summarizer, task tracker, model heartbeat
config.py        Model roster, prompts, identity system
env.py           Hardware detection, dynamic paths, model tiers
setup.py         First-run setup wizard
cloud.py         Provider-agnostic cloud LLM integration
web.py           Flask web server + SSE streaming
custom_tools/    50+ drop-in tool plugins
```

### Identity System

Every model wakes up as BOLT. The identity system injects the same personality, user profile, and context into every brain region. When switching between models, a context relay compresses what just happened so the next model picks up seamlessly. BOLT learns about you over time — name, preferences, projects — stored locally in SQLite.

## Tools

BOLT ships with 58 tools: shell, file I/O, Python exec, web search, git, system info, network diagnostics, screenshots, clipboard, timers, notifications, weather, archive, diff, cron, package management, TTS, task manager, backups, encryption, DNS lookups, hashing, port scanning, QR codes, RSS, YouTube, translation, PDF reading, Docker, SSH, notes, calendar, image tools, and more.

All tools are plugins — drop a `.py` file in `custom_tools/` with `TOOL_NAME`, `TOOL_DESC`, and `def run(args)` to add your own.

## Privacy

- All data stored locally in `data/bolt.db` (SQLite)
- No telemetry, no tracking, no data leaves your machine
- Cloud brain is opt-in only — set the key or don't
- User profile facts stored with confidence scores, wipeable with `/forget`
- `.gitignore` excludes all user data from version control

## License

MIT — Created by James Connolly, [CPTRI](https://github.com/Jamescode-cpt)
