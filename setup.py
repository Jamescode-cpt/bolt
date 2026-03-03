#!/usr/bin/env python3
"""BOLT first-run setup — hardware detection, model pulling, config generation."""

import os
import sys
import json
import time
import subprocess

# Ensure bolt dir is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env

# ─── ANSI colors ───
RST  = "\033[0m"
BOLD = "\033[1m"
DIM  = "\033[2m"
B5   = "\033[38;5;33m"
B6   = "\033[38;5;39m"
B7   = "\033[38;5;75m"
Y1   = "\033[38;5;220m"
Y2   = "\033[38;5;226m"
R1   = "\033[38;5;196m"
G1   = "\033[38;5;82m"


def _print(msg, color=B7):
    print(f"  {color}{msg}{RST}")


def _header(msg):
    print(f"\n  {Y1}⚡{RST} {BOLD}{B6}{msg}{RST}")
    print(f"  {DIM}{B5}{'─' * 50}{RST}")


def _ok(msg):
    print(f"  {G1}  ✓ {msg}{RST}")


def _err(msg):
    print(f"  {R1}  ✗ {msg}{RST}")


def _status(msg):
    print(f"  {DIM}{B7}  → {msg}{RST}")
    sys.stdout.flush()


def print_banner():
    """Print the BOLT setup banner."""
    print()
    print(f"  {B5}╔{'━' * 54}╗{RST}")
    print(f"  {B5}║{RST}{' ' * 54}{B5}║{RST}")
    title = f"    {BOLD}{B6}B {B7}O {Y2}L {R1}T{RST}   {DIM}{B7}— First Run Setup{RST}"
    # Rough padding
    print(f"  {B5}║{RST}{title}{' ' * 10}{B5}║{RST}")
    print(f"  {B5}║{RST}{' ' * 54}{B5}║{RST}")
    print(f"  {B5}╚{'━' * 54}╝{RST}")
    print()


def detect_hardware():
    """Detect and display hardware info."""
    _header("Hardware Detection")

    ram = env.RAM_GB
    cores = env.CPU_CORES
    gpu = env.GPU

    _ok(f"RAM: {ram} GB")
    _ok(f"CPU: {cores} cores")

    if gpu:
        gpu_str = gpu["name"]
        if gpu["vram_gb"] > 0:
            gpu_str += f" ({gpu['vram_gb']}GB VRAM)"
        _ok(f"GPU: {gpu_str}")
    else:
        _print("GPU: Not detected (CPU inference)")

    return ram, cores, gpu


def select_tier(ram):
    """Select model tier based on RAM, with user override."""
    _header("Model Tier Selection")

    tier = env.select_model_tier()
    models = env.get_tier_models(tier)

    tier_desc = {
        "minimal":  f"Minimal  — 2 models  (router + 3b companion)    [needs ~4GB]",
        "standard": f"Standard — 4 models  (+ 7b companion, coders)   [needs ~10GB]",
        "full":     f"Full     — 5 models  (+ 14b coder)              [needs ~18GB]",
        "beast":    f"Beast    — 6 models  (+ 32b coder)              [needs ~28GB]",
    }

    _print(f"Based on {ram}GB RAM, recommended tier: {BOLD}{Y2}{tier}{RST}")
    print()

    for t, desc in tier_desc.items():
        marker = f"{Y1}→{RST}" if t == tier else " "
        print(f"  {marker} {desc}")

    print()
    choice = input(f"  {B7}Use '{tier}'? [Y/n/tier name]: {RST}").strip().lower()

    if choice and choice != "y" and choice != "yes":
        if choice in env.MODEL_TIERS:
            tier = choice
            models = env.get_tier_models(tier)
            _ok(f"Switched to {tier} tier")
        else:
            _print(f"Unknown tier '{choice}', using {tier}")

    _ok(f"Selected tier: {tier} ({len(models)} models)")

    print()
    _print("Models to install:")
    for key, model in models.items():
        _print(f"  {key:15s} → {model}")

    return tier, models


