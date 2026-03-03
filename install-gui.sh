#!/usr/bin/env bash
# BOLT GUI Installer — zenity-based graphical installer for Linux.
# For non-technical users who don't want to touch a terminal.
#
# Usage: download this file, make it executable, double-click it.
# Or:    bash install-gui.sh
set -u  # treat unset vars as errors, but don't exit on command failures (GUI dialogs return non-zero on cancel)

BOLT_DIR="${BOLT_DIR:-$HOME/bolt}"
REPO_URL="${BOLT_REPO:-https://github.com/Jamescode-cpt/bolt.git}"
ICON_DIR="$HOME/.local/share/icons"
APP_DIR="$HOME/.local/share/applications"
DESKTOP_DIR="$HOME/Desktop"

# ─── Detect GUI toolkit ───

GUI=""
if command -v zenity &>/dev/null; then
    GUI="zenity"
elif command -v kdialog &>/dev/null; then
    GUI="kdialog"
fi

# If no GUI toolkit, try to install zenity
if [ -z "$GUI" ]; then
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        case "$ID" in
            ubuntu|debian|linuxmint|pop)
                sudo apt-get install -y zenity 2>/dev/null && GUI="zenity" ;;
            fedora|rhel|centos|rocky|alma)
                sudo dnf install -y zenity 2>/dev/null && GUI="zenity" ;;
            arch|manjaro|endeavouros)
                sudo pacman -S --noconfirm zenity 2>/dev/null && GUI="zenity" ;;
        esac
    fi
fi

if [ -z "$GUI" ]; then
    echo "ERROR: No GUI toolkit found (zenity or kdialog). Install zenity and try again."
    exit 1
fi

# ─── GUI helpers ───

gui_info() {
    if [ "$GUI" = "zenity" ]; then
        zenity --info --title="BOLT" --text="$1" --width=400 2>/dev/null
    else
        kdialog --msgbox "$1" --title "BOLT" 2>/dev/null
    fi
}

gui_error() {
    if [ "$GUI" = "zenity" ]; then
        zenity --error --title="BOLT" --text="$1" --width=400 2>/dev/null
    else
        kdialog --error "$1" --title "BOLT" 2>/dev/null
    fi
}

gui_question() {
    if [ "$GUI" = "zenity" ]; then
        zenity --question --title="BOLT" --text="$1" --width=400 2>/dev/null
        return $?
    else
        kdialog --yesno "$1" --title "BOLT" 2>/dev/null
        return $?
    fi
}

gui_password() {
    if [ "$GUI" = "zenity" ]; then
        zenity --password --title="BOLT needs your password" 2>/dev/null
    else
        kdialog --password "BOLT needs your password to install system packages:" --title "BOLT" 2>/dev/null
    fi
}

gui_progress_pulse() {
    # $1 = title text
    if [ "$GUI" = "zenity" ]; then
        zenity --progress --pulsate --auto-close --no-cancel --title="BOLT" --text="$1" --width=400 2>/dev/null
    else
        # kdialog doesn't have a great pulsate, use busyindicator
        kdialog --progressbar "$1" 0 2>/dev/null || true
    fi
}

gui_list() {
    # $1 = text, $2..N = items (value label pairs)
    local text="$1"; shift
    if [ "$GUI" = "zenity" ]; then
        zenity --list --radiolist --title="BOLT" --text="$text" \
            --column="Pick" --column="Tier" --column="Description" \
            --width=500 --height=350 "$@" 2>/dev/null
    else
        # kdialog radio
        kdialog --radiolist "$text" "$@" --title "BOLT" 2>/dev/null
    fi
}

gui_entry() {
    if [ "$GUI" = "zenity" ]; then
        zenity --entry --title="BOLT" --text="$1" --width=400 2>/dev/null
    else
        kdialog --inputbox "$1" "" --title "BOLT" 2>/dev/null
    fi
}

# ─── Step runner (runs command with progress dialog) ───

run_with_progress() {
    local title="$1"; shift
    "$@" 2>&1 | gui_progress_pulse "$title"
}

# ─── Welcome ───

