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
        # BOLT is already running — open browser with saved URL
        if [ -f "$HOME/.bolt-url" ]; then
            xdg-open "$(cat "$HOME/.bolt-url")" 2>/dev/null || true
        else
            xdg-open "http://localhost:$DEFAULT_PORT" 2>/dev/null || true
        fi
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

# ─── Wait for server, then open browser with auth token ───

URL_FILE="$HOME/.bolt-url"

if wait_for_server "http://localhost:$PORT"; then
    # Read the full URL with token from the file the server writes
    if [ -f "$URL_FILE" ]; then
        BOLT_URL=$(cat "$URL_FILE")
    else
        BOLT_URL="http://localhost:$PORT"
    fi
    xdg-open "$BOLT_URL" 2>/dev/null || true
else
    notify "BOLT took too long to start. Check ~/.bolt.log"
fi
