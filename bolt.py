#!/usr/bin/env python3
"""BOLT — Built On Local Terrain. CLI entry point."""

import sys
import os

# Ensure bolt/ is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import memory
import state
import brain
import tools
import pipeline
import identity
import cloud
from identity import ProfileLearnerWorker
from workers import SummarizerWorker, TaskTrackerWorker, HeartbeatWorker
import requests

# ─── ANSI color codes ───
RST   = "\033[0m"
BOLD  = "\033[1m"
DIM   = "\033[2m"

# Blues
B1    = "\033[38;5;17m"   # deep navy
B2    = "\033[38;5;19m"   # dark blue
B3    = "\033[38;5;21m"   # blue
B4    = "\033[38;5;27m"   # bright blue
B5    = "\033[38;5;33m"   # electric blue
B6    = "\033[38;5;39m"   # sky blue
B7    = "\033[38;5;75m"   # light blue

# Yellows
Y1    = "\033[38;5;220m"  # gold
Y2    = "\033[38;5;226m"  # bright yellow
Y3    = "\033[38;5;228m"  # pale yellow
Y4    = "\033[38;5;214m"  # orange-yellow

# Reds
R1    = "\033[38;5;196m"  # bright red
R2    = "\033[38;5;160m"  # deep red
R3    = "\033[38;5;124m"  # dark red

# Greens
G1    = "\033[38;5;82m"   # bright green

# Background highlights
BG_B  = "\033[48;5;17m"   # dark blue bg
BG_Y  = "\033[48;5;220m"  # yellow bg
BG_R  = "\033[48;5;160m"  # red bg


def banner():
    """Print the fancy BOLT startup banner."""
    W = 58  # box width
    h  = f"{B4}{'─' * W}{RST}"
    hb = f"{B5}{'━' * W}{RST}"

    print()
    print(f"  {B5}╔{'━' * W}╗{RST}")
    print(f"  {B5}║{RST}{' ' * W}{B5}║{RST}")

    # Lightning bolt ASCII art — gradient blue/yellow/red
    bolt_lines = [
        f"          {Y2}      ▄▄▄▄▄▄{RST}",
        f"          {Y2}     ▄█{Y1}█████{Y2}▀{RST}",
        f"          {Y1}    ▄███{Y4}██▀▀{RST}",
        f"          {Y4}  ▄████{R1}█▀{RST}",
        f"          {R1} █████████████▄{RST}",
        f"          {R1}  ▀▀▀▀▀{R2}█████▀{RST}",
        f"          {R2}      ▀{R3}███▀{RST}",
        f"          {R3}      ▀█▀{RST}",
        f"          {R3}       ▀{RST}",
    ]

    for line in bolt_lines:
        pad = W - _visible_len(line)
        print(f"  {B5}║{RST}{line}{' ' * max(pad, 0)}{B5}║{RST}")

    print(f"  {B5}║{RST}{' ' * W}{B5}║{RST}")

    # Title line
    title = f"{BOLD}{B6}B {B7}O {Y2}L {R1}T{RST}"
    title_full = f"          {BOLD}{B6}B{RST} {BOLD}{B7}O{RST} {BOLD}{Y2}L{RST} {BOLD}{R1}T{RST}"
    pad = W - _visible_len(title_full)
    print(f"  {B5}║{RST}{title_full}{' ' * max(pad, 0)}{B5}║{RST}")

    # Subtitle
    sub = f"    {DIM}{B7}Built On Local Terrain{RST}"
    pad = W - _visible_len(sub)
    print(f"  {B5}║{RST}{sub}{' ' * max(pad, 0)}{B5}║{RST}")

    print(f"  {B5}║{RST}{' ' * W}{B5}║{RST}")

    # Separator
    sep = f"    {B4}{'─' * 50}{RST}"
    pad = W - _visible_len(sep)
    print(f"  {B5}║{RST}{sep}{' ' * max(pad, 0)}{B5}║{RST}")

    print(f"  {B5}║{RST}{' ' * W}{B5}║{RST}")

    # Mode line
    mode = brain.get_mode()
    mode_icon = "💬" if mode == "companion" else "🔨"
    status = f"    {Y1}⚡{RST} {B7}Ready{RST} {DIM}{B4}│{RST} {DIM}Mode: {Y2}{mode}{RST} {DIM}{B4}│{RST} {DIM}Type {Y2}/help{RST} {DIM}for commands{RST}"
    pad = W - _visible_len(status)
    print(f"  {B5}║{RST}{status}{' ' * max(pad, 0)}{B5}║{RST}")

    # Cloud status line
    if cloud.is_available():
        cloud_status = f"    {DIM}{B4}│{RST} {G1}Cloud: online{RST} {DIM}({cloud.get_display_name()}){RST}"
    else:
        cloud_status = f"    {DIM}{B4}│{RST} {DIM}Cloud: offline (local only){RST}"
    pad = W - _visible_len(cloud_status)
    print(f"  {B5}║{RST}{cloud_status}{' ' * max(pad, 0)}{B5}║{RST}")

    print(f"  {B5}║{RST}{' ' * W}{B5}║{RST}")
    print(f"  {B5}╚{'━' * W}╝{RST}")
    print()