gui_info "Welcome to BOLT!\n\nBuilt On Local Terrain — a local AI companion that runs on your machine.\n\nThis installer will:\n  1. Install any missing system tools\n  2. Install Ollama (AI model runner)\n  3. Download BOLT\n  4. Pull AI models for your hardware\n  5. Create a desktop shortcut\n\nNo data leaves your machine. No cloud required."

# ─── Detect OS ───

OS=""
PKG_INSTALL=""
if [ -f /etc/os-release ]; then
    . /etc/os-release
    case "$ID" in
        ubuntu|debian|linuxmint|pop)
            OS="debian"; PKG_INSTALL="apt-get install -y" ;;
        fedora|rhel|centos|rocky|alma)
            OS="fedora"; PKG_INSTALL="dnf install -y" ;;
        arch|manjaro|endeavouros)
            OS="arch"; PKG_INSTALL="pacman -S --noconfirm" ;;
    esac
fi

if [ -z "$OS" ]; then
    gui_error "Could not detect your Linux distribution.\n\nPlease install manually:\n  python3, pip, git, ollama\n\nThen run: python3 ~/bolt/bolt.py"
    exit 1
fi

# ─── Check which deps are missing BEFORE asking for password ───

MISSING=""
command -v python3 &>/dev/null || MISSING="$MISSING python3"
command -v git &>/dev/null     || MISSING="$MISSING git"
command -v openssl &>/dev/null || MISSING="$MISSING openssl"
command -v pip3 &>/dev/null || command -v pip &>/dev/null || MISSING="$MISSING pip"

SUDO_PASS=""
HAVE_SUDO=false

run_sudo() {
    if [ "$HAVE_SUDO" = true ]; then
        if [ -n "$SUDO_PASS" ]; then
            echo "$SUDO_PASS" | sudo -S "$@" 2>/dev/null
        else
            sudo "$@" 2>/dev/null
        fi
    fi
}

if [ -n "$MISSING" ]; then
    # Only ask for password if we actually need to install something
    if gui_question "BOLT needs to install:$MISSING\n\nThis requires your system password.\nYour password is only used for this install step.\n\nContinue?"; then
        SUDO_PASS=$(gui_password) || true
        HAVE_SUDO=true
    else
        gui_error "Cannot continue without:$MISSING\n\nInstall them manually and run this installer again."
        exit 1
    fi
else
    HAVE_SUDO=false
fi

# ─── Install system deps (only if something is missing) ───

if [ -n "$MISSING" ]; then
    (
        echo "10"; echo "# Installing missing packages:$MISSING"
        if ! command -v python3 &>/dev/null; then
            echo "20"; echo "# Installing Python..."
            run_sudo $PKG_INSTALL python3 python3-pip 2>&1
        fi

        if ! command -v git &>/dev/null; then
            echo "40"; echo "# Installing Git..."
            run_sudo $PKG_INSTALL git 2>&1
        fi

        if ! command -v openssl &>/dev/null; then
            echo "60"; echo "# Installing OpenSSL..."
            run_sudo $PKG_INSTALL openssl 2>&1
        fi

        echo "80"; echo "# Checking optional tools..."
        if [ "$HAVE_SUDO" = true ]; then
            run_sudo $PKG_INSTALL espeak-ng 2>&1 || true
        fi

        echo "100"
    ) | if [ "$GUI" = "zenity" ]; then
        zenity --progress --title="BOLT" --text="Installing system packages..." \
            --width=400 --auto-close --no-cancel 2>/dev/null || true
    else
        cat > /dev/null
    fi
fi

# ─── Install Ollama ───

if ! command -v ollama &>/dev/null; then
    (
        echo "# Downloading Ollama..."
        curl -fsSL https://ollama.com/install.sh | sh 2>&1
    ) | gui_progress_pulse "Installing Ollama (AI model engine)..."

    if ! command -v ollama &>/dev/null; then
        gui_error "Could not install Ollama.\n\nPlease install it manually:\n  curl -fsSL https://ollama.com/install.sh | sh\n\nThen run this installer again."
        exit 1
    fi
fi

# Start Ollama if not running
if ! curl -sf http://localhost:11434/api/tags &>/dev/null; then
    nohup ollama serve &>/dev/null &
    sleep 3
fi

