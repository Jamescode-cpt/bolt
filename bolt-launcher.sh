#!/usr/bin/env bash
# BOLT Desktop Launcher — starts BOLT web UI and opens the browser.
# Used by the .desktop file so Joe Soap just clicks an icon.
set -u

# Default BOLT_DIR to wherever this script lives (set by the installer)
BOLT_DIR="${BOLT_DIR:-$(cd "$(dirname "$0")" && pwd)}"
PIDFILE="$HOME/.bolt.pid"
DEFAULT_PORT=3080

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

open_browser() {
    local url="$1"
    # Force a NEW visible window — xdg-open often just opens a background tab
    if command -v firefox &>/dev/null; then
        nohup firefox --new-window "$url" &>/dev/null &
        return 0
    elif command -v google-chrome &>/dev/null; then
        nohup google-chrome --new-window "$url" &>/dev/null &
        return 0
    elif command -v chromium-browser &>/dev/null; then
        nohup chromium-browser --new-window "$url" &>/dev/null &
        return 0
    elif command -v chromium &>/dev/null; then
        nohup chromium --new-window "$url" &>/dev/null &
        return 0
    fi
    # Fallback
    xdg-open "$url" 2>/dev/null || true
}

# ─── Check if BOLT is already running ───

if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE" 2>/dev/null || true)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        # BOLT is already running — open browser with saved URL
        if [ -f "$HOME/.bolt-url" ]; then
            BOLT_URL=$(tr -d '[:space:]' < "$HOME/.bolt-url")
        else
            BOLT_URL="http://localhost:$DEFAULT_PORT"
        fi
        open_browser "$BOLT_URL"
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

if wait_for_server "http://localhost:$PORT/api/health"; then
    # Give server a moment to write the URL file
    sleep 1
    # Read the full URL with token from the file the server writes
    if [ -f "$URL_FILE" ]; then
        BOLT_URL=$(tr -d '[:space:]' < "$URL_FILE")
    else
        BOLT_URL="http://localhost:$PORT"
    fi
    open_browser "$BOLT_URL"
else
    notify "BOLT took too long to start. Check ~/.bolt.log"
fi
