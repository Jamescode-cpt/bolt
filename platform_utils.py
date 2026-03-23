"""BOLT platform detection — single source of truth for OS differences.

Import IS_MAC / IS_LINUX and the helper functions from here.
Every custom tool that touches platform-specific code should use this.
"""

import os
import platform
import subprocess
import shutil
import time

# ─── Platform constants ───

SYSTEM = platform.system()          # "Darwin" or "Linux"
IS_MAC = SYSTEM == "Darwin"
IS_LINUX = SYSTEM == "Linux"
PLATFORM_NAME = "macOS" if IS_MAC else "Linux"


# ─── Cross-platform helpers ───

def get_cpu_usage(duration=0.5):
    """Measure CPU usage. Returns (usage_pct, core_count, load_str)."""
    cores = os.cpu_count() or 1

    # Load average — works on both platforms
    load_str = ""
    try:
        load = os.getloadavg()
        load_str = f"{load[0]:.2f} {load[1]:.2f} {load[2]:.2f}"
    except (OSError, AttributeError):
        pass

    if IS_LINUX:
        return _cpu_usage_linux(duration, cores, load_str)
    else:
        return _cpu_usage_mac(duration, cores, load_str)


def _cpu_usage_linux(duration, cores, load_str):
    def read_stat():
        try:
            with open("/proc/stat") as f:
                for line in f:
                    if line.startswith("cpu "):
                        vals = list(map(int, line.split()[1:]))
                        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
                        return sum(vals), idle
        except Exception:
            pass
        return None

    s1 = read_stat()
    if not s1:
        return None, cores, load_str
    time.sleep(duration)
    s2 = read_stat()
    if not s2:
        return None, cores, load_str
    d_total = s2[0] - s1[0]
    d_idle = s2[1] - s1[1]
    if d_total == 0:
        return 0.0, cores, load_str
    return (1.0 - d_idle / d_total) * 100.0, cores, load_str


def _cpu_usage_mac(duration, cores, load_str):
    """Use top -l 2 to sample CPU on macOS."""
    try:
        out = subprocess.check_output(
            ["top", "-l", "2", "-n", "0", "-s", "1"],
            text=True, timeout=10, stderr=subprocess.DEVNULL,
        )
        # Parse the last "CPU usage:" line
        for line in reversed(out.splitlines()):
            if "CPU usage:" in line:
                # "CPU usage: 5.26% user, 10.52% sys, 84.21% idle"
                parts = line.split(",")
                for part in parts:
                    if "idle" in part:
                        idle_pct = float(part.strip().split("%")[0].split()[-1])
                        return 100.0 - idle_pct, cores, load_str
    except Exception:
        pass
    return None, cores, load_str


def get_ram_info():
    """Returns dict with total_kb, used_kb, avail_kb, swap_total_kb, swap_used_kb."""
    if IS_LINUX:
        return _ram_info_linux()
    else:
        return _ram_info_mac()


def _ram_info_linux():
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(":")
                    try:
                        info[key] = int(parts[1])
                    except ValueError:
                        pass
        total = info.get("MemTotal", 0)
        avail = info.get("MemAvailable", 0)
        swap_total = info.get("SwapTotal", 0)
        swap_free = info.get("SwapFree", 0)
        return {
            "total_kb": total, "used_kb": total - avail, "avail_kb": avail,
            "swap_total_kb": swap_total, "swap_used_kb": swap_total - swap_free,
        }
    except Exception:
        return None


