"""BOLT custom tool — Bluetooth device management via bluetoothctl.

Read-only operations only: status, devices, scan, info, connected.
Never pairs, connects, disconnects, or removes devices.
"""

import os
import re

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

# MAC address pattern
MAC_PATTERN = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')


def _check_bluetoothctl():
    """Check if bluetoothctl is available."""
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
    """Run a bluetoothctl command and return (success, stdout, stderr)."""
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
        # bluetoothctl sometimes outputs ANSI escape codes — strip them
        stdout = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', stdout)
        stderr = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', stderr)
        return True, stdout, stderr
    except subprocess.TimeoutExpired:
        return False, "", f"Command timed out after {timeout}s"
    except FileNotFoundError:
        return False, "", "bluetoothctl not found"
    except Exception as e:
        return False, "", f"Error running bluetoothctl: {e}"


def _cmd_status():
    """Show Bluetooth adapter status."""
    ok, stdout, stderr = _run_btctl("show")
    if not ok:
        return f"Failed to get adapter status: {stderr}"
    if not stdout:
        return "No Bluetooth adapter found or bluetoothd is not running."

    # Parse the output into readable format
    lines = ["Bluetooth Adapter Status:\n"]
    current_controller = None

    for line in stdout.split("\n"):
        line = line.strip()
        if not line:
            continue

        if line.startswith("Controller"):
            current_controller = line
            lines.append(f"  {line}")
        elif ":" in line:
            # Key-value pairs like "Name: hostname"
            lines.append(f"    {line}")

    if len(lines) == 1:
        # Fallback: just show raw output
        lines.append(stdout)

    return "\n".join(lines)


def _cmd_devices():
    """List paired devices."""
    ok, stdout, stderr = _run_btctl("devices", "Paired")
    if not ok:
        # Try without "Paired" argument (older bluetoothctl versions)
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
        # Lines look like: "Device AA:BB:CC:DD:EE:FF DeviceName"
        match = re.match(r'Device\s+((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})\s*(.*)', line)
        if match:
            mac = match.group(1)
            name = match.group(2).strip() or "(unnamed)"
            lines.append(f"  {mac}  {name}")
            device_count += 1
        elif "Device" in line:
            lines.append(f"  {line}")
            device_count += 1

    if device_count == 0:
        return "No paired devices found."

    lines.append(f"\n  Total: {device_count} paired device(s)")
    return "\n".join(lines)


def _cmd_scan():
    """Scan for nearby Bluetooth devices (10 seconds)."""
    import subprocess
    import time

    # Use a subprocess approach: start scan, wait, then get devices
    # bluetoothctl scan needs special handling since it's interactive

    # First, try to scan using a timed approach
    try:
        # Start scanning in background using a shell pipeline
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

        # Strip ANSI codes
        stdout = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', stdout or "")

    except Exception as e:
        return f"Scan error: {e}"

    # Now get the list of discovered devices
    ok, dev_stdout, dev_stderr = _run_btctl("devices")
    if not ok:
        # Fall back to parsing scan output directly
        pass

    # Parse discovered devices from scan output + devices list
    devices = {}

    # Parse scan output for NEW/CHG device lines
    for line in stdout.split("\n"):
        line = line.strip()
        match = re.search(r'(?:NEW|CHG)\s+Device\s+((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})\s*(.*)', line)
        if match:
            mac = match.group(1)
            name = match.group(2).strip()
            if name and mac not in devices:
                devices[mac] = name

    # Also parse devices list output
    if dev_stdout:
        for line in (dev_stdout or "").split("\n"):
            line = line.strip()
            match = re.match(r'Device\s+((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})\s*(.*)', line)
            if match:
                mac = match.group(1)
                name = match.group(2).strip() or "(unnamed)"
                if mac not in devices:
                    devices[mac] = name

    if not devices:
        return f"Scan completed ({SCAN_DURATION}s). No devices found nearby."

    lines = [f"Scan completed ({SCAN_DURATION}s). Found {len(devices)} device(s):\n"]
    for mac, name in sorted(devices.items(), key=lambda x: x[1]):
        display_name = name if name else "(unnamed)"
        lines.append(f"  {mac}  {display_name}")

    return "\n".join(lines)