def _visible_len(s):
    """Length of string minus ANSI escape codes."""
    import re
    return len(re.sub(r'\033\[[0-9;]*m', '', s))


def prompt_str():
    """Colored input prompt with mode indicator."""
    mode = brain.get_mode()
    if mode == "companion":
        return f"  {B5}⚡{RST} {BOLD}{B7}>{RST} "
    else:
        return f"  {Y1}⚡{RST} {BOLD}{Y2}>{RST} "


def print_response_header():
    """Print a small header before BOLT's response."""
    print(f"\n  {DIM}{B4}{'─' * 50}{RST}")
    print(f"  {Y1}⚡{RST} {BOLD}{B6}BOLT{RST}")
    print(f"  {DIM}{B4}{'─' * 50}{RST}\n  ", end="")


def print_divider():
    print(f"\n  {DIM}{B4}{'─' * 50}{RST}\n")


def stream_print(chunk):
    """Print a streamed chunk without newline, in blue tint."""
    sys.stdout.write(f"{B7}{chunk}{RST}")
    sys.stdout.flush()


def styled_print(text, color=B7):
    """Print text with color."""
    for line in text.split("\n"):
        print(f"  {color}{line}{RST}")


def handle_command(cmd, session_id):
    """Handle /commands. Returns True if handled."""
    cmd = cmd.strip().lower()

    if cmd == "/help":
        print()
        print(f"  {BOLD}{B6}Commands{RST}")
        print(f"  {DIM}{B4}{'─' * 44}{RST}")
        cmds = [
            ("/companion",   "switch to companion mode (chat/hangout)"),
            ("/code",        "switch to code mode (tools enabled)"),
            ("/build",       "kick off the multi-model build pipeline"),
            ("/buildstatus", "check if a build is in progress"),
            ("/profile",     "see what BOLT knows about you"),
            ("/forget",      "wipe BOLT's memory of you"),
            ("/status",      "session info & current task"),
            ("/timeline",    "BOLT's activity log"),
            ("/memory",      "what BOLT remembers from conversations"),
            ("/task",        "show/manage tasks"),
            ("/tools",       "list available tools"),
            ("/web",         "launch web UI (access from phone)"),
            ("/clear",       "new session (profile persists)"),
            ("/quit",        "save and exit"),
            ("/help",        "show this help"),
        ]
        for name, desc in cmds:
            print(f"  {Y2}{name:16s}{RST} {DIM}{desc}{RST}")
        print()
        return True

    if cmd == "/companion":
        brain.set_mode("companion")
        print(f"\n  {Y1}⚡{RST} {B7}Companion mode — let's just hang.{RST}\n")
        return True

    if cmd == "/code":
        brain.set_mode("code")
        print(f"\n  {Y1}⚡{RST} {Y2}Code mode — tools are live. Let's build.{RST}\n")
        return True

    if cmd == "/profile":
        print(f"\n  {BOLD}{B6}User Profile{RST}")
        print(f"  {DIM}{B4}{'─' * 44}{RST}")
        styled_print(identity.get_profile_display())
        print()
        return True

    if cmd == "/forget":
        identity.clear_profile()
        print(f"\n  {Y1}⚡{RST} {B7}Profile wiped. Fresh start — I'll learn again naturally.{RST}\n")
        return True

    if cmd == "/status":
        print(f"\n  {BOLD}{B6}Status{RST}")
        print(f"  {DIM}{B4}{'─' * 40}{RST}")
        mode = brain.get_mode()
        print(f"  {Y2}Mode:{RST}  {mode}")
        building = "yes" if pipeline.is_pipeline_running() else "no"
        print(f"  {Y2}Build:{RST} {building}")
        styled_print(state.format_status(session_id))
        print()
        return True

    if cmd == "/timeline":
        print(f"\n  {BOLD}{B6}Timeline{RST}")
        print(f"  {DIM}{B4}{'─' * 40}{RST}")
        styled_print(state.format_timeline())
        print()
        return True

    if cmd == "/memory":
        print(f"\n  {BOLD}{B6}Memory{RST}")
        print(f"  {DIM}{B4}{'─' * 40}{RST}")
        styled_print(state.format_memory(session_id))
        print()
        return True

    if cmd == "/task":
        print(f"\n  {BOLD}{B6}Tasks{RST}")
        print(f"  {DIM}{B4}{'─' * 40}{RST}")
        styled_print(state.format_tasks())
        print()
        return True

    if cmd == "/tools":
        print(f"\n  {BOLD}{B6}Tools{RST}")
        print(f"  {DIM}{B4}{'─' * 40}{RST}")
        tl = tools.list_tools()
        for name, desc in tl.items():
            print(f"  {Y2}{name:15s}{RST} {DIM}{desc}{RST}")
        print()
        return True

    if cmd == "/build":
        if pipeline.is_pipeline_running():
            print(f"\n  {Y1}⚡{RST} {B7}A build is already running. Keep chatting — it'll finish in the background.{RST}\n")
            return True
        # Gather recent conversation as context for the spec
        history = memory.get_recent_messages(session_id, limit=30)
        convo_text = ""
        for msg in history:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            convo_text += f"{role}: {content}\n"
        if not convo_text.strip():
            print(f"  {R1}No conversation yet — chat about what you want to build first.{RST}\n")
            return True

        brain.set_mode("build")

        def _on_done(success, output_dir, summary):
            if success:
                memory.save_message(session_id, "assistant", f"Build complete. {summary}")
            brain.set_mode("companion")

        pipeline.run_pipeline(convo_text, callback=_on_done)
        return True

    if cmd == "/buildstatus":
        if pipeline.is_pipeline_running():
            print(f"\n  {Y1}⚡{RST} {B7}Build pipeline is running — status updates print as phases complete.{RST}\n")
        else:
            print(f"\n  {Y1}⚡{RST} {B7}No build running.{RST}\n")
        return True

    if cmd == "/web" or cmd.startswith("/web "):
        parts = cmd.split()
        port = 3000
        if len(parts) > 1:
            try:
                port = int(parts[1])
            except ValueError:
                pass
        print(f"\n  {Y1}⚡{RST} {B7}Starting web UI on port {port}...{RST}\n")
        import web
        web.run_web(port=port)
        return True

    if cmd == "/quit":
        print(f"\n  {DIM}{B7}  Saving session snapshot...{RST}")
        try:
            memory.save_session_snapshot(session_id)
        except Exception:
            pass
        state.log("session_end", session_id)
        print_divider()
        print(f"  {Y1}⚡{RST} {B7}BOLT saved. See ya.{RST}\n")
        sys.exit(0)

    return False