def _ram_info_mac():
    try:
        # Total RAM
        total_bytes = int(subprocess.check_output(
            ["sysctl", "-n", "hw.memsize"], text=True, timeout=5
        ).strip())
        total_kb = total_bytes // 1024

        # vm_stat for page info
        out = subprocess.check_output(["vm_stat"], text=True, timeout=5)
        page_size = 4096  # default, parse if available
        pages = {}
        for line in out.splitlines():
            if "page size of" in line:
                try:
                    page_size = int(line.split()[-2])
                except (ValueError, IndexError):
                    pass
            parts = line.split(":")
            if len(parts) == 2:
                key = parts[0].strip()
                val = parts[1].strip().rstrip(".")
                try:
                    pages[key] = int(val)
                except ValueError:
                    pass

        free_pages = pages.get("Pages free", 0)
        inactive = pages.get("Pages inactive", 0)
        speculative = pages.get("Pages speculative", 0)
        avail_kb = (free_pages + inactive + speculative) * page_size // 1024
        used_kb = total_kb - avail_kb

        # Swap
        swap_total_kb = 0
        swap_used_kb = 0
        try:
            swap_out = subprocess.check_output(
                ["sysctl", "-n", "vm.swapusage"], text=True, timeout=5
            ).strip()
            # "total = 2048.00M  used = 123.45M  free = 1924.55M"
            for part in swap_out.split("  "):
                part = part.strip()
                if part.startswith("total"):
                    val = part.split("=")[1].strip().rstrip("M")
                    swap_total_kb = int(float(val) * 1024)
                elif part.startswith("used"):
                    val = part.split("=")[1].strip().rstrip("M")
                    swap_used_kb = int(float(val) * 1024)
        except Exception:
            pass

        return {
            "total_kb": total_kb, "used_kb": used_kb, "avail_kb": avail_kb,
            "swap_total_kb": swap_total_kb, "swap_used_kb": swap_used_kb,
        }
    except Exception:
        return None


def get_uptime_secs():
    """Returns system uptime in seconds."""
    if IS_LINUX:
        try:
            with open("/proc/uptime") as f:
                return float(f.read().split()[0])
        except Exception:
            return None
    else:
        # macOS: sysctl kern.boottime
        try:
            out = subprocess.check_output(
                ["sysctl", "-n", "kern.boottime"], text=True, timeout=5
            ).strip()
            # "{ sec = 1234567890, usec = 123456 } ..."
            import re
            m = re.search(r"sec\s*=\s*(\d+)", out)
            if m:
                boot_ts = int(m.group(1))
                return time.time() - boot_ts
        except Exception:
            pass
        return None


def get_total_mem_kb():
    """Get total physical memory in kB."""
    info = get_ram_info()
    return info["total_kb"] if info else 1


def get_battery_info():
    """Returns battery string or None if no battery."""
    if IS_LINUX:
        return _battery_linux()
    else:
        return _battery_mac()


def _battery_linux():
    base = "/sys/class/power_supply"
    if not os.path.isdir(base):
        return "Battery: no power_supply sysfs found"
    results = []
    for entry in os.listdir(base):
        try:
            with open(os.path.join(base, entry, "type")) as f:
                typ = f.read().strip()
        except Exception:
            continue
        if typ.lower() != "battery":
            continue
        bat = os.path.join(base, entry)
        capacity = _read_file_safe(os.path.join(bat, "capacity"))
        status = _read_file_safe(os.path.join(bat, "status"))
        parts = [f"Battery ({entry}):"]
        if capacity:
            parts.append(f"{capacity}%")
        if status:
            parts.append(f"[{status}]")
        results.append(" ".join(parts))
    if not results:
        return "Battery: no battery detected (desktop or unsupported)"
    return "\n".join(results)


def _battery_mac():
    try:
        out = subprocess.check_output(
            ["pmset", "-g", "batt"], text=True, timeout=5
        ).strip()
        # Parse "InternalBattery-0 (id=...)  95%; charging; 1:23 remaining"
        for line in out.splitlines():
            if "InternalBattery" in line or "%" in line:
                return f"Battery: {line.strip()}"
        return "Battery: no battery detected (desktop Mac)"
    except Exception:
        return "Battery: unable to read (pmset not available)"


def get_temps():
    """Returns temperature string."""
    if IS_LINUX:
        return _temps_linux()
    else:
        return _temps_mac()


def _temps_linux():
    base = "/sys/class/thermal"
    if not os.path.isdir(base):
        return "Temps: no thermal sysfs found"
    results = []
    for entry in sorted(os.listdir(base)):
        if not entry.startswith("thermal_zone"):
            continue
        path = os.path.join(base, entry)
        temp_raw = _read_file_safe(os.path.join(path, "temp"))
        type_name = _read_file_safe(os.path.join(path, "type")) or entry
        if temp_raw:
            try:
                temp_c = int(temp_raw) / 1000.0
                results.append((type_name, temp_c))
            except ValueError:
                pass
    if not results:
        return "Temps: no thermal zones reporting"
    lines = [f"  {name}: {temp:.1f}°C" for name, temp in results]
    return "Temps:\n" + "\n".join(lines)


