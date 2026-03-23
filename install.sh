#!/usr/bin/env bash
# BOLT installer — one-line install for Linux & macOS
# curl -fsSL https://raw.githubusercontent.com/Jamescode-cpt/bolt/main/install.sh | bash
set -euo pipefail

# ─── Colors ───
RST='\033[0m'
BOLD='\033[1m'
DIM='\033[2m'
B5='\033[38;5;33m'
B6='\033[38;5;39m'
B7='\033[38;5;75m'
Y1='\033[38;5;220m'
Y2='\033[38;5;226m'
R1='\033[38;5;196m'
G1='\033[38;5;82m'

info()  { echo -e "  ${B7}$1${RST}"; }
ok()    { echo -e "  ${G1}✓ $1${RST}"; }
err()   { echo -e "  ${R1}✗ $1${RST}"; }
header(){ echo -e "\n  ${Y1}⚡${RST} ${BOLD}${B6}$1${RST}\n  ${DIM}${B5}$(printf '─%.0s' {1..50})${RST}"; }

BOLT_DIR="${BOLT_DIR:-$HOME/bolt}"
REPO_URL="${BOLT_REPO:-https://github.com/Jamescode-cpt/bolt.git}"

# ─── Platform detection ───
IS_MAC=false
[[ "$(uname)" == "Darwin" ]] && IS_MAC=true

# Source brew if on Mac (so we can find brew-installed tools)
if $IS_MAC && [ -f /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
fi

# ─── Banner ───
echo ""
echo -e "  ${B5}╔══════════════════════════════════════════════════════╗${RST}"
echo -e "  ${B5}║${RST}    ${BOLD}${B6}B ${B7}O ${Y2}L ${R1}T${RST}   ${DIM}${B7}— Installer${RST}                          ${B5}║${RST}"
echo -e "  ${B5}╚══════════════════════════════════════════════════════╝${RST}"
echo ""

# ─── Detect OS ───
header "Detecting OS"

OS="unknown"
PKG_INSTALL=""

if $IS_MAC; then
    OS="macos"
    if command -v brew &>/dev/null; then
        PKG_INSTALL="brew install"
    fi
elif [ -f /etc/os-release ]; then
    . /etc/os-release
    case "$ID" in
        ubuntu|debian|linuxmint|pop)
            OS="debian"
            PKG_INSTALL="sudo apt-get install -y"
            ;;
        fedora|rhel|centos|rocky|alma)
            OS="fedora"
            PKG_INSTALL="sudo dnf install -y"
            ;;
        arch|manjaro|endeavouros)
            OS="arch"
            PKG_INSTALL="sudo pacman -S --noconfirm"
            ;;
    esac
fi

if [ "$OS" == "unknown" ]; then
    err "Could not detect OS. Install dependencies manually:"
    info "  python3, pip, git, openssl"
    info "Then clone the repo and run: python3 setup.py"
    exit 1
fi

ok "Detected: $OS $(uname -m)"

# ─── Install system deps ───
header "System Dependencies"

install_if_missing() {
    local cmd="$1"
    local pkg="${2:-$1}"
    if command -v "$cmd" &>/dev/null; then
        ok "$cmd already installed"
    else
        if [ -n "$PKG_INSTALL" ]; then
            info "Installing $pkg..."
            $PKG_INSTALL "$pkg" || err "Failed to install $pkg"
        else
            err "$cmd not found and no package manager available"
        fi
    fi
}

case "$OS" in
    debian)
        sudo apt-get update -qq
        install_if_missing python3 python3
        install_if_missing pip python3-pip
        install_if_missing git git
        install_if_missing openssl openssl
        $PKG_INSTALL espeak-ng 2>/dev/null || info "espeak-ng not available (TTS optional)"
        ;;
    fedora)
        install_if_missing python3 python3
        install_if_missing pip python3-pip
        install_if_missing git git
        install_if_missing openssl openssl
        $PKG_INSTALL espeak-ng 2>/dev/null || true
        ;;
    arch)
        install_if_missing python3 python
        install_if_missing pip python-pip
        install_if_missing git git
        install_if_missing openssl openssl
        $PKG_INSTALL espeak-ng 2>/dev/null || true
        ;;
    macos)
        if ! command -v brew &>/dev/null; then
            err "Homebrew not found. Installing it now..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            eval "$(/opt/homebrew/bin/brew shellenv)"
            PKG_INSTALL="brew install"
            if ! command -v brew &>/dev/null; then
                err "Homebrew install failed. Install it manually: https://brew.sh"
                exit 1
            fi
            ok "Homebrew installed"
        fi
        install_if_missing python3 python@3.12
        install_if_missing git git
        install_if_missing openssl openssl
        ;;
esac

# ─── Install Ollama ───
header "Ollama"

if command -v ollama &>/dev/null; then
    ok "Ollama already installed"