def _ensure_models_warm():
    """Check Ollama and warm router + companion if not loaded."""
    from config import MODELS, OLLAMA_URL
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/ps", timeout=5)
        if resp.status_code != 200:
            return
        loaded = {m["name"] for m in resp.json().get("models", [])}
        for key in ("router", "companion"):
            model = MODELS.get(key)
            if model and model not in loaded:
                print(f"  {DIM}{B7}  Warming {model}...{RST}")
                try:
                    requests.post(
                        f"{OLLAMA_URL}/api/generate",
                        json={"model": model, "prompt": "hi", "keep_alive": "30m"},
                        timeout=120,
                    )
                except Exception:
                    pass
    except Exception:
        pass


def main():
    # ─── --web flag: launch web UI instead of CLI ───
    import argparse
    parser = argparse.ArgumentParser(description="BOLT — Built On Local Terrain")
    parser.add_argument("--web", action="store_true", help="Launch web UI instead of CLI")
    parser.add_argument("--port", type=int, default=3000, help="Web UI port (default: 3000)")
    args = parser.parse_args()

    if args.web:
        import web
        web.run_web(port=args.port)
        return

    # Initialize
    memory.init_db()
    identity.init_profile_tables()

    # Warm models before anything else
    _ensure_models_warm()

    # Session management — reuse last session or create new
    session_id = state.get_state("last_session")
    if not session_id:
        session_id = state.new_session_id()
    state.set_state("last_session", session_id)
    state.log("session_start", session_id)

    banner()

    # Start background workers
    summarizer = SummarizerWorker(session_id)
    summarizer.start()
    task_tracker = TaskTrackerWorker(session_id)
    profile_learner = ProfileLearnerWorker(session_id)
    heartbeat = HeartbeatWorker()
    heartbeat.start()

    try:
        while True:
            try:
                user_input = input(prompt_str()).strip()
            except EOFError:
                break

            if not user_input:
                continue

            # Handle /clear specially — new session but keep profile
            if user_input.lower() == "/clear":
                summarizer.stop()
                # Snapshot the outgoing session
                try:
                    summarizer.force_summarize()
                    memory.save_session_snapshot(session_id)
                except Exception:
                    pass
                session_id = state.new_session_id()
                state.set_state("last_session", session_id)
                state.log("session_start", f"{session_id} (cleared)")
                summarizer = SummarizerWorker(session_id)
                summarizer.start()
                task_tracker = TaskTrackerWorker(session_id)
                profile_learner = ProfileLearnerWorker(session_id)
                print(f"\n  {Y1}⚡{RST} {B7}New session. I still know you though.{RST}\n")
                continue

            # Handle / commands
            if user_input.startswith("/"):
                if handle_command(user_input, session_id):
                    continue
                else:
                    print(f"  {R1}Unknown command:{RST} {user_input}")
                    continue

            # Process through the brain
            print_response_header()
            response = brain.process_message(
                session_id, user_input, stream_callback=stream_print
            )
            print_divider()

            # Background learning — profile + tasks (non-blocking)
            try:
                profile_learner.tick(user_input, response)
            except Exception:
                pass
            try:
                task_tracker.check(user_input, response)
            except Exception:
                pass

    except KeyboardInterrupt:
        pass
    finally:
        summarizer.stop()
        heartbeat.stop()
        print(f"\n\n  {DIM}{B7}  Saving session snapshot...{RST}")
        try:
            summarizer.force_summarize()
            memory.save_session_snapshot(session_id)
        except Exception:
            pass
        state.log("session_end", session_id)
        print(f"  {Y1}⚡{RST} {B7}BOLT saved. See ya.{RST}\n")


if __name__ == "__main__":
    main()
