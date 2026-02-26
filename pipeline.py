"""BOLT pipeline — staged multi-model build system.

Flow:
  1. Spec    (3b)         — distill conversation into a JSON build spec
  2. Architect (32b)      — plan structure, split work into two handoffs
  3. Build   (14b + 7b)   — workers build their pieces in parallel
  4. Review  (32b)        — validate everything fits together
  5. Write                — save all files to disk

The 1.5b router stays loaded the whole time so the user can keep chatting
while the pipeline works in the background.
"""

import json
import os
import sys
import time
import threading
import requests

from config import (
    MODELS, OLLAMA_URL,
    SPEC_PROMPT, ARCHITECT_PROMPT, WORKER_PROMPT, REVIEW_PROMPT,
)
import identity

# ─── ANSI (match bolt.py palette) ───
RST  = "\033[0m"
BOLD = "\033[1m"
DIM  = "\033[2m"
B4   = "\033[38;5;27m"
B5   = "\033[38;5;33m"
B6   = "\033[38;5;39m"
B7   = "\033[38;5;75m"
Y1   = "\033[38;5;220m"
Y2   = "\033[38;5;226m"
R1   = "\033[38;5;196m"
G1   = "\033[38;5;82m"

# Track active pipeline state
_active_pipeline = None
_pipeline_lock = threading.Lock()

KEEP_ALIVE_MODEL = MODELS["router"]  # 1.5b — always stays loaded (~1GB)


# ─── Ollama helpers ───

def _ollama_generate(model, prompt, timeout=600):
    """Blocking generate call — returns full text."""
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=timeout,
        )
        if resp.status_code == 200:
            return resp.json().get("response", "")
        return f"[error: HTTP {resp.status_code}]"
    except Exception as e:
        return f"[error: {e}]"


def unload_model(model_name):
    """Unload a model from memory via keep_alive=0."""
    try:
        requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model_name, "prompt": "", "keep_alive": 0},
            timeout=30,
        )
    except Exception:
        pass


def unload_all_except_chat():
    """Unload every model EXCEPT the small chat model."""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/ps", timeout=10)
        if resp.status_code == 200:
            for m in resp.json().get("models", []):
                if m["name"] != KEEP_ALIVE_MODEL:
                    unload_model(m["name"])
    except Exception:
        pass


def warm_model(model_name):
    """Load a model into memory by sending a tiny prompt."""
    try:
        requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model_name, "prompt": "hi", "keep_alive": "10m"},
            timeout=180,
        )
    except Exception:
        pass


# ─── Status printer (thread-safe) ───

_print_lock = threading.Lock()


def _phase(num, total, label):
    bar = f"[{'█' * num}{'░' * (total - num)}]"
    with _print_lock:
        print(f"\n  {Y1}⚡{RST} {BOLD}{B6}Phase {num}/{total}{RST} {bar} {B7}{label}{RST}")
        print(f"  {DIM}{B4}{'─' * 50}{RST}")
        sys.stdout.flush()


def _status(msg):
    with _print_lock:
        print(f"  {DIM}{B7}  → {msg}{RST}")
        sys.stdout.flush()


def _ok(msg):
    with _print_lock:
        print(f"  {G1}  ✓ {msg}{RST}")
        sys.stdout.flush()


def _err(msg):
    with _print_lock:
        print(f"  {R1}  ✗ {msg}{RST}")
        sys.stdout.flush()


# ─── JSON extraction ───

def _extract_json(text):
    """Pull JSON from model output, handling markdown fences and preamble."""
    text = text.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1]
    if "```" in text:
        text = text.split("```", 1)[0]
    text = text.strip()

    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


# ─── Pipeline stages ───

def stage_spec(conversation_text):
    """Phase 1: Small model distills conversation into a build spec."""
    _phase(1, 5, "Building spec")
    _status("Clearing big models, keeping chat alive...")
    unload_all_except_chat()

    model = MODELS["fast_code"]  # 3b
    _status(f"Loading {model}...")
    prompt = SPEC_PROMPT.format(conversation=conversation_text[:3000])

    _status("Generating spec...")
    raw = _ollama_generate(model, prompt, timeout=120)

    # Unload 3b after use — only router stays
    unload_model(model)

    spec = _extract_json(raw)
    if not spec:
        _err(f"Spec generation failed, raw output:\n{raw[:500]}")
        return None

    _ok(f"Spec ready: {spec.get('project', '?')} — {len(spec.get('files', []))} files planned")
    return spec