def _cmd_info(mac):
    """Show info for a specific device by MAC address."""
    if not MAC_PATTERN.match(mac):
        return f"Invalid MAC address format: {mac}. Expected format: AA:BB:CC:DD:EE:FF"

    ok, stdout, stderr = _run_btctl("info", mac)
    if not ok:
        return f"Failed to get device info: {stderr}"
    if not stdout:
        return f"No information found for device {mac}. Device may not be known."

    # Check for "not available" response
    if "not available" in stdout.lower():
        return f"Device {mac} is not known. Try scanning first."

    lines = [f"Device Info for {mac}:\n"]
    for line in stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("Device"):
            lines.append(f"  {line}")
        elif ":" in line:
            lines.append(f"    {line}")
        else:
            lines.append(f"    {line}")

    return "\n".join(lines)


def _cmd_connected():
    """List currently connected devices."""
    # Try the "devices Connected" subcommand (newer bluetoothctl)
    ok, stdout, stderr = _run_btctl("devices", "Connected")
    if not ok or not stdout:
        # Fallback: get all devices and check each one's info for "Connected: yes"
        ok2, dev_stdout, _ = _run_btctl("devices")
        if not ok2 or not dev_stdout:
            if not ok:
                return f"Failed to list connected devices: {stderr}"
            return "No connected devices found."

        connected = []
        for line in dev_stdout.split("\n"):
            match = re.match(r'Device\s+((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})\s*(.*)', line.strip())
            if match:
                mac = match.group(1)
                name = match.group(2).strip() or "(unnamed)"
                # Check if connected
                ok3, info_stdout, _ = _run_btctl("info", mac)
                if ok3 and "Connected: yes" in info_stdout:
                    connected.append((mac, name))

        if not connected:
            return "No devices currently connected."

        lines = [f"Connected Devices ({len(connected)}):\n"]
        for mac, name in connected:
            lines.append(f"  {mac}  {name}")
        return "\n".join(lines)

    # Parse "devices Connected" output
    if "Device" not in stdout:
        return "No devices currently connected."

    lines = ["Connected Devices:\n"]
    count = 0
    for line in stdout.split("\n"):
        line = line.strip()
        match = re.match(r'Device\s+((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})\s*(.*)', line)
        if match:
            mac = match.group(1)
            name = match.group(2).strip() or "(unnamed)"
            lines.append(f"  {mac}  {name}")
            count += 1

    if count == 0:
        return "No devices currently connected."

    lines.insert(0, f"Connected Devices ({count}):\n")
    # Remove the old first line we added
    lines.pop(1)
    return "\n".join(lines)


def run(args):
    """Bluetooth management dispatcher.

    Args is a string: command [options]
    """
    args = (args or "").strip()

    if not args:
        return (
            "Usage:\n"
            '  <tool name="bluetooth">status</tool> — adapter status\n'
            '  <tool name="bluetooth">devices</tool> — list paired devices\n'
            '  <tool name="bluetooth">scan</tool> — scan for nearby devices (10s)\n'
            '  <tool name="bluetooth">info AA:BB:CC:DD:EE:FF</tool> — device info\n'
            '  <tool name="bluetooth">connected</tool> — list connected devices'
        )

    # Check that bluetoothctl is available
    btctl_path, err = _check_bluetoothctl()
    if err:
        return err

    parts = args.split(None, 1)
    command = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""

    try:
        if command == "status":
            return _cmd_status()
        elif command == "devices":
            return _cmd_devices()
        elif command == "scan":
            return _cmd_scan()
        elif command == "info":
            if not rest:
                return "Usage: info <MAC_ADDRESS>  (e.g., info AA:BB:CC:DD:EE:FF)"
            return _cmd_info(rest.strip())
        elif command == "connected":
            return _cmd_connected()
        else:
            # Security: block any write operations that might be attempted
            blocked = {"pair", "trust", "untrust", "connect", "disconnect", "remove",
                       "power", "agent", "default-agent", "discoverable", "pairable",
                       "set-alias", "block", "unblock"}
            if command in blocked:
                return (
                    f"Command '{command}' is blocked for security. "
                    "This tool is read-only. Pairing, connecting, and device management "
                    "should be done manually by the user."
                )
            return (
                f"Unknown bluetooth command: {command}\n"
                "Available commands: status, devices, scan, info, connected"
            )
    except Exception as e:
        return f"bluetooth error: {e}"