# ─── Clone BOLT ───

if [ -d "$BOLT_DIR" ]; then
    (cd "$BOLT_DIR" && git pull --ff-only 2>&1 || true; echo "done") | gui_progress_pulse "Updating BOLT..."
else
    (git clone "$REPO_URL" "$BOLT_DIR" 2>&1 || true; echo "done") | gui_progress_pulse "Downloading BOLT..."
fi

if [ ! -d "$BOLT_DIR" ]; then
    gui_error "Failed to download BOLT.\n\nCheck your internet connection and try again."
    exit 1
fi

# ─── Python deps ───

if [ -f "$BOLT_DIR/requirements.txt" ]; then
    (pip install --user -r "$BOLT_DIR/requirements.txt" 2>&1 || pip3 install --user -r "$BOLT_DIR/requirements.txt" 2>&1 || true; echo "done") \
        | gui_progress_pulse "Installing Python packages..."
fi

# ─── Hardware detection & tier selection ───

RAM_GB=$(python3 -c "
try:
    with open('/proc/meminfo') as f:
        for line in f:
            if line.startswith('MemTotal:'):
                print(int(line.split()[1]) // 1024 // 1024)
                break
except:
    print(8)
" 2>/dev/null)

if [ "$RAM_GB" -ge 32 ]; then
    REC_TIER="beast"
elif [ "$RAM_GB" -ge 16 ]; then
    REC_TIER="full"
elif [ "$RAM_GB" -ge 8 ]; then
    REC_TIER="standard"
else
    REC_TIER="minimal"
fi

TIER=$(gui_list "Your system has ${RAM_GB}GB RAM.\nRecommended tier: ${REC_TIER}\n\nPick your model tier:" \
    $([ "$REC_TIER" = "minimal" ] && echo "TRUE" || echo "FALSE") "minimal" "Minimal — 2 models (~4GB RAM)" \
    $([ "$REC_TIER" = "standard" ] && echo "TRUE" || echo "FALSE") "standard" "Standard — 4 models (~10GB RAM)" \
    $([ "$REC_TIER" = "full" ] && echo "TRUE" || echo "FALSE") "full" "Full — 5 models (~18GB RAM)" \
    $([ "$REC_TIER" = "beast" ] && echo "TRUE" || echo "FALSE") "beast" "Beast — 6 models (~28GB RAM)" \
) || TIER="$REC_TIER"

[ -z "$TIER" ] && TIER="$REC_TIER"

# ─── Pull models ───

# Get model list for selected tier
MODELS=$(python3 -c "
import sys; sys.path.insert(0, '$BOLT_DIR')
import env
models = env.MODEL_TIERS.get('$TIER', env.MODEL_TIERS['standard'])
for name in models.values():
    print(name)
" 2>/dev/null)

MODEL_COUNT=$(echo "$MODELS" | wc -l)
CURRENT=0

for MODEL in $MODELS; do
    CURRENT=$((CURRENT + 1))
    PCT=$(( CURRENT * 100 / MODEL_COUNT ))

    (
        echo "$PCT"
        echo "# Pulling $MODEL ($CURRENT of $MODEL_COUNT)..."
        ollama pull "$MODEL" 2>&1
    ) | if [ "$GUI" = "zenity" ]; then
        zenity --progress --title="BOLT" --text="Pulling AI models..." \
            --width=400 --auto-close --no-cancel --percentage=0 2>/dev/null || true
    else
        cat > /dev/null
    fi
done

# ─── Generate SSL certs (for phone access) ───

CERT_DIR="$BOLT_DIR/data"
mkdir -p "$CERT_DIR"

if [ ! -f "$CERT_DIR/bolt-cert.pem" ]; then
    openssl req -x509 -newkey rsa:2048 \
        -keyout "$CERT_DIR/bolt-key.pem" \
        -out "$CERT_DIR/bolt-cert.pem" \
        -days 365 -nodes \
        -subj "/CN=bolt.local" 2>/dev/null || true
    [ -f "$CERT_DIR/bolt-key.pem" ] && chmod 600 "$CERT_DIR/bolt-key.pem"
fi

# ─── Write config ───

USER_NAME=$(gui_entry "What's your name? (or leave blank to skip)") || USER_NAME=""

python3 -c "
import sys, json, time, os
sys.path.insert(0, '$BOLT_DIR')
import env

tier = '$TIER'
models = env.MODEL_TIERS.get(tier, env.MODEL_TIERS['standard'])
config = {
    'tier': tier,
    'models': models,
    'ram_gb': env.RAM_GB,
    'cpu_cores': env.CPU_CORES,
    'advanced_tools': True,
    'setup_complete': True,
    'created_at': time.strftime('%Y-%m-%d %H:%M:%S'),
}
name = '$USER_NAME'.strip()
if name:
    config['user_name'] = name

os.makedirs(env.DATA_DIR, exist_ok=True)
with open(env.CONFIG_PATH, 'w') as f:
    json.dump(config, f, indent=2)

# Save name to profile DB
if name:
    import memory, identity
    memory.init_db()
    identity.init_profile_tables()
    identity.save_fact('name', 'name', name, confidence=1.0, source='setup')
" 2>/dev/null

# ─── Create desktop launcher ───

mkdir -p "$APP_DIR" "$ICON_DIR"

# Generate a simple bolt icon (lightning bolt SVG → PNG)
python3 -c "
import os
svg = '''<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<svg width=\"256\" height=\"256\" viewBox=\"0 0 256 256\" xmlns=\"http://www.w3.org/2000/svg\">
  <defs>
    <linearGradient id=\"bg\" x1=\"0\" y1=\"0\" x2=\"0\" y2=\"1\">
      <stop offset=\"0%\" stop-color=\"#1e3a5f\"/>
      <stop offset=\"100%\" stop-color=\"#0a0e1a\"/>
    </linearGradient>
    <linearGradient id=\"bolt\" x1=\"0\" y1=\"0\" x2=\"0\" y2=\"1\">
      <stop offset=\"0%\" stop-color=\"#fbbf24\"/>
      <stop offset=\"50%\" stop-color=\"#f59e0b\"/>
      <stop offset=\"100%\" stop-color=\"#ef4444\"/>
    </linearGradient>
  </defs>
  <rect width=\"256\" height=\"256\" rx=\"48\" fill=\"url(#bg)\"/>
  <path d=\"M 148 28 L 88 128 L 128 128 L 108 228 L 168 128 L 128 128 L 148 28 Z\" fill=\"url(#bolt)\"/>
</svg>'''
svg_path = os.path.expanduser('~/.local/share/icons/bolt.svg')
with open(svg_path, 'w') as f:
    f.write(svg)
# Try converting to PNG if possible
try:
    import subprocess
    subprocess.run(['rsvg-convert', '-w', '256', '-h', '256', svg_path, '-o',
        os.path.expanduser('~/.local/share/icons/bolt.png')],
        capture_output=True, timeout=10)
except Exception:
    pass
" 2>/dev/null

# Determine icon path (prefer PNG, fall back to SVG)
ICON_PATH="$ICON_DIR/bolt.svg"
[ -f "$ICON_DIR/bolt.png" ] && ICON_PATH="$ICON_DIR/bolt.png"

# Create .desktop file in applications menu
cat > "$APP_DIR/bolt.desktop" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=BOLT
Comment=Built On Local Terrain — Local AI Companion
Exec=bash $BOLT_DIR/bolt-launcher.sh
Icon=$ICON_PATH
Terminal=false
Categories=Utility;
StartupNotify=true
EOF

chmod +x "$APP_DIR/bolt.desktop"

# Also copy to Desktop if it exists
if [ -d "$DESKTOP_DIR" ]; then
    cp "$APP_DIR/bolt.desktop" "$DESKTOP_DIR/bolt.desktop"
    chmod +x "$DESKTOP_DIR/bolt.desktop"
    # GNOME: mark as trusted
    gio set "$DESKTOP_DIR/bolt.desktop" metadata::trusted true 2>/dev/null || true
fi

# ─── Done! ───

if gui_question "BOLT is installed!\n\nA shortcut has been added to your desktop and app menu.\n\nWould you like to launch BOLT now?"; then
    bash "$BOLT_DIR/bolt-launcher.sh" &
fi