def _temps_mac():
    """macOS temps — try osx-cpu-temp or powermetrics (if available)."""
    # Try osx-cpu-temp (homebrew installable)
    if shutil.which("osx-cpu-temp"):
        try:
            out = subprocess.check_output(
                ["osx-cpu-temp"], text=True, timeout=5
            ).strip()
            return f"Temps:\n  CPU: {out}"
        except Exception:
            pass
    # Try reading via powermetrics (requires no sudo for some data on newer macOS)
    # This often requires root, so we'll just note it's unavailable
    return "Temps: install 'osx-cpu-temp' (brew install osx-cpu-temp) for temperature readings"


def get_interfaces():
    """Get network interface listing. Returns string."""
    if IS_LINUX:
        try:
            out = subprocess.run(
                ["ip", "-brief", "addr"], capture_output=True, text=True, timeout=5,
            )
            if out.returncode == 0 and out.stdout.strip():
                lines = ["  Interfaces:"]
                for line in out.stdout.strip().splitlines():
                    parts = line.split()
                    if len(parts) >= 3:
                        iface, state = parts[0], parts[1]
                        addrs = " ".join(parts[2:])
                        lines.append(f"    {iface} ({state}): {addrs}")
                return "\n".join(lines)
        except Exception:
            pass
    else:
        try:
            out = subprocess.run(
                ["ifconfig"], capture_output=True, text=True, timeout=5,
            )
            if out.returncode == 0 and out.stdout.strip():
                lines = ["  Interfaces:"]
                current_iface = None
                for line in out.stdout.splitlines():
                    if line and not line[0].isspace():
                        current_iface = line.split(":")[0]
                    elif "inet " in line and current_iface:
                        ip = line.strip().split()[1]
                        if ip != "127.0.0.1":
                            lines.append(f"    {current_iface}: {ip}")
                return "\n".join(lines)
        except Exception:
            pass
    return ""


def get_wifi_info():
    """Get WiFi signal info."""
    if IS_LINUX:
        try:
            with open("/proc/net/wireless") as f:
                lines = f.readlines()
            data_lines = [l.strip() for l in lines[2:] if l.strip()]
            if not data_lines:
                return "No wireless interfaces active"
            results = []
            for line in data_lines:
                parts = line.split()
                if len(parts) < 4:
                    continue
                iface = parts[0].rstrip(":")
                quality = parts[2].rstrip(".")
                signal = parts[3].rstrip(".")
                results.append(f"  {iface}: quality={quality} signal={signal} dBm")
            return "WiFi:\n" + "\n".join(results) if results else "No wireless data available"
        except FileNotFoundError:
            return "No wireless interface found (/proc/net/wireless missing)"
        except Exception as e:
            return f"WiFi read error: {e}"
    else:
        # macOS: airport utility
        airport = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
        if os.path.exists(airport):
            try:
                out = subprocess.check_output(
                    [airport, "-I"], text=True, timeout=5
                ).strip()
                ssid = rssi = noise = ""
                for line in out.splitlines():
                    line = line.strip()
                    if line.startswith("SSID:"):
                        ssid = line.split(":", 1)[1].strip()
                    elif line.startswith("agrCtlRSSI:"):
                        rssi = line.split(":", 1)[1].strip()
                    elif line.startswith("agrCtlNoise:"):
                        noise = line.split(":", 1)[1].strip()
                if ssid:
                    return f"WiFi:\n  SSID: {ssid}\n  RSSI: {rssi} dBm\n  Noise: {noise} dBm"
                return "WiFi: not connected"
            except Exception:
                pass
        # Fallback: networksetup
        try:
            out = subprocess.check_output(
                ["networksetup", "-getairportnetwork", "en0"],
                text=True, timeout=5
            ).strip()
            return f"WiFi:\n  {out}"
        except Exception:
            return "WiFi: unable to query wireless info"


def send_notification(title, body, urgency="normal"):
    """Send a desktop notification. Returns (success, message)."""
    if IS_LINUX:
        if not shutil.which("notify-send"):
            return False, (
                "notify-send not found. Install with:\n"
                "  sudo apt install libnotify-bin    # Debian/Ubuntu\n"
                "  sudo pacman -S libnotify          # Arch/SteamOS"
            )
        try:
            cmd = ["notify-send", "-u", urgency, title, body]
            subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return True, f"Notification sent: [{urgency}] {title}"
        except Exception as e:
            return False, f"notify-send error: {e}"
    else:
        # macOS: osascript
        try:
            script = f'display notification "{_escape_applescript(body)}" with title "{_escape_applescript(title)}"'
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=10,
            )
            return True, f"Notification sent: {title}"
        except Exception as e:
            return False, f"osascript error: {e}"