def check_ollama():
    """Verify Ollama is installed and running."""
    _header("Ollama Check")

    # Check if ollama binary exists
    try:
        result = subprocess.run(["ollama", "--version"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            version = result.stdout.strip() or result.stderr.strip()
            _ok(f"Ollama installed: {version}")
        else:
            _err("Ollama found but returned an error")
            return False
    except FileNotFoundError:
        _err("Ollama not found!")
        _print("Install Ollama: curl -fsSL https://ollama.com/install.sh | sh")
        return False
    except Exception as e:
        _err(f"Error checking Ollama: {e}")
        return False

    # Check if Ollama is running
    try:
        import requests
        resp = requests.get(f"{env.OLLAMA_URL}/api/tags", timeout=5)
        if resp.status_code == 200:
            _ok(f"Ollama running at {env.OLLAMA_URL}")
            return True
    except Exception:
        pass

    _print("Ollama is installed but not running. Trying to start it...")
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait for it to start
        for _ in range(10):
            time.sleep(1)
            try:
                import requests
                resp = requests.get(f"{env.OLLAMA_URL}/api/tags", timeout=3)
                if resp.status_code == 200:
                    _ok("Ollama started successfully")
                    return True
            except Exception:
                pass
        _err("Could not start Ollama. Start it manually: ollama serve")
        return False
    except Exception as e:
        _err(f"Failed to start Ollama: {e}")
        return False


def pull_models(models):
    """Pull all required models via Ollama."""
    _header("Pulling Models")
    _print("This may take a while on first run...")
    print()

    for key, model in models.items():
        _status(f"Pulling {model} ({key})...")
        try:
            result = subprocess.run(
                ["ollama", "pull", model],
                capture_output=False,
                timeout=1800,  # 30 min max per model
            )
            if result.returncode == 0:
                _ok(f"{model} ready")
            else:
                _err(f"Failed to pull {model}")
        except subprocess.TimeoutExpired:
            _err(f"Timeout pulling {model} — try manually: ollama pull {model}")
        except Exception as e:
            _err(f"Error pulling {model}: {e}")


def generate_certs():
    """Generate self-signed SSL certs for web UI."""
    _header("SSL Certificates")

    cert_file = env.CERT_FILE
    key_file = env.KEY_FILE

    if os.path.exists(cert_file) and os.path.exists(key_file):
        _ok("SSL certs already exist")
        return

    try:
        result = subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", key_file,
            "-out", cert_file,
            "-days", "365", "-nodes",
            "-subj", "/CN=bolt.local",
        ], capture_output=True, text=True, timeout=30)

        if result.returncode == 0 and os.path.exists(cert_file):
            os.chmod(key_file, 0o600)
            _ok("SSL certs generated (valid for 1 year)")
        else:
            _err("Could not generate SSL certs")
            _print("Web UI will work without HTTPS, but mic won't work over network")
    except FileNotFoundError:
        _err("openssl not found — skipping cert generation")
        _print("Install openssl to enable HTTPS for web UI")
    except Exception as e:
        _err(f"Cert generation error: {e}")


def ask_advanced_tools():
    """Ask whether to enable advanced/sharp tools."""
    _header("Tool Safety")
    _print("BOLT ships with 50+ tools. Some are powerful:")
    _print(f"  shell, python exec, SSH, Docker, port scanning,")
    _print(f"  encryption, process management, cron, packages")
    print()
    _print("Safe mode:     File I/O, search, web, notes, weather, etc.")
    _print("Advanced mode:  Everything — full system access")
    print()
    choice = input(f"  {B7}Enable advanced tools? [y/N]: {RST}").strip().lower()
    enabled = choice in ("y", "yes")

    if enabled:
        _ok("Advanced tools enabled — full power unlocked")
    else:
        _ok("Safe mode — you can enable advanced tools later in data/bolt_config.json")

    return enabled


def ask_name():
    """Optionally ask the user's name."""
    _header("Who Are You?")
    _print("BOLT learns about you over time, but we can start with your name.")
    print()
    name = input(f"  {B7}Your name (or press Enter to skip): {RST}").strip()

    if name:
        # Save to profile DB
        try:
            import memory
            import identity
            memory.init_db()
            identity.init_profile_tables()
            identity.save_fact("name", "name", name, confidence=1.0, source="setup")
            _ok(f"Nice to meet you, {name}!")
        except Exception:
            _ok(f"Got it, {name}! (Will save to profile on first chat)")
    else:
        _print("No worries — BOLT will learn your name naturally.")

    return name


def write_config(tier, models, name=None, advanced_tools=False):
    """Write the bolt_config.json file."""
    _header("Saving Configuration")

    os.makedirs(env.DATA_DIR, exist_ok=True)

    config = {
        "tier": tier,
        "models": models,
        "ram_gb": env.RAM_GB,
        "cpu_cores": env.CPU_CORES,
        "advanced_tools": advanced_tools,
        "setup_complete": True,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if name:
        config["user_name"] = name

    with open(env.CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)

    _ok(f"Config saved to {env.CONFIG_PATH}")


def print_success():
    """Print the success banner."""
    print()
    print(f"  {Y1}{'━' * 54}{RST}")
    print(f"  {Y1}⚡{RST} {BOLD}{G1}BOLT is ready!{RST}")
    print(f"  {Y1}{'━' * 54}{RST}")
    print()
    _print("Start chatting:")
    _print(f"  CLI:  python3 bolt.py")
    _print(f"  Web:  python3 bolt.py --web")
    print()
    _print("Commands: /help  |  Modes: /companion  /code  /build")
    print()


def run_setup():
    """Run the full first-run setup flow."""
    print_banner()

    # 1. Detect hardware
    ram, cores, gpu = detect_hardware()

    # 2. Check Ollama
    ollama_ok = check_ollama()
    if not ollama_ok:
        _print("")
        _print("BOLT needs Ollama to run. Install it and try again.")
        _print("  curl -fsSL https://ollama.com/install.sh | sh")
        print()
        choice = input(f"  {B7}Continue setup without Ollama? [y/N]: {RST}").strip().lower()
        if choice not in ("y", "yes"):
            sys.exit(1)

    # 3. Select tier
    tier, models = select_tier(ram)

    # 4. Pull models
    if ollama_ok:
        print()
        choice = input(f"  {B7}Pull models now? [Y/n]: {RST}").strip().lower()
        if choice in ("", "y", "yes"):
            pull_models(models)
        else:
            _print("Skipping model pull. Run 'ollama pull <model>' later.")

    # 5. Generate SSL certs
    generate_certs()

    # 6. Advanced tools prompt
    adv = ask_advanced_tools()

    # 7. Ask name
    name = ask_name()

    # 8. Write config
    write_config(tier, models, name, advanced_tools=adv)

    # 9. Done
    print_success()


if __name__ == "__main__":
    run_setup()
