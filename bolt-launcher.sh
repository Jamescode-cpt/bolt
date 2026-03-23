#!/usr/bin/env bash
# BOLT Desktop Launcher — starts BOLT web UI and opens the browser.
# Cross-platform: Linux + macOS. Used by .desktop file or app shortcut.
set -u

# Default BOLT_DIR to wherever this script lives
BOLT_DIR="${BOLT_DIR:-$(cd "$(dirname "$0")" && pwd)}"
PIDFILE="$HOME/.bolt.pid"
DEFAULT_PORT=3080

# ─── Platform detection ───
IS_MAC=false
[[ "$(uname)" == "Darwin" ]] && IS_MAC=true

# ─── Helpers ───

notify() {
    if $IS_MAC; then
        osascript -e "display notification \"$1\" with title \"BOLT\"" 2>/dev/null || true
    else
        notify-send "BOLT" "$1" 2>/dev/null || true
    fi
}

is_port_free() {
    if command -v ss &>/dev/null; then
        ! ss -tlnp 2>/dev/null | grep -q ":$1 " 2>/dev/null
    elif command -v lsof &>/dev/null; then
        ! lsof -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | grep -q LISTEN
    else
        # Can't check — assume free
        return 0
    fi
}

find_free_port() {
    local port=$DEFAULT_PORT
    while ! is_port_free "$port"; do
        port=$((port + 1))
        if [ "$port" -gt 3100 ]; then
            echo "$DEFAULT_PORT"
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
    if $IS_MAC; then
        open "$url" 2>/dev/null
        return 0
    fi
    # Linux: try named browsers for a new window, then xdg-open
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
    xdg-open "$url" 2>/dev/null || true
}

# ─── Check if BOLT is already running ───

if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE" 2>/dev/null || true)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
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

# ─── Ensure Ollama is running (skip if using MLX-only) ───

if ! curl -sf http://localhost:11434/api/tags &>/dev/null; then
    if command -v ollama &>/dev/null; then
        if $IS_MAC; then
            # macOS: ollama may be an app, try opening it
            open -a Ollama 2>/dev/null || nohup ollama serve &>/dev/null &
        else
            nohup ollama serve &>/dev/null &
        fi
        tries=0
        while ! curl -sf http://localhost:11434/api/tags &>/dev/null; do
            sleep 1
            tries=$((tries + 1))
            if [ $tries -ge 15 ]; then
                # Not fatal if MLX is available
                notify "Ollama not responding. BOLT will try MLX or local fallback."
                break
            fi
        done
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
    sleep 1
    if [ -f "$URL_FILE" ]; then
        BOLT_URL=$(tr -d '[:space:]' < "$URL_FILE")
    else
        BOLT_URL="http://localhost:$PORT"
    fi
    open_browser "$BOLT_URL"
else
    notify "BOLT took too long to start. Check ~/.bolt.log"
fi