else
    info "Installing Ollama..."
    if $IS_MAC; then
        brew install ollama 2>/dev/null && ok "Ollama installed" || {
            err "brew install ollama failed — trying direct install"
            curl -fsSL https://ollama.com/install.sh | sh 2>/dev/null || err "Install Ollama manually: https://ollama.com"
        }
    else
        curl -fsSL https://ollama.com/install.sh | sh
        command -v ollama &>/dev/null && ok "Ollama installed" || err "Ollama install failed. Install manually: https://ollama.com"
    fi
fi

# Start Ollama if not running
if command -v ollama &>/dev/null && ! curl -sf http://localhost:11434/api/tags &>/dev/null; then
    info "Starting Ollama..."
    if $IS_MAC; then
        brew services start ollama 2>/dev/null || nohup ollama serve &>/dev/null &
    else
        nohup ollama serve &>/dev/null &
    fi
    sleep 3
fi

# ─── Clone BOLT ───
header "Downloading BOLT"

if [ -d "$BOLT_DIR" ]; then
    info "BOLT directory already exists at $BOLT_DIR"
    info "Updating..."
    cd "$BOLT_DIR" && git pull --ff-only 2>/dev/null || info "Not a git repo or can't pull, skipping update"
else
    info "Cloning to $BOLT_DIR..."
    git clone "$REPO_URL" "$BOLT_DIR"
    ok "Cloned BOLT"
fi

cd "$BOLT_DIR"

# ─── Python deps ───
header "Python Dependencies"

if $IS_MAC; then
    # macOS: use a venv to avoid PEP 668 restrictions
    PYTHON_CMD="python3"
    command -v python3.12 &>/dev/null && PYTHON_CMD="python3.12"

    if [ ! -d "$BOLT_DIR/venv" ]; then
        info "Creating Python virtual environment..."
        $PYTHON_CMD -m venv "$BOLT_DIR/venv"
        ok "venv created"
    fi
    source "$BOLT_DIR/venv/bin/activate"

    info "Installing Python packages..."
    pip install --quiet requests flask qrcode pillow cryptography 2>/dev/null
    ok "Core deps installed"

    # MLX for Apple Silicon
    if [[ "$(uname -m)" == "arm64" ]]; then
        info "Installing MLX (Apple Silicon native inference)..."
        pip install --quiet mlx-lm 2>/dev/null && ok "mlx-lm installed (2-5x faster than Ollama)" || info "mlx-lm install failed (optional)"
    fi
else
    # Linux: pip install directly
    if [ -f requirements.txt ]; then
        pip3 install --user -r requirements.txt 2>/dev/null || pip install --user -r requirements.txt 2>/dev/null || info "Some deps failed — non-critical"
        ok "Python deps installed"
    fi
fi

# ─── Create data dir ───
mkdir -p "$BOLT_DIR/data"

# ─── SSL Certs ───
header "SSL Certificates"

CERT_FILE="$BOLT_DIR/data/bolt-cert.pem"
KEY_FILE="$BOLT_DIR/data/bolt-key.pem"

if [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ]; then
    ok "SSL certs already exist"
else
    openssl req -x509 -newkey rsa:2048 \
        -keyout "$KEY_FILE" \
        -out "$CERT_FILE" \
        -days 365 -nodes \
        -subj "/CN=bolt.local" 2>/dev/null
    if [ -f "$CERT_FILE" ]; then
        chmod 600 "$KEY_FILE"
        ok "SSL certs generated (valid for 1 year)"
    else
        info "Could not generate SSL certs (web UI will work without HTTPS)"
    fi
fi

# ─── Create launcher ───
header "Creating Launcher"

if $IS_MAC; then
    # macOS: write launcher that sets up brew + venv
    mkdir -p "$HOME/.local/bin"
    cat > "$HOME/.local/bin/bolt" << LAUNCHER_EOF
#!/usr/bin/env bash
eval "\$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null
cd "$BOLT_DIR"
source venv/bin/activate 2>/dev/null
python3 bolt.py "\$@"
LAUNCHER_EOF
    chmod +x "$HOME/.local/bin/bolt"

    # Also update bolt.sh in the repo
    cat > "$BOLT_DIR/bolt.sh" << 'BOLTSH_EOF'
#!/usr/bin/env bash
eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null
cd "$(dirname "$0")"
source venv/bin/activate 2>/dev/null
python3 bolt.py "$@"
BOLTSH_EOF
    chmod +x "$BOLT_DIR/bolt.sh"

    # Symlink to /opt/homebrew/bin so it works immediately (no PATH fiddling)
    ln -sf "$HOME/.local/bin/bolt" /opt/homebrew/bin/bolt 2>/dev/null && ok "Created /opt/homebrew/bin/bolt (works immediately)" || true

    # Also add ~/.local/bin to PATH for future shells
    if ! grep -q "/.local/bin" "$HOME/.zshrc" 2>/dev/null; then
        echo '' >> "$HOME/.zshrc"
        echo '# BOLT' >> "$HOME/.zshrc"
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.zshrc"
    fi
    ok "Created ~/.local/bin/bolt"

    # ─── macOS Dock shortcut (Automator .app) ───
    APP_DIR="$HOME/Applications/BOLT.app/Contents/MacOS"
    mkdir -p "$APP_DIR"
    mkdir -p "$HOME/Applications/BOLT.app/Contents"

    # Info.plist
    cat > "$HOME/Applications/BOLT.app/Contents/Info.plist" << 'PLIST_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>bolt-launch</string>
    <key>CFBundleName</key>
    <string>BOLT</string>
    <key>CFBundleIdentifier</key>
    <string>local.bolt.app</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>14.0</string>
