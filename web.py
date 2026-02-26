"""BOLT Web Frontend — Flask app with SSE streaming for phone-accessible chat UI."""

import sys
import os
import json
import threading
import queue
import time
import subprocess
import secrets
import hmac

# Ensure bolt/ is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, render_template, request, Response, jsonify

import memory
import state
import brain
import identity
import pipeline
import tools
from identity import ProfileLearnerWorker
from workers import SummarizerWorker, TaskTrackerWorker

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max request


@app.after_request
def _security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "default-src 'self' 'unsafe-inline'; connect-src 'self'"
    return response

# ─── Concurrency ───
_chat_lock = threading.Lock()
_initialized = False
_init_lock = threading.Lock()

# ─── Auth token ───
_auth_token = None

# Session & workers (initialized once)
_session_id = None
_summarizer = None
_task_tracker = None
_profile_learner = None


def _check_auth():
    """Check if request has valid auth token. Returns error response or None."""
    token = request.args.get("token") or request.headers.get("X-Bolt-Token")
    if token and hmac.compare_digest(token, _auth_token):
        return None
    return jsonify({"error": "Unauthorized — add ?token=YOUR_TOKEN to the URL"}), 401


def _ensure_initialized():
    """One-time initialization — same lifecycle as bolt.py:main() but for web context."""
    global _initialized, _session_id, _summarizer, _task_tracker, _profile_learner

    with _init_lock:
        if _initialized:
            return
        global _auth_token
        _auth_token = secrets.token_urlsafe(16)
        memory.init_db()
        identity.init_profile_tables()

        _session_id = state.get_state("last_session")
        if not _session_id:
            _session_id = state.new_session_id()
        state.set_state("last_session", _session_id)
        state.log("session_start", f"{_session_id} (web)")

        # Web defaults to code mode — so BOLT can actually execute tools
        # (companion mode has no tool instructions, just chat)
        brain.set_mode("code")

        _summarizer = SummarizerWorker(_session_id)
        _summarizer.start()
        _task_tracker = TaskTrackerWorker(_session_id)
        _profile_learner = ProfileLearnerWorker(_session_id)
        _initialized = True


# ─── Routes ───

@app.route("/")
def index():
    """Serve the chat UI."""
    _ensure_initialized()
    auth_err = _check_auth()
    if auth_err:
        return auth_err
    return render_template("index.html", token=_auth_token)


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """Send a message, get SSE stream back."""
    _ensure_initialized()
    auth_err = _check_auth()
    if auth_err:
        return auth_err
    data = request.get_json(silent=True) or {}
    msg = (data.get("message") or "").strip()
    if not msg:
        return jsonify({"error": "empty message"}), 400

    # Acquire lock non-blocking — reject if model already busy
    if not _chat_lock.acquire(blocking=False):
        return jsonify({"error": "Model is busy, try again in a moment"}), 429

    q = queue.Queue()

    def _stream_worker():
        global _session_id
        try:
            def stream_cb(chunk):
                q.put(("chunk", chunk))

            response = brain.process_message(_session_id, msg, stream_callback=stream_cb)

            # Background learning (non-blocking)
            try:
                _profile_learner.tick(msg, response)
            except Exception:
                pass
            try:
                _task_tracker.check(msg, response)
            except Exception:
                pass

            q.put(("done", response))
        except Exception as e:
            q.put(("error", str(e)))
        finally:
            _chat_lock.release()

    t = threading.Thread(target=_stream_worker, daemon=True)
    t.start()

    def generate():
        while True:
            try:
                kind, data = q.get(timeout=300)
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'error', 'content': 'Timeout'})}\n\n"
                break

            if kind == "chunk":
                yield f"data: {json.dumps({'type': 'chunk', 'content': data})}\n\n"
            elif kind == "done":
                yield f"data: {json.dumps({'type': 'done', 'content': data})}\n\n"
                break
            elif kind == "error":
                yield f"data: {json.dumps({'type': 'error', 'content': data})}\n\n"
                break

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ─── Whisper transcription ───
_whisper_model = None
_whisper_lock = threading.Lock()


def _get_whisper():
    """Lazy-load whisper model on first use."""
    global _whisper_model
    if _whisper_model is None:
        with _whisper_lock:
            if _whisper_model is None:
                from faster_whisper import WhisperModel
                _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
    return _whisper_model


