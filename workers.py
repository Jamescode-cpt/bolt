"""Background workers — summarizer, task tracker, model heartbeat."""

import threading
import time
import json
import memory
import state
from config import MODELS, OLLAMA_URL, SUMMARY_INTERVAL, SUMMARIZER_PROMPT, TASK_DETECT_PROMPT
import requests

HEARTBEAT_INTERVAL = 270  # 4.5 minutes — Ollama default keep_alive is 5m


def _quick_generate(prompt):
    """Quick non-streaming generation using the router model."""
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": MODELS["router"],
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")
    except Exception as e:
        state.log("worker_error", str(e))
        return ""


class SummarizerWorker(threading.Thread):
    """Watches message count and auto-summarizes when threshold is reached."""

    def __init__(self, session_id):
        super().__init__(daemon=True)
        self.session_id = session_id
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        while not self._stop_event.is_set():
            try:
                count = memory.count_unsummarized(self.session_id)
                if count >= SUMMARY_INTERVAL:
                    self._summarize()
            except Exception as e:
                state.log("summarizer_error", str(e))
            self._stop_event.wait(15)  # Check every 15 seconds

    def _summarize(self):
        msgs = memory.get_unsummarized_messages(self.session_id)
        if not msgs:
            return

        # Build conversation text
        convo_parts = []
        for m in msgs:
            convo_parts.append(f"{m['role']}: {m['content']}")
        conversation = "\n".join(convo_parts)

        # Truncate if too long
        if len(conversation) > 6000:
            conversation = conversation[:6000] + "\n... (truncated)"

        prompt = SUMMARIZER_PROMPT.format(conversation=conversation)
        summary = _quick_generate(prompt)

        if summary.strip():
            last_id = msgs[-1]["id"]
            memory.save_summary(self.session_id, summary.strip(), last_id)
            state.log("summarized", f"covered through message #{last_id}")

    def force_summarize(self):
        """Trigger a summary check immediately (called from main thread)."""
        try:
            self._summarize()
        except Exception:
            pass


class TaskTrackerWorker:
    """Detects tasks from conversation exchanges. Called synchronously after each exchange."""

    def __init__(self, session_id):
        self.session_id = session_id

    def check(self, user_msg, assistant_msg):
        """Analyze the latest exchange for task information."""
        try:
            prompt = TASK_DETECT_PROMPT.format(
                user_msg=user_msg[:500],
                assistant_msg=assistant_msg[:500],
            )
            result = _quick_generate(prompt)
            self._parse_task_result(result)
        except Exception as e:
            state.log("task_tracker_error", str(e))

    def _parse_task_result(self, result):
        task_line = ""
        status_line = ""
        for line in result.strip().split("\n"):
            line = line.strip()
            if line.upper().startswith("TASK:"):
                task_line = line[5:].strip()
            elif line.upper().startswith("STATUS:"):
                status_line = line[7:].strip().lower()

        if not task_line or task_line.upper() == "NONE":
            return

        if status_line == "done":
            memory.complete_active_task()
            state.log("task_done", task_line)
        elif status_line == "active":
            memory.upsert_task(task_line, "active")
            state.log("task_detected", task_line)


class HeartbeatWorker(threading.Thread):
    """Keeps core models warm in Ollama while BOLT is running.

    On full/beast tiers (16GB+), router + companion (7b) + worker_heavy (14b)
    all stay hot together (~13.5GB). The 1.5b router is ALWAYS hot — it handles
    classification so the user never waits. Only when the 32b beast is needed
    do the 7b and 14b unload (pipeline handles that), then reload after.

    On standard tier (8-12GB), only router + companion stay hot.
    """

    def __init__(self):
        super().__init__(daemon=True)
        self._stop_event = threading.Event()
        # Determine which models to keep hot based on available RAM
        self._hot_keys = ["router", "companion"]
        try:
            import env
            if env.RAM_GB >= 16 and MODELS.get("worker_heavy"):
                self._hot_keys.append("worker_heavy")
        except Exception:
            pass

    def stop(self):
        self._stop_event.set()

    def run(self):
        while not self._stop_event.is_set():
            self._pulse()
            self._stop_event.wait(HEARTBEAT_INTERVAL)

    def _pulse(self):
        """Send a keep_alive ping to each core model."""
        for key in self._hot_keys:
            model = MODELS.get(key)
            if not model:
                continue
            try:
                requests.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={"model": model, "prompt": "", "keep_alive": "10m"},
                    timeout=15,
                )
            except Exception:
                pass
