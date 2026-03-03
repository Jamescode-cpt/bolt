#!/usr/bin/env bash
# BOLT Desktop Launcher — starts BOLT web UI and opens the browser.
# Used by the .desktop file so Joe Soap just clicks an icon.
set -euo pipefail

BOLT_DIR="${BOLT_DIR:-$HOME/bolt}"
PIDFILE="$HOME/.bolt.pid"
DEFAULT_PORT=3000

# ─── Helpers ───

notify() {
    # Desktop notification (silent fail if not available)
    notify-send "BOLT" "$1" 2>/dev/null || true
}

is_port_free() {
    ! ss -tlnp 2>/dev/null | grep -q ":$1 " 2>/dev/null
}

find_free_port() {
    local port=$DEFAULT_PORT
    while ! is_port_free "$port"; do
        port=$((port + 1))
        if [ "$port" -gt 3100 ]; then
            echo "$DEFAULT_PORT"  # give up, let Flask handle the error
            return
        fi
    done
    echo "$port"
}

wait_for_server() {
    local url="$1"
    local tries=0
    while [ $tries -lt 30 ]; do
        if curl -sf -o /dev/null "$url" 2>/dev/null; then
            return 0
        fi
        sleep 1
        tries=$((tries + 1))
    done
    return 1
}

# ─── Check if BOLT is already running ───

if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE" 2>/dev/null || true)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        # BOLT is already running — find its port and open browser
        PORT=$(ss -tlnp 2>/dev/null | grep "pid=$OLD_PID" | grep -oP ':\K\d+' | head -1 || echo "$DEFAULT_PORT")
        [ -z "$PORT" ] && PORT=$DEFAULT_PORT
        xdg-open "http://localhost:$PORT" 2>/dev/null || true
        exit 0
    fi
    rm -f "$PIDFILE"
fi

# ─── Ensure Ollama is running ───

if ! curl -sf http://localhost:11434/api/tags &>/dev/null; then
    if command -v ollama &>/dev/null; then
        nohup ollama serve &>/dev/null &
        # Wait for Ollama
        tries=0
        while ! curl -sf http://localhost:11434/api/tags &>/dev/null; do
            sleep 1
            tries=$((tries + 1))
            if [ $tries -ge 15 ]; then
                notify "Could not start Ollama. Please start it manually."
                exit 1
            fi
        done
    else
        notify "Ollama not found. Please install it first."
        exit 1
    fi
fi

# ─── Find a free port ───

PORT=$(find_free_port)

# ─── Launch BOLT ───

cd "$BOLT_DIR"
nohup python3 bolt.py --gui --port "$PORT" > "$HOME/.bolt.log" 2>&1 &
BOLT_PID=$!
echo "$BOLT_PID" > "$PIDFILE"

# ─── Wait for server, then open browser ───

if wait_for_server "http://localhost:$PORT"; then
    xdg-open "http://localhost:$PORT" 2>/dev/null || true
else
    notify "BOLT took too long to start. Check ~/.bolt.log"
fi
