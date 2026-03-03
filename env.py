"""BOLT environment config — single source of truth for paths and hardware.

Auto-detects hardware. All values overridable via environment variables.
"""

import os
import subprocess
import re

# ─── Paths ───

BOLT_HOME = os.path.dirname(os.path.abspath(__file__))
USER_HOME = os.path.expanduser("~")
DATA_DIR = os.path.join(BOLT_HOME, "data")
DB_PATH = os.path.join(DATA_DIR, "bolt.db")
CONFIG_PATH = os.path.join(DATA_DIR, "bolt_config.json")
CERT_FILE = os.path.join(DATA_DIR, "bolt-cert.pem")
KEY_FILE = os.path.join(DATA_DIR, "bolt-key.pem")

# Derived dirs
DOWNLOADS_DIR = os.path.join(USER_HOME, "Downloads")
SCREENSHOTS_DIR = os.path.join(USER_HOME, "screenshots")
BACKUPS_DIR = os.path.join(USER_HOME, "bolt_backups")

# ─── Ollama ───

OLLAMA_URL = os.environ.get("BOLT_OLLAMA_URL", "http://localhost:11434")

# ─── Hardware detection ───


def detect_ram_gb():
    """Detect total system RAM in GB."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return round(kb / 1024 / 1024)
    except Exception:
        pass
    # macOS fallback
    try:
        out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True, timeout=5)
        return round(int(out.strip()) / 1024 / 1024 / 1024)
    except Exception:
        pass
    return 8  # safe default


def detect_cpu_cores():
    """Detect number of CPU cores."""
    try:
        return os.cpu_count() or 4
    except Exception:
        return 4


def detect_gpu():
    """Detect GPU info. Returns a dict with 'name' and 'vram_gb' or None."""
    # Try nvidia-smi
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            text=True, timeout=10
        )
        parts = out.strip().split(", ")
        if len(parts) >= 2:
            return {"name": parts[0], "vram_gb": round(int(parts[1]) / 1024)}
    except Exception:
        pass
    # Try ROCm (AMD)
    try:
        out = subprocess.check_output(["rocm-smi", "--showmeminfo", "vram"], text=True, timeout=10)
        total = 0
        for line in out.splitlines():
            if "Total" in line:
                match = re.search(r"(\d+)", line)
                if match:
                    total = int(match.group(1)) // (1024 * 1024)
        if total > 0:
            # Try to get GPU name
            name = "AMD GPU"
            try:
                name_out = subprocess.check_output(["rocm-smi", "--showproductname"], text=True, timeout=10)
                for line in name_out.splitlines():
                    if "Card" in line and "series" in line.lower():
                        name = line.strip()
                        break
            except Exception:
                pass
            return {"name": name, "vram_gb": total}
    except Exception:
        pass
    # Try lspci for basic GPU identification
    try:
        out = subprocess.check_output(["lspci"], text=True, timeout=5)
        for line in out.splitlines():
            if "VGA" in line or "3D" in line or "Display" in line:
                return {"name": line.split(": ", 1)[-1].strip(), "vram_gb": 0}
    except Exception:
        pass
    return None


def detect_hardware_string():
    """Build a human-readable hardware summary."""
    ram = RAM_GB
    cores = CPU_CORES
    gpu = GPU

    parts = [f"{ram}GB RAM", f"{cores} CPU cores"]
    if gpu:
        gpu_str = gpu["name"]
        if gpu["vram_gb"] > 0:
            gpu_str += f" ({gpu['vram_gb']}GB VRAM)"
        parts.append(gpu_str)
    return ", ".join(parts)


# ─── Computed values (cached at import time) ───

RAM_GB = int(os.environ.get("BOLT_RAM_GB", 0)) or detect_ram_gb()
CPU_CORES = detect_cpu_cores()
GPU = detect_gpu()


def select_model_tier():
    """Pick the appropriate model tier based on available RAM."""
    if RAM_GB >= 32:
        return "beast"
    elif RAM_GB >= 16:
        return "full"
    elif RAM_GB >= 8:
        return "standard"
    else:
        return "minimal"


# ─── Model tiers ───

MODEL_TIERS = {
    "minimal": {
        "router":    "qwen2.5:1.5b",
        "companion": "qwen2.5:3b",
    },
    "standard": {
        "router":       "qwen2.5:1.5b",
        "companion":    "qwen2.5:7b",
        "fast_code":    "qwen2.5-coder:3b",
        "worker_light": "qwen2.5-coder:7b",
    },
    "full": {
        "router":       "qwen2.5:1.5b",
        "companion":    "qwen2.5:7b",
        "fast_code":    "qwen2.5-coder:3b",
        "worker_light": "qwen2.5-coder:7b",
        "worker_heavy": "qwen2.5-coder:14b",
    },
    "beast": {
        "router":       "qwen2.5:1.5b",
        "companion":    "qwen2.5:7b",
        "fast_code":    "qwen2.5-coder:3b",
        "worker_light": "qwen2.5-coder:7b",
        "worker_heavy": "qwen2.5-coder:14b",
        "beast":        "qwen2.5-coder:32b-instruct-q3_K_M",
    },
}


def get_tier_models(tier=None):
    """Get the model dict for a tier. Falls back to auto-detected tier."""
    if tier is None:
        tier = select_model_tier()
    return MODEL_TIERS.get(tier, MODEL_TIERS["standard"])


def is_first_run():
    """Check if this is the first time BOLT is launched."""
    return not os.path.exists(CONFIG_PATH)