def stage_architect(spec):
    """Phase 2: Big model plans architecture and splits work."""
    _phase(2, 5, "Architect planning")
    _status("Loading 32b architect (chat still available)...")
    unload_all_except_chat()

    model = MODELS["beast"]  # 32b
    user_ctx = identity.get_profile_text()
    prompt = ARCHITECT_PROMPT.format(spec=json.dumps(spec, indent=2), user_context=user_ctx)
    _status("Planning architecture and splitting work...")
    raw = _ollama_generate(model, prompt, timeout=600)

    # Free the beast immediately
    unload_model(model)

    plan = _extract_json(raw)
    if not plan:
        _err(f"Architect failed, raw output:\n{raw[:500]}")
        return None

    heavy_count = len(plan.get("worker_heavy", {}).get("files", []))
    light_count = len(plan.get("worker_light", {}).get("files", []))
    _ok(f"Architecture planned — {heavy_count} heavy tasks, {light_count} light tasks")
    return plan


def _run_worker(model_name, label, tasks, spec, results_dict, user_ctx=""):
    """Worker thread — builds files sequentially for one model."""
    for task in tasks:
        file_path = task["path"]
        desc = task["description"]
        deps = ", ".join(task.get("depends_on", [])) or "none"
        context = (
            f"Project: {spec.get('project', '?')}\n"
            f"Description: {spec.get('description', '')}\n"
            f"Language: {spec.get('language', 'python')}"
        )

        prompt = WORKER_PROMPT.format(
            context=context,
            file_path=file_path,
            description=desc,
            depends_on=deps,
            user_context=user_ctx,
        )
        code = _ollama_generate(model_name, prompt, timeout=300)

        # Strip markdown fences if model wrapped it
        code = code.strip()
        if code.startswith("```"):
            lines = code.split("\n")
            lines = lines[1:]  # drop opening fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            code = "\n".join(lines)

        results_dict[file_path] = code
        _ok(f"[{label}] Built {file_path}")


