"""BOLT custom tool — Bluetooth device info.

Cross-platform: Linux (bluetoothctl), macOS (system_profiler).
Read-only operations only: status, devices, scan, info, connected.
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from platform_utils import IS_MAC, IS_LINUX

TOOL_NAME = "bluetooth"
TOOL_DESC = (
    "Bluetooth device management (read-only). "
    '<tool name="bluetooth">status</tool> — adapter status. '
    '<tool name="bluetooth">devices</tool> — list paired devices. '
    '<tool name="bluetooth">scan</tool> — scan for nearby devices (10s). '
    '<tool name="bluetooth">info AA:BB:CC:DD:EE:FF</tool> — device info. '
    '<tool name="bluetooth">connected</tool> — list connected devices.'
)

BTCTL_TIMEOUT = 15
SCAN_DURATION = 10
MAC_PATTERN = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')


# ─── macOS implementation ───

def _mac_bt_info():
    """Get all Bluetooth info via system_profiler on macOS."""
    import subprocess
    try:
        out = subprocess.check_output(
            ["system_profiler", "SPBluetoothDataType"],
            text=True, timeout=15,
        )
        return out.strip()
    except Exception as e:
        return f"Error getting Bluetooth info: {e}"


def _mac_status():
    info = _mac_bt_info()
    if "Error" in info:
        return info
    lines = ["Bluetooth Adapter Status (macOS):\n"]
    for line in info.splitlines():
        stripped = line.strip()
        if any(k in stripped.lower() for k in ["address:", "state:", "chipset:", "firmware", "bluetooth"]):
            lines.append(f"  {stripped}")
    return "\n".join(lines) if len(lines) > 1 else info


def _mac_devices():
    info = _mac_bt_info()
    if "Error" in info:
        return info
    lines = ["Paired/Connected Devices (macOS):\n"]
    in_devices = False
    for line in info.splitlines():
        stripped = line.strip()
        if "Connected:" in stripped or "Paired:" in stripped or "Devices" in stripped:
            in_devices = True
            lines.append(f"\n  {stripped}")
        elif in_devices and stripped and ":" in stripped:
            lines.append(f"    {stripped}")
    return "\n".join(lines) if len(lines) > 1 else "No paired devices found.\n\n(Full output):\n" + info


def _mac_connected():
    info = _mac_bt_info()
    if "Error" in info:
        return info
    lines = ["Connected Devices (macOS):\n"]
    in_connected = False
    for line in info.splitlines():
        stripped = line.strip()
        if "Connected:" in stripped:
            in_connected = True
        elif in_connected:
            if stripped.startswith("Not Connected") or stripped == "":
                in_connected = False
            elif ":" in stripped:
                lines.append(f"  {stripped}")
    return "\n".join(lines) if len(lines) > 1 else "No devices currently connected."


# ─── Linux implementation (bluetoothctl) ───

def _check_bluetoothctl():
    import shutil
    path = shutil.which("bluetoothctl")
    if not path:
        return None, (
            "bluetoothctl not found. Install it with:\n"
            "  sudo apt install bluez        # Debian/Ubuntu\n"
            "  sudo pacman -S bluez-utils    # Arch\n"
            "  sudo dnf install bluez        # Fedora"
        )
    return path, None


def _run_btctl(*args, timeout=None):
    import subprocess
    if timeout is None:
        timeout = BTCTL_TIMEOUT
    cmd = ["bluetoothctl"] + list(args)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        stdout = result.stdout.strip() if result.stdout else ""
        stderr = result.stderr.strip() if result.stderr else ""
        stdout = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', stdout)
        stderr = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', stderr)
        return True, stdout, stderr
    except subprocess.TimeoutExpired:
        return False, "", f"Command timed out after {timeout}s"
    except FileNotFoundError:
        return False, "", "bluetoothctl not found"
    except Exception as e:
        return False, "", f"Error running bluetoothctl: {e}"


def _linux_status():
    ok, stdout, stderr = _run_btctl("show")
    if not ok:
        return f"Failed to get adapter status: {stderr}"
    if not stdout:
        return "No Bluetooth adapter found or bluetoothd is not running."
    lines = ["Bluetooth Adapter Status:\n"]
    for line in stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("Controller"):
            lines.append(f"  {line}")
        elif ":" in line:
            lines.append(f"    {line}")
    if len(lines) == 1:
        lines.append(stdout)
    return "\n".join(lines)


def _linux_devices():
    ok, stdout, stderr = _run_btctl("devices", "Paired")
    if not ok:
        ok, stdout, stderr = _run_btctl("paired-devices")
        if not ok:
            return f"Failed to list paired devices: {stderr}"
    if not stdout or stdout.strip() == "":
        return "No paired devices found."
    lines = ["Paired Devices:\n"]
    device_count = 0
    for line in stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        match = re.match(r'Device\s+((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})\s*(.*)', line)
        if match:
            mac = match.group(1)
            name = match.group(2).strip() or "(unnamed)"
            lines.append(f"  {mac}  {name}")
            device_count += 1
    if device_count == 0:
        return "No paired devices found."
    lines.append(f"\n  Total: {device_count} paired device(s)")
    return "\n".join(lines)


def _linux_scan():
    import subprocess
    try:
        proc = subprocess.Popen(
            ["bluetoothctl", "--timeout", str(SCAN_DURATION), "scan", "on"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, text=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=SCAN_DURATION + 5)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
        stdout = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', stdout or "")
    except Exception as e:
        return f"Scan error: {e}"

    ok, dev_stdout, _ = _run_btctl("devices")
    devices = {}
    for line in stdout.split("\n"):
        match = re.search(r'(?:NEW|CHG)\s+Device\s+((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})\s*(.*)', line.strip())
        if match:
            mac = match.group(1)
            name = match.group(2).strip()
            if name and mac not in devices:
                devices[mac] = name

    if dev_stdout:
        for line in (dev_stdout or "").split("\n"):
            match = re.match(r'Device\s+((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})\s*(.*)', line.strip())
            if match:
                mac = match.group(1)
                name = match.group(2).strip() or "(unnamed)"
                if mac not in devices:
                    devices[mac] = name

    if not devices:
        return f"Scan completed ({SCAN_DURATION}s). No devices found nearby."
    lines = [f"Scan completed ({SCAN_DURATION}s). Found {len(devices)} device(s):\n"]
    for mac, name in sorted(devices.items(), key=lambda x: x[1]):
        lines.append(f"  {mac}  {name if name else '(unnamed)'}")
    return "\n".join(lines)


def _linux_info(mac):
    if not MAC_PATTERN.match(mac):
        return f"Invalid MAC address format: {mac}. Expected: AA:BB:CC:DD:EE:FF"
    ok, stdout, stderr = _run_btctl("info", mac)
    if not ok:
        return f"Failed to get device info: {stderr}"
    if not stdout or "not available" in stdout.lower():
        return f"Device {mac} is not known. Try scanning first."
    lines = [f"Device Info for {mac}:\n"]
    for line in stdout.split("\n"):
        line = line.strip()
        if line:
            lines.append(f"  {line}")
    return "\n".join(lines)


def _linux_connected():
    ok, stdout, stderr = _run_btctl("devices", "Connected")
    if ok and stdout and "Device" in stdout:
        lines = ["Connected Devices:\n"]
        count = 0
        for line in stdout.split("\n"):
            match = re.match(r'Device\s+((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})\s*(.*)', line.strip())
            if match:
                lines.append(f"  {match.group(1)}  {match.group(2).strip() or '(unnamed)'}")
                count += 1
        if count == 0:
            return "No devices currently connected."
        return "\n".join(lines)

    # Fallback: check each device
    ok2, dev_stdout, _ = _run_btctl("devices")
    if not ok2 or not dev_stdout:
        return "No connected devices found."
    connected = []
    for line in dev_stdout.split("\n"):
        match = re.match(r'Device\s+((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})\s*(.*)', line.strip())
        if match:
            mac = match.group(1)
            name = match.group(2).strip() or "(unnamed)"
            ok3, info_stdout, _ = _run_btctl("info", mac)
            if ok3 and "Connected: yes" in info_stdout:
                connected.append((mac, name))
    if not connected:
        return "No devices currently connected."
    lines = [f"Connected Devices ({len(connected)}):\n"]
    for mac, name in connected:
        lines.append(f"  {mac}  {name}")
    return "\n".join(lines)


# ─── Dispatcher ───

def run(args):
    args = (args or "").strip()

    if not args:
        return (
            "Usage:\n"
            '  <tool name="bluetooth">status</tool> — adapter status\n'
            '  <tool name="bluetooth">devices</tool> — list paired devices\n'
            '  <tool name="bluetooth">scan</tool> — scan for nearby devices\n'
            '  <tool name="bluetooth">info AA:BB:CC:DD:EE:FF</tool> — device info\n'
            '  <tool name="bluetooth">connected</tool> — list connected devices'
        )

    if IS_LINUX:
        btctl_path, err = _check_bluetoothctl()
        if err:
            return err

    parts = args.split(None, 1)
    command = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""

    blocked = {"pair", "trust", "untrust", "connect", "disconnect", "remove",
               "power", "agent", "default-agent", "discoverable", "pairable",
               "set-alias", "block", "unblock"}
    if command in blocked:
        return (
            f"Command '{command}' is blocked for security. "
            "This tool is read-only."
        )

    try:
        if IS_MAC:
            if command == "status":
                return _mac_status()
            elif command == "devices":
                return _mac_devices()
            elif command == "scan":
                return "Bluetooth scanning on macOS requires system_profiler — showing known devices instead.\n\n" + _mac_devices()
            elif command == "info":
                return "Device info by MAC not available on macOS. Use 'devices' or 'status' instead.\n\n" + _mac_status()
            elif command == "connected":
                return _mac_connected()
        else:
            if command == "status":
                return _linux_status()
            elif command == "devices":
                return _linux_devices()
            elif command == "scan":
                return _linux_scan()
            elif command == "info":
                if not rest:
                    return "Usage: info <MAC_ADDRESS>"
                return _linux_info(rest.strip())
            elif command == "connected":
                return _linux_connected()

        return f"Unknown bluetooth command: {command}\nAvailable: status, devices, scan, info, connected"
    except Exception as e:
        return f"bluetooth error: {e}"
