# BOLT

**Built On Local Terrain** — a local AI companion that runs entirely on your machine.

BOLT is a hive-mind framework powered by Ollama. One personality, multiple brain regions (models) that activate based on what you need. It detects your hardware and self-configures — no cloud, no API keys, no data leaving your machine.

## Quick Install

```bash
curl -fsSL https://raw.githubusercontent.com/Jamescode-cpt/bolt/main/install.sh | bash
```

This installs system deps, Ollama, pulls the right models for your hardware, and gets BOLT running.

## Requirements

- **Python 3.10+**
- **Ollama** (installed automatically by the installer)
- **8GB+ RAM** (more RAM = bigger models = smarter BOLT)

| RAM | Tier | Models |
|-----|------|--------|
| 4-6 GB | minimal | 1.5b router + 3b companion |
| 8-12 GB | standard | + 7b companion, 3b + 7b coders |
| 16-24 GB | full | + 14b coder |
| 32GB+ | beast | + 32b coder (architect/reviewer) |

## Manual Install

```bash
# 1. Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 2. Clone BOLT
git clone https://github.com/Jamescode-cpt/bolt.git ~/bolt
cd ~/bolt

# 3. Install Python deps
pip install -r requirements.txt

# 4. Run (first launch triggers setup)
python3 bolt.py
```

## Usage

```bash
# CLI mode
python3 bolt.py

# Web UI (access from phone)
python3 bolt.py --web

# Re-run setup
python3 bolt.py --setup
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
| `/help` | Show all commands |

### Web UI

Start with `python3 bolt.py --web`, then open `https://YOUR_IP:3000` on your phone. Features:
- SSE streaming responses
- Voice input (Whisper STT, requires `pip install faster-whisper`)
- All slash commands via hamburger menu
- BOLT generates self-signed SSL certs on first run — your browser may show a security warning, this is normal for local self-signed certs

## Architecture

```
bolt.py          CLI entry point, commands, main loop
brain.py         Router + model orchestration + tool loop
identity.py      User profile learning, context relay
pipeline.py      Multi-model build pipeline (background, parallel)
tools.py         Tool registry + built-in tools
memory.py        SQLite persistence
workers.py       Background summarizer + task tracker
config.py        Model roster, prompts, identity
env.py           Hardware detection, paths, model tiers
setup.py         First-run setup wizard
web.py           Flask web server + SSE streaming
custom_tools/    50+ drop-in tool plugins
```

### How It Works

1. **Router** (1.5b, always loaded) classifies your message
2. The right **brain region** activates (3b-32b depending on complexity)
3. Every model gets the same **identity injection** — BOLT is one personality
4. **Tools** execute real commands on your machine (shell, files, code, web, etc.)
5. **Profile learner** picks up facts about you in the background
6. **Build pipeline** runs multi-model code generation with parallel workers

## Tools

BOLT ships with 50+ tools including: shell, file I/O, web search, git, system info, network, screenshots, clipboard, timers, notifications, weather, archive, diff, cron, packages, TTS, task manager, backups, encryption, DNS, hashing, port scanning, QR codes, RSS, YouTube, translation, PDF reading, Docker, SSH, notes, calendar, image tools, and more.

All tools are plugins in `custom_tools/` — drop in a `.py` file with `TOOL_NAME`, `TOOL_DESC`, and `def run(args)` to add your own.

## License

MIT — Created by James Connolly, [CPTRI](https://github.com/Jamescode-cpt)