def get_clipboard_backends():
    """Returns list of (read_cmd, write_cmd, description) tuples for this platform."""
    if IS_MAC:
        return [
            (["pbpaste"], ["pbcopy"], "macOS clipboard"),
        ]
    else:
        return [
            (["wl-paste"], ["wl-copy"], "wl-clipboard (Wayland)"),
            (["xclip", "-selection", "clipboard", "-o"],
             ["xclip", "-selection", "clipboard", "-i"], "xclip"),
            (["xsel", "--clipboard", "--output"],
             ["xsel", "--clipboard", "--input"], "xsel"),
        ]


def get_screenshot_tools():
    """Returns list of (binary, args_template, description) for this platform."""
    if IS_MAC:
        return [
            ("screencapture", ["{output}"], "macOS screencapture"),
        ]
    else:
        return [
            ("grim", ["{output}"], "grim (Wayland)"),
            ("gnome-screenshot", ["-f", "{output}"], "gnome-screenshot"),
            ("scrot", ["{output}"], "scrot (X11)"),
            ("import", ["-window", "root", "{output}"], "ImageMagick import"),
            ("spectacle", ["-b", "-n", "-o", "{output}"], "KDE Spectacle"),
        ]


def get_tts_backends():
    """Returns list of TTS backend names for this platform."""
    if IS_MAC:
        return ["say"]  # Built-in on all Macs
    else:
        return ["espeak", "espeak-ng", "spd-say", "piper"]


def get_audio_player():
    """Returns the audio player command for piping raw audio."""
    if IS_MAC:
        return "afplay"
    else:
        return "aplay"


def get_process_list():
    """Get list of process dicts: pid, name, cpu, mem_pct, rss_kb, uid."""
    if IS_LINUX:
        return _procs_linux()
    else:
        return _procs_mac()


def _procs_linux():
    """Read processes from /proc."""
    clk = _get_clk_tck()
    uptime = get_uptime_secs() or 0
    total_mem = get_total_mem_kb()
    procs = []

    try:
        entries = os.listdir("/proc")
    except Exception:
        return procs

    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        base = f"/proc/{pid}"

        comm = _read_file_safe(f"{base}/comm")
        if comm is None:
            continue
        comm = comm.strip()

        stat_raw = _read_file_safe(f"{base}/stat")
        if not stat_raw:
            continue

        close_paren = stat_raw.rfind(")")
        if close_paren < 0:
            continue
        fields_after = stat_raw[close_paren + 2:].split()
        if len(fields_after) < 20:
            continue

        try:
            utime = int(fields_after[11])
            stime = int(fields_after[12])
            starttime = int(fields_after[19])
        except (IndexError, ValueError):
            continue

        total_time = utime + stime
        proc_uptime = uptime - (starttime / clk)
        cpu_pct = (total_time / clk / proc_uptime * 100) if proc_uptime > 0 else 0

        status_raw = _read_file_safe(f"{base}/status")
        rss_kb = 0
        uid = -1
        if status_raw:
            for line in status_raw.splitlines():
                if line.startswith("VmRSS:"):
                    try:
                        rss_kb = int(line.split()[1])
                    except (IndexError, ValueError):
                        pass
                elif line.startswith("Uid:"):
                    try:
                        uid = int(line.split()[1])
                    except (IndexError, ValueError):
                        pass

        mem_pct = (rss_kb / total_mem * 100) if total_mem > 0 else 0
        procs.append({
            "pid": pid, "name": comm, "cpu": cpu_pct,
            "mem_pct": mem_pct, "rss_kb": rss_kb, "uid": uid,
        })

    return procs


