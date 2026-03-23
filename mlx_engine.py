"""BOLT MLX Engine — Apple Silicon native inference via mlx-lm.

DISABLED BY DEFAULT. MLX loads full model weights into unified memory with no
management, which causes memory pressure and system freezes on 16GB Macs.
Ollama handles memory properly and is the safe default.

To enable: set BOLT_USE_MLX=1 environment variable (at your own risk).
Only recommended on 32GB+ Macs.
"""

import os

# ─── MLX is OFF by default — opt-in only ───
_force_enabled = os.environ.get("BOLT_USE_MLX", "0") == "1"
_available = False
_mlx_lm = None
_mlx = None
_checked = False


def _check_availability():
    """Check if MLX is available AND explicitly enabled."""
    global _available, _mlx_lm, _mlx, _checked
    if _checked:
        return _available
    _checked = True

    # Must be explicitly opted in
    if not _force_enabled:
        return False

    import platform
    if platform.system() != "Darwin":
        return False

    try:
        import mlx
        import mlx_lm
        _mlx = mlx
        _mlx_lm = mlx_lm
        _available = True
    except ImportError:
        _available = False

    return _available


def is_available():
    return _check_availability()


# ─── Ollama-to-MLX model name mapping ───
MLX_MODEL_MAP = {
    "qwen2.5:1.5b":                      "mlx-community/Qwen2.5-1.5B-Instruct-4bit",
    "qwen2.5:7b":                        "mlx-community/Qwen2.5-7B-Instruct-4bit",
    "qwen2.5:3b":                        "mlx-community/Qwen2.5-3B-Instruct-4bit",
    "qwen2.5-coder:3b":                  "mlx-community/Qwen2.5-Coder-3B-Instruct-4bit",
    "qwen2.5-coder:7b":                  "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
    "qwen2.5-coder:14b":                 "mlx-community/Qwen2.5-Coder-14B-Instruct-4bit",
    "qwen2.5-coder:32b-instruct-q3_K_M": "mlx-community/Qwen2.5-Coder-32B-Instruct-4bit",
}


def get_mapped_model(ollama_name):
    if not _check_availability():
        return None
    return MLX_MODEL_MAP.get(ollama_name)


def get_status():
    if not _check_availability():
        if not _force_enabled:
            return {"available": False, "reason": "Disabled by default (set BOLT_USE_MLX=1 to enable)"}
        return {"available": False, "reason": "MLX not installed or not on macOS"}
    return {"available": True, "loaded_model": _loaded_model[0] if _loaded_model else None}


def list_available_models():
    return dict(MLX_MODEL_MAP)


# ─── Model cache ───
import threading

_loaded_model = None
_model_lock = threading.Lock()


def _get_model(ollama_name):
    global _loaded_model
    mlx_name = MLX_MODEL_MAP.get(ollama_name)
    if not mlx_name:
        return None, None, f"No MLX mapping for model: {ollama_name}"

    with _model_lock:
        if _loaded_model and _loaded_model[0] == mlx_name:
            return _loaded_model[1], _loaded_model[2], None

        if _loaded_model:
            _loaded_model = None
            import gc
            gc.collect()

        try:
            model, tokenizer = _mlx_lm.load(mlx_name)
            _loaded_model = (mlx_name, model, tokenizer)
            return model, tokenizer, None
        except Exception as e:
            return None, None, f"Failed to load MLX model {mlx_name}: {e}"


def unload_all():
    global _loaded_model
    with _model_lock:
        _loaded_model = None
        import gc
        gc.collect()


# ─── Chat interface ───

def chat(ollama_model_name, messages, stream=True):
    if not _check_availability():
        yield "[MLX disabled — using Ollama]"
        return

    model, tokenizer, error = _get_model(ollama_model_name)
    if error:
        yield f"[MLX error: {error}]"
        return

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

    try:
        prompt = tokenizer.apply_chat_template(
            clean, tokenize=False, add_generation_prompt=True,
        )
    except Exception as e:
        yield f"[MLX template error: {e}]"
        return

    try:
        if stream:
            for response in _mlx_lm.stream_generate(
                model, tokenizer, prompt=prompt, max_tokens=4096,
            ):
                text = response.text if hasattr(response, 'text') else str(response)
                if text:
                    yield text
        else:
            response = _mlx_lm.generate(
                model, tokenizer, prompt=prompt, max_tokens=4096, verbose=False,
            )
            yield response
    except Exception as e:
        yield f"[MLX generation error: {e}]"


def chat_full(ollama_model_name, messages):
    return "".join(chat(ollama_model_name, messages, stream=False))