</dict>
</plist>
PLIST_EOF

    # Launch script
    cat > "$APP_DIR/bolt-launch" << APPLAUNCH_EOF
#!/usr/bin/env bash
eval "\$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null
cd "$BOLT_DIR"
source venv/bin/activate 2>/dev/null
python3 bolt.py --web &
sleep 3
open "http://localhost:3000"
APPLAUNCH_EOF
    chmod +x "$APP_DIR/bolt-launch"
    ok "Created ~/Applications/BOLT.app (drag to Dock)"

else
    # Linux: standard launcher
    LAUNCHER_DIR="$HOME/.local/bin"
    mkdir -p "$LAUNCHER_DIR"
    cat > "$LAUNCHER_DIR/bolt" << LAUNCHER_EOF
#!/usr/bin/env bash
cd "$BOLT_DIR" && python3 bolt.py "\$@"
LAUNCHER_EOF
    chmod +x "$LAUNCHER_DIR/bolt"
    ok "Created $LAUNCHER_DIR/bolt"

    # Add to PATH if needed
    if [[ ":$PATH:" != *":$LAUNCHER_DIR:"* ]]; then
        SHELL_RC="$HOME/.bashrc"
        [ -f "$HOME/.zshrc" ] && SHELL_RC="$HOME/.zshrc"
        echo '' >> "$SHELL_RC"
        echo '# BOLT' >> "$SHELL_RC"
        echo "export PATH=\"$LAUNCHER_DIR:\$PATH\"" >> "$SHELL_RC"
        info "Added to $SHELL_RC — restart your shell or run: source $SHELL_RC"
    fi
fi

# ─── Pull models ───
header "Pulling Models"

if command -v ollama &>/dev/null && curl -sf http://localhost:11434/api/tags &>/dev/null; then
    # Get models for detected tier
    if $IS_MAC; then
        source "$BOLT_DIR/venv/bin/activate" 2>/dev/null
    fi
    MODELS=$(cd "$BOLT_DIR" && python3 -c "
import env
models = env.get_tier_models()
for v in models.values():
    print(v)
" 2>/dev/null)

    if [ -n "$MODELS" ]; then
        TOTAL=$(echo "$MODELS" | wc -l | tr -d ' ')
        CURRENT=0
        for MODEL in $MODELS; do
            CURRENT=$((CURRENT + 1))
            info "Pulling $MODEL ($CURRENT of $TOTAL)..."
            ollama pull "$MODEL" 2>&1 | tail -1
        done
        ok "All models pulled"
    fi
else
    info "Ollama not running — skipping model pull. Run 'ollama pull <model>' later."
fi

# ─── Write config (non-interactive) ───
header "Configuring BOLT"

if $IS_MAC; then
    source "$BOLT_DIR/venv/bin/activate" 2>/dev/null
fi

cd "$BOLT_DIR"
python3 -c "
import os, sys, json, time
sys.path.insert(0, '.')
import env, memory, identity

tier = env.select_model_tier()
models = env.get_tier_models(tier)

os.makedirs(env.DATA_DIR, exist_ok=True)
config_path = env.CONFIG_PATH

# Don't overwrite existing config
if not os.path.exists(config_path):
    config = {
        'tier': tier,
        'models': models,
        'ram_gb': env.RAM_GB,
        'cpu_cores': env.CPU_CORES,
        'advanced_tools': True,
        'setup_complete': True,
        'created_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    }
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    print(f'  Config: {tier} tier ({len(models)} models)')
else:
    print('  Config already exists — keeping it')

memory.init_db()
identity.init_profile_tables()
print('  Database initialized')
" 2>/dev/null

ok "BOLT configured"

# ─── Done ───
echo ""
echo -e "  ${Y1}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
echo -e "  ${Y1}⚡${RST} ${BOLD}${G1}BOLT installed successfully!${RST}"
echo -e "  ${Y1}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
echo ""
echo -e "  ${B7}Start BOLT:${RST}"
echo -e "  ${Y2}  bolt${RST}          ${DIM}# CLI mode${RST}"
echo -e "  ${Y2}  bolt --web${RST}    ${DIM}# Web UI (phone access)${RST}"
echo ""
if $IS_MAC; then
    echo -e "  ${B7}macOS:${RST}"
    echo -e "  ${DIM}  BOLT.app is in ~/Applications — drag it to your Dock${RST}"
    echo -e "  ${DIM}  Or just type 'bolt' in any new terminal${RST}"
    echo ""
fi
