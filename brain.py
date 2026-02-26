"""BOLT brain — unified routing, model orchestration, identity injection, and tool loop."""

import json
import requests
import time
import memory
import state
import tools
import identity
import cloud
from config import MODELS, OLLAMA_URL, ROUTER_PROMPT, MAX_TOOL_LOOPS

# Current mode — shared state
_current_mode = "companion"


def get_mode():
    return _current_mode


def set_mode(mode):
    global _current_mode
    _current_mode = mode


def _ollama_chat(model, messages, stream=True):
    """Call Ollama chat API. Yields chunks if streaming, else returns full response."""
    clean = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if not content or not content.strip():
            continue
        if role not in ("user", "assistant", "system"):
            role = "user"
        if clean and clean[-1]["role"] == role and role != "system":
            clean[-1]["content"] += "\n" + content
        else:
            clean.append({"role": role, "content": content})

    if not clean:
        yield "[BOLT: No context to send.]"
        return

    payload = {"model": model, "messages": clean, "stream": stream}

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat", json=payload, stream=stream, timeout=300,
        )
    except requests.ConnectionError:
        yield f"[BOLT: Cannot reach Ollama at {OLLAMA_URL}. Is it running?]"
        return
    except requests.Timeout:
        yield "[BOLT: Request timed out.]"
        return
    except Exception as e:
        yield f"[BOLT: Connection error — {e}]"
        return

    if resp.status_code != 200:
        try:
            err_body = resp.text[:300]
        except Exception:
            err_body = f"HTTP {resp.status_code}"
        state.log("ollama_error", f"{model} HTTP {resp.status_code}: {err_body}")
        yield f"[BOLT: Model error (HTTP {resp.status_code}). Retrying with smaller context...]"
        fallback = [m for m in clean if m["role"] == "system"][:1]
        last_user = [m for m in clean if m["role"] == "user"]
        if last_user:
            fallback.append(last_user[-1])
        if fallback:
            try:
                r2 = requests.post(
                    f"{OLLAMA_URL}/api/chat",
                    json={"model": model, "messages": fallback, "stream": False},
                    timeout=300,
                )
                if r2.status_code == 200:
                    yield r2.json().get("message", {}).get("content", "")
                    return
            except Exception:
                pass
        yield "[BOLT: I hit an error. Try again or rephrase.]"
        return

    if stream:
        for line in resp.iter_lines():
            if not line:
                continue
            try:
                data = json.loads(line)
                chunk = data.get("message", {}).get("content", "")
                if chunk:
                    yield chunk
                if data.get("done"):
                    return
            except json.JSONDecodeError:
                continue
    else:
        try:
            data = resp.json()
            yield data.get("message", {}).get("content", "")
        except Exception:
            yield "[BOLT: Failed to parse response.]"


def _chat_full(model, messages):
    """Non-streaming call, returns full text."""
    parts = list(_ollama_chat(model, messages, stream=False))
    return "".join(parts)


def _classify(user_message):
    """Silently classify a user message."""
    prompt = ROUTER_PROMPT.format(message=user_message[:500])
    messages = [{"role": "user", "content": prompt}]
    result = _chat_full(MODELS["router"], messages).strip().lower()
    for cat in ("cloud", "code_beast", "code_complex", "code_simple", "companion"):
        if cat in result:
            return cat
    return "companion"


def _pick_model(category):
    """Map category to model key, respecting current mode."""
    if _current_mode == "companion" and category == "companion":
        return "companion"

    # Cloud routing — use Sonnet when available, fall back to local
    if category in ("cloud", "code_beast"):
        if cloud.is_available():
            return "cloud"
        # Offline fallback
        return "beast" if category == "code_beast" else "worker_heavy"

    return {
        "companion": "companion",
        "code_simple": "fast_code",
        "code_complex": "worker_heavy",
    }.get(category, "companion")


def _pick_mode_for_category(category):
    """Determine the effective mode context for this response."""
    if category == "companion":
        return "companion"
    return "code"


def process_message(session_id, user_message, stream_callback=None):
    """Main entry point: process a user message and return BOLT's response."""
    memory.save_message(session_id, "user", user_message)

    # 1. Classify
    category = _classify(user_message)
    model_key = _pick_model(category)
    effective_mode = _pick_mode_for_category(category)
    state.log("route", f"{category} -> {model_key} (mode={effective_mode})")

    # 2. Build context with identity injection
    context = _build_context_with_identity(session_id, effective_mode)

    # 3. Generate response with tool loop
    full_response = _generate_with_tools(
        model_key, context, session_id, stream_callback
    )

    # 4. Save assistant response
    memory.save_message(session_id, "assistant", full_response)
    state.log("response", f"model={model_key}, len={len(full_response)}")

    return full_response