def _procs_mac():
    """Get process list via ps on macOS."""
    procs = []
    try:
        out = subprocess.check_output(
            ["ps", "-axo", "pid,user,pcpu,pmem,rss,comm"],
            text=True, timeout=10,
        )
        for line in out.splitlines()[1:]:  # skip header
            parts = line.split(None, 5)
            if len(parts) < 6:
                continue
            try:
                pid = int(parts[0])
                user = parts[1]
                cpu = float(parts[2])
                mem_pct = float(parts[3])
                rss_kb = int(parts[4])
                name = os.path.basename(parts[5])
                uid = 0 if user == "root" else -1
                procs.append({
                    "pid": pid, "name": name, "cpu": cpu,
                    "mem_pct": mem_pct, "rss_kb": rss_kb, "uid": uid,
                })
            except (ValueError, IndexError):
                continue
    except Exception:
        pass
    return procs


def get_local_ips():
    """Get all local IPs (cross-platform)."""
    import socket
    ips = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and ip != "127.0.0.1":
                ips.append(ip)
    except Exception:
        pass

    if not ips:
        if IS_LINUX:
            try:
                out = subprocess.check_output(
                    ["ip", "-4", "addr", "show"], text=True, timeout=5
                )
                for line in out.splitlines():
                    line = line.strip()
                    if line.startswith("inet ") and "127.0.0.1" not in line:
                        ip = line.split()[1].split("/")[0]
                        if ip not in ips:
                            ips.append(ip)
            except Exception:
                pass
        else:
            try:
                out = subprocess.check_output(
                    ["ifconfig"], text=True, timeout=5
                )
                for line in out.splitlines():
                    line = line.strip()
                    if line.startswith("inet ") and "127.0.0.1" not in line:
                        ip = line.split()[1]
                        if ip not in ips:
                            ips.append(ip)
            except Exception:
                pass
    return ips


def get_df_output():
    """Cross-platform df output."""
    if IS_LINUX:
        try:
            result = subprocess.run(
                ["df", "-h", "--output=source,fstype,size,used,avail,pcent,target"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
    # macOS or fallback: basic df -h (no --output flag)
    try:
        result = subprocess.run(
            ["df", "-h"], capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def get_ping_cmd(host, count=3, timeout=5):
    """Build a cross-platform ping command."""
    if IS_MAC:
        return ["ping", "-c", str(count), "-t", str(timeout), host]
    else:
        return ["ping", "-c", str(count), "-W", str(timeout), host]


def get_service_manager():
    """Returns 'systemd', 'launchd', or None."""
    if IS_LINUX and shutil.which("systemctl"):
        return "systemd"
    elif IS_MAC:
        return "launchd"
    return None


def get_package_manager():
    """Returns 'apt', 'brew', or None."""
    if IS_LINUX and shutil.which("apt"):
        return "apt"
    elif IS_MAC and shutil.which("brew"):
        return "brew"
    return None


def get_bluetooth_tool():
    """Returns 'bluetoothctl', 'system_profiler', or None."""
    if IS_LINUX and shutil.which("bluetoothctl"):
        return "bluetoothctl"
    elif IS_MAC:
        return "system_profiler"
    return None


def get_log_command():
    """Get the system log command for this platform."""
    if IS_LINUX and shutil.which("journalctl"):
        return ["journalctl", "--no-pager", "-n", "30", "--output=short-iso"]
    elif IS_MAC:
        return ["log", "show", "--last", "5m", "--style", "compact"]
    return None


def detect_gpu_mac():
    """Detect GPU on macOS via system_profiler."""
    try:
        out = subprocess.check_output(
            ["system_profiler", "SPDisplaysDataType"],
            text=True, timeout=10,
        )
        for line in out.splitlines():
            line = line.strip()
            if "Chipset Model:" in line or "Chip:" in line:
                name = line.split(":", 1)[1].strip()
                return {"name": name, "vram_gb": 0}
    except Exception:
        pass
    # Apple Silicon shares system RAM
    if _is_apple_silicon():
        return {"name": "Apple Silicon (integrated GPU)", "vram_gb": 0}
    return None


def _is_apple_silicon():
    """Check if running on Apple Silicon."""
    return IS_MAC and platform.machine() == "arm64"


# ─── Internal helpers ───

def _read_file_safe(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return None


def _get_clk_tck():
    try:
        return os.sysconf("SC_CLK_TCK")
    except Exception:
        return 100


def _escape_applescript(s):
    """Escape a string for use in AppleScript."""
    return s.replace("\\", "\\\\").replace('"', '\\"')