@app.route("/api/transcribe", methods=["POST"])
def api_transcribe():
    """Receive audio from the browser mic, transcribe with whisper."""
    _ensure_initialized()
    auth_err = _check_auth()
    if auth_err:
        return auth_err
    if "audio" not in request.files:
        return jsonify({"error": "no audio file"}), 400

    audio_file = request.files["audio"]

    # Save to temp file (whisper needs a file path)
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".webm", delete=False)
    try:
        audio_file.save(tmp.name)
        tmp.close()

        model = _get_whisper()
        segments, _ = model.transcribe(tmp.name, language="en")
        text = " ".join(seg.text.strip() for seg in segments).strip()

        return jsonify({"text": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


@app.route("/api/messages", methods=["GET"])
def api_messages():
    """Chat history for page reload."""
    _ensure_initialized()
    auth_err = _check_auth()
    if auth_err:
        return auth_err
    limit = request.args.get("limit", 50, type=int)
    rows = memory.get_recent_messages(_session_id, limit=limit)
    messages = []
    for r in rows:
        role = r["role"]
        if role in ("tool", "tool_result"):
            continue  # Skip tool internals in the UI
        messages.append({"role": role, "content": r["content"]})
    return jsonify(messages)


@app.route("/api/status", methods=["GET"])
def api_status():
    """Mode, build status, session info."""
    _ensure_initialized()
    auth_err = _check_auth()
    if auth_err:
        return auth_err
    mode = brain.get_mode()
    building = pipeline.is_pipeline_running()
    task = memory.get_active_task()
    return jsonify({
        "mode": mode,
        "building": building,
        "session_id": _session_id,
        "task": task["title"] if task else None,
    })


@app.route("/api/command", methods=["POST"])
def api_command():
    """Execute slash commands."""
    _ensure_initialized()
    auth_err = _check_auth()
    if auth_err:
        return auth_err
    global _session_id, _summarizer, _task_tracker, _profile_learner

    data = request.get_json(silent=True) or {}
    cmd = (data.get("command") or "").strip().lower()
    if not cmd.startswith("/"):
        cmd = "/" + cmd

    result = {"ok": True, "message": ""}

    if cmd == "/companion":
        brain.set_mode("companion")
        result["message"] = "Companion mode — let's just hang."

    elif cmd == "/code":
        brain.set_mode("code")
        result["message"] = "Code mode — tools are live. Let's build."

    elif cmd == "/profile":
        result["message"] = identity.get_profile_display()

    elif cmd == "/forget":
        identity.clear_profile()
        result["message"] = "Profile wiped. Fresh start — I'll learn again naturally."

    elif cmd == "/status":
        result["message"] = state.format_status(_session_id)

    elif cmd == "/timeline":
        result["message"] = state.format_timeline()

    elif cmd == "/memory":
        result["message"] = state.format_memory(_session_id)

    elif cmd == "/task":
        result["message"] = state.format_tasks()

    elif cmd == "/tools":
        tl = tools.list_tools()
        lines = [f"{name:15s}  {desc}" for name, desc in tl.items()]
        result["message"] = "\n".join(lines) if lines else "No tools loaded."

    elif cmd == "/build":
        if pipeline.is_pipeline_running():
            result["message"] = "A build is already running. Keep chatting — it'll finish in the background."
        else:
            history = memory.get_recent_messages(_session_id, limit=30)
            convo_text = ""
            for msg_row in history:
                role = msg_row.get("role", "?") if isinstance(msg_row, dict) else msg_row["role"]
                content = msg_row.get("content", "") if isinstance(msg_row, dict) else msg_row["content"]
                convo_text += f"{role}: {content}\n"
            if not convo_text.strip():
                result["message"] = "No conversation yet — chat about what you want to build first."
            else:
                brain.set_mode("build")

                def _on_done(success, output_dir, summary):
                    if success:
                        memory.save_message(_session_id, "assistant", f"Build complete. {summary}")
                    brain.set_mode("companion")

                pipeline.run_pipeline(convo_text, callback=_on_done)
                result["message"] = "Build pipeline launched! Keep chatting — it runs in the background."

    elif cmd == "/buildstatus":
        if pipeline.is_pipeline_running():
            result["message"] = "Build pipeline is running."
        else:
            result["message"] = "No build running."

    elif cmd == "/clear":
        _summarizer.stop()
        _session_id = state.new_session_id()
        state.set_state("last_session", _session_id)
        state.log("session_start", f"{_session_id} (web, cleared)")
        _summarizer = SummarizerWorker(_session_id)
        _summarizer.start()
        _task_tracker = TaskTrackerWorker(_session_id)
        _profile_learner = ProfileLearnerWorker(_session_id)
        result["message"] = "New session. I still know you though."

    elif cmd == "/help":
        cmds = [
            "/companion   — switch to companion mode (chat/hangout)",
            "/code        — switch to code mode (tools enabled)",
            "/build       — kick off the multi-model build pipeline",
            "/buildstatus — check if a build is in progress",
            "/profile     — see what BOLT knows about you",
            "/forget      — wipe BOLT's memory of you",
            "/status      — session info & current task",
            "/timeline    — BOLT's activity log",
            "/memory      — what BOLT remembers from conversations",
            "/task        — show/manage tasks",
            "/tools       — list available tools",
            "/clear       — new session (profile persists)",
        ]
        result["message"] = "\n".join(cmds)

    else:
        result["ok"] = False
        result["message"] = f"Unknown command: {cmd}"

    return jsonify(result)


# ─── Startup ───

def _get_local_ips():
    """Get all local IPs for the startup banner."""
    ips = []
    try:
        import socket
        hostname = socket.gethostname()
        # Get all addresses
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and ip != "127.0.0.1":
                ips.append(ip)
    except Exception:
        pass
    # Fallback: parse ip addr
    if not ips:
        try:
            out = subprocess.check_output(["ip", "-4", "addr", "show"], text=True, timeout=5)
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("inet ") and "127.0.0.1" not in line:
                    ip = line.split()[1].split("/")[0]
                    if ip not in ips:
                        ips.append(ip)
        except Exception:
            pass
    return ips


def _get_tailscale_ip():
    """Try to get Tailscale IP if available."""
    try:
        out = subprocess.check_output(
            ["tailscale", "ip", "-4"], text=True, timeout=5
        ).strip()
        if out:
            return out.splitlines()[0]
    except Exception:
        pass
    return None


def run_web(port=3000):
    """Launch the web server with a nice banner."""
    _ensure_initialized()

    ips = _get_local_ips()
    ts_ip = _get_tailscale_ip()

    # SSL cert for HTTPS (required for mic access from phone)
    cert_dir = os.path.dirname(os.path.abspath(__file__))
    cert_file = os.path.join(cert_dir, "bolt-cert.pem")
    key_file = os.path.join(cert_dir, "bolt-key.pem")
    has_ssl = os.path.exists(cert_file) and os.path.exists(key_file)
    scheme = "https" if has_ssl else "http"

    print()
    print("  \033[38;5;33m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m")
    print("  \033[38;5;220m⚡\033[0m \033[1m\033[38;5;39mBOLT Web UI\033[0m")
    print("  \033[38;5;33m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m")
    print()
    print(f"  \033[38;5;75mLocal:\033[0m      {scheme}://localhost:{port}?token={_auth_token}")
    for ip in ips:
        print(f"  \033[38;5;75mNetwork:\033[0m    {scheme}://{ip}:{port}?token={_auth_token}")
    if ts_ip:
        print(f"  \033[38;5;82mTailscale:\033[0m  {scheme}://{ts_ip}:{port}?token={_auth_token}")
    if has_ssl:
        print(f"  \033[38;5;82mHTTPS:\033[0m      ON (mic + voice enabled)")
    print()
    print(f"  \033[2m\033[38;5;75mMode: {brain.get_mode()} | Session: {_session_id}\033[0m")
    print(f"  \033[2m\033[38;5;75mOpen the URL above on your phone to chat with BOLT\033[0m")
    print(f"  \033[38;5;214mToken:\033[0m      {_auth_token}")
    print()
    print("  \033[38;5;33m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m")
    print()

    state.log("web_start", f"port={port}, ssl={has_ssl}")

    ssl_ctx = None
    if has_ssl:
        import ssl
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.load_cert_chain(cert_file, key_file)

    app.run(host="127.0.0.1", port=port, threaded=True, debug=False, ssl_context=ssl_ctx)