def _build_context_with_identity(session_id, mode="companion"):
    """Build context with BOLT's unified identity injected."""
    budget = memory.MAX_CONTEXT_TOKENS
    messages = []

    # 1. Identity (replaces old static system prompt)
    bolt_identity = identity.build_identity(mode=mode, session_id=session_id)
    messages.append({"role": "system", "content": bolt_identity})
    budget -= memory.estimate_tokens(bolt_identity)

    # 2. Latest summary (compressed history)
    summary = memory.get_latest_summary(session_id)
    if summary:
        summary_text = f"[Conversation summary so far]: {summary['summary']}"
        cost = memory.estimate_tokens(summary_text)
        if cost < budget:
            messages.append({"role": "system", "content": summary_text})
            budget -= cost

    # 3. Active task
    task = memory.get_active_task()
    if task:
        task_text = f"[Current task]: {task['title']} (status: {task['status']})"
        cost = memory.estimate_tokens(task_text)
        if cost < budget:
            messages.append({"role": "system", "content": task_text})
            budget -= cost

    # 4. Recent messages that fit
    recent = memory.get_recent_messages(session_id)
    selected = []
    total_cost = 0
    for row in reversed(recent):
        cost = row["token_estimate"] or memory.estimate_tokens(row["content"])
        if total_cost + cost > budget:
            break
        selected.append(row)
        total_cost += cost
    selected.reverse()

    for row in selected:
        role = row["role"]
        if role in ("tool", "tool_result"):
            role = "system"
        elif role not in ("user", "assistant", "system"):
            role = "user"
        messages.append({"role": role, "content": row["content"]})

    return messages


def _generate_with_tools(model_key, context, session_id, stream_callback):
    """Generate a response, handling tool calls in a loop."""
    is_cloud = (model_key == "cloud")
    model_name = MODELS[model_key]
    messages = list(context)
    accumulated_text = ""

    for loop_num in range(MAX_TOOL_LOOPS):
        full_text = ""
        if is_cloud:
            # Cloud path — stream from Anthropic
            try:
                for chunk in cloud.chat(messages, stream_callback):
                    full_text += chunk
                    if stream_callback and loop_num == 0:
                        stream_callback(chunk)
                    elif stream_callback and loop_num > 0 and chunk:
                        stream_callback(chunk)
            except Exception as e:
                state.log("cloud_error", str(e))
                if full_text:
                    full_text += "\n[cloud connection lost, partial response]"
                else:
                    full_text = "[BOLT: Cloud brain failed — try again or I'll go local.]"
        elif stream_callback and loop_num == 0:
            for chunk in _ollama_chat(model_name, messages, stream=True):
                full_text += chunk
                stream_callback(chunk)
        else:
            full_text = _chat_full(model_name, messages)
            if stream_callback and loop_num > 0:
                stream_callback(full_text)

        # Check for tool calls
        tool_calls, cleaned_text = tools.parse_tool_calls(full_text)

        if not tool_calls:
            return accumulated_text + full_text if accumulated_text else full_text

        # Execute each tool call
        all_results = []
        for tool_name, tool_args in tool_calls:
            state.log("tool_call", f"{tool_name}: {tool_args[:100]}")
            success, result = tools.execute_tool(tool_name, tool_args)
            state.log("tool_result", f"{tool_name}: {'ok' if success else 'err'}")
            formatted = tools.format_tool_result(tool_name, result)
            all_results.append(formatted)
            memory.save_message(session_id, "tool", f"Called {tool_name}")
            memory.save_message(session_id, "tool_result", result[:500])

        if cleaned_text.strip():
            accumulated_text += cleaned_text + "\n"

        messages.append({"role": "assistant", "content": full_text})
        messages.append({"role": "user", "content": "Tool results:\n" + "\n".join(all_results)})

    return accumulated_text + full_text if accumulated_text else full_text


def preload_daily_trio():
    """Preload models for the current mode."""
    from config import COMPANION_MODELS
    for key in COMPANION_MODELS:
        model_name = MODELS[key]
        try:
            requests.post(
                f"{OLLAMA_URL}/api/chat",
                json={"model": model_name, "messages": [{"role": "user", "content": "hi"}], "stream": False},
                timeout=120,
            )
            state.log("preload", f"loaded {key}")
        except Exception:
            state.log("preload_fail", f"could not load {key}")