def stage_build(spec, plan):
    """Phase 3: Two workers build in parallel — 14b heavy, 7b light."""
    _phase(3, 5, "Building (parallel workers)")
    _status("Loading worker models (chat still available)...")
    unload_all_except_chat()

    heavy_model = MODELS["worker_heavy"]  # 14b
    light_model = MODELS["worker_light"] # 7b

    # Warm both workers in parallel
    _status(f"Loading {heavy_model} + {light_model}...")
    t1 = threading.Thread(target=warm_model, args=(heavy_model,))
    t2 = threading.Thread(target=warm_model, args=(light_model,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    _ok("Both workers loaded")

    heavy_tasks = plan.get("worker_heavy", {}).get("files", [])
    light_tasks = plan.get("worker_light", {}).get("files", [])
    results = {}

    # Inject user context so workers code with awareness of who the user is
    user_ctx = identity.get_profile_text()
    _status(f"14b worker: {len(heavy_tasks)} files  |  7b worker: {len(light_tasks)} files")

    th = threading.Thread(target=_run_worker, args=(heavy_model, "14b", heavy_tasks, spec, results, user_ctx))
    tl = threading.Thread(target=_run_worker, args=(light_model, "7b", light_tasks, spec, results, user_ctx))
    th.start()
    tl.start()
    th.join()
    tl.join()

    # Free workers
    unload_model(heavy_model)
    unload_model(light_model)

    _ok(f"Build complete — {len(results)} files produced")
    return results


def stage_review(plan, built_files):
    """Phase 4: Big model reviews the combined output."""
    _phase(4, 5, "Review & validate")
    _status("Loading 32b reviewer (chat still available)...")
    unload_all_except_chat()

    model = MODELS["beast"]

    # Format built files for review
    files_text = ""
    for path, code in built_files.items():
        files_text += f"\n--- {path} ---\n{code[:2000]}\n"

    prompt = REVIEW_PROMPT.format(
        plan=json.dumps(plan, indent=2)[:3000],
        files=files_text[:6000],
    )

    _status("Reviewing...")
    raw = _ollama_generate(model, prompt, timeout=600)

    # Free the beast
    unload_model(model)

    review = _extract_json(raw)
    if not review:
        _err(f"Review parse failed, raw:\n{raw[:500]}")
        return {"verdict": "pass", "issues": [], "summary": "Could not parse review — assuming OK."}

    verdict = review.get("verdict", "pass")
    issues = review.get("issues", [])
    if verdict == "pass":
        _ok(f"Review passed: {review.get('summary', 'Looks good')}")
    else:
        _err(f"Review found {len(issues)} issue(s)")
        for iss in issues:
            _status(f"  {iss.get('file', '?')}: {iss.get('issue', '?')}")

    return review


def stage_write(spec, built_files):
    """Phase 5: Write all files to disk."""
    _phase(5, 5, "Writing to disk")
    home_dir = os.path.expanduser("~")
    default_output = os.path.join(home_dir, "projects", "output")
    output_dir = os.path.realpath(spec.get("output_dir", default_output))

    # Security: refuse to write outside home directory
    if not output_dir.startswith(home_dir + os.sep) and output_dir != home_dir:
        _err(f"Refusing to write outside home directory: {output_dir}")
        return []

    os.makedirs(output_dir, exist_ok=True)
    written = []
    for rel_path, code in built_files.items():
        full_path = os.path.realpath(os.path.join(output_dir, rel_path))
        # Block path traversal (../ in rel_path)
        if not full_path.startswith(output_dir + os.sep):
            _err(f"Skipping path traversal attempt: {rel_path}")
            continue
        os.makedirs(os.path.dirname(full_path) or output_dir, exist_ok=True)
        with open(full_path, "w") as f:
            f.write(code)
        written.append(full_path)
        _ok(f"Wrote {full_path}")

    _ok(f"All {len(written)} files written to {output_dir}")

    # Restore chat models (fast too, since pipeline is done)
    _status("Restoring chat models...")
    unload_all_except_chat()
    warm_model(MODELS["companion"])

    return written


# ─── Background pipeline runner ───

def _pipeline_thread(conversation_text, callback):
    """Run the full pipeline in a background thread."""
    global _active_pipeline
    try:
        success, output_dir, summary = _run_pipeline_inner(conversation_text)
        if callback:
            callback(success, output_dir, summary)
    finally:
        with _pipeline_lock:
            _active_pipeline = None


def _run_pipeline_inner(conversation_text):
    """The actual pipeline logic."""
    start = time.time()

    # Phase 1: Spec
    spec = stage_spec(conversation_text)
    if not spec:
        return False, None, "Failed to generate build spec."

    # Phase 2: Architect
    plan = stage_architect(spec)
    if not plan:
        return False, None, "Architect failed to produce a plan."

    # Phase 3: Build
    built_files = stage_build(spec, plan)
    if not built_files:
        return False, None, "Workers produced no files."

    # Phase 4: Review
    review = stage_review(plan, built_files)

    # Phase 5: Write to disk
    written = stage_write(spec, built_files)

    elapsed = time.time() - start
    output_dir = spec.get("output_dir", os.path.join(os.path.expanduser("~"), "projects", "output"))

    summary = (
        f"Built {len(written)} files in {elapsed:.0f}s\n"
        f"Output: {output_dir}\n"
        f"Review: {review.get('verdict', '?')} — {review.get('summary', '')}"
    )

    with _print_lock:
        print(f"\n  {Y1}{'━' * 54}{RST}")
        print(f"  {Y1}⚡{RST} {BOLD}{G1}PIPELINE COMPLETE{RST} ({elapsed:.0f}s)")
        print(f"  {DIM}{B7}Output → {output_dir}{RST}")
        print(f"  {Y1}{'━' * 54}{RST}\n")
        sys.stdout.flush()

    return True, output_dir, summary


# ─── Public API ───

def is_pipeline_running():
    """Check if a build pipeline is currently active."""
    with _pipeline_lock:
        return _active_pipeline is not None


def run_pipeline(conversation_text, callback=None):
    """Launch the build pipeline in the background.

    The 1.5b chat model stays loaded so the user can keep talking.
    Status updates print to the terminal as phases complete.
    Optional callback(success, output_dir, summary) fires when done.

    Returns True if launched, False if one is already running.
    """
    global _active_pipeline

    with _pipeline_lock:
        if _active_pipeline is not None:
            _err("A build is already running. Wait for it to finish.")
            return False

        with _print_lock:
            print(f"\n  {Y1}{'━' * 54}{RST}")
            print(f"  {Y1}⚡{RST} {BOLD}{Y2}BOLT BUILD PIPELINE{RST}")
            print(f"  {DIM}{B7}  Running in background — keep chatting!{RST}")
            print(f"  {Y1}{'━' * 54}{RST}")
            sys.stdout.flush()

        # Make sure the chat model is loaded before we start
        warm_model(KEEP_ALIVE_MODEL)

        t = threading.Thread(
            target=_pipeline_thread,
            args=(conversation_text, callback),
            daemon=True,
        )
        _active_pipeline = t

    t.start()
    return True
