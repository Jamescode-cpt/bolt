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

if [ -f /etc/os-release ]; then
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
elif [[ "$(uname)" == "Darwin" ]]; then
    OS="macos"
    if command -v brew &>/dev/null; then
        PKG_INSTALL="brew install"
    fi
fi

if [ "$OS" == "unknown" ]; then
    err "Could not detect OS. Install dependencies manually:"
    info "  python3, pip, git, openssl, espeak-ng (optional)"
    info "Then clone the repo and run: python3 setup.py"
    exit 1
fi

ok "Detected: $OS"

# ─── Install system deps ───
header "System Dependencies"

install_if_missing() {
    local cmd="$1"
    local pkg="${2:-$1}"
    if command -v "$cmd" &>/dev/null; then
        ok "$cmd already installed"
    else
        info "Installing $pkg..."
        $PKG_INSTALL "$pkg" || err "Failed to install $pkg"
    fi
}

case "$OS" in
    debian)
        sudo apt-get update -qq
        install_if_missing python3 python3
        install_if_missing pip python3-pip
        install_if_missing git git
        install_if_missing openssl openssl
        # Optional: TTS
        $PKG_INSTALL espeak-ng 2>/dev/null || info "espeak-ng not available (TTS won't work, that's OK)"
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
            err "Homebrew not found. Install it: https://brew.sh"
            exit 1
        fi
        install_if_missing python3 python3
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
    curl -fsSL https://ollama.com/install.sh | sh
    if command -v ollama &>/dev/null; then
        ok "Ollama installed"
    else
        err "Ollama install failed. Install manually: https://ollama.com"
    fi
fi

# Start Ollama if not running
if ! curl -sf http://localhost:11434/api/tags &>/dev/null; then
    info "Starting Ollama..."
    nohup ollama serve &>/dev/null &
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

if [ -f requirements.txt ]; then
    pip install --user -r requirements.txt 2>/dev/null || pip3 install --user -r requirements.txt
    ok "Python deps installed"
else
    info "No requirements.txt found, skipping"
fi

# ─── Create launcher ───
header "Creating Launcher"

LAUNCHER_DIR="$HOME/.local/bin"
mkdir -p "$LAUNCHER_DIR"

cat > "$LAUNCHER_DIR/bolt" << EOF
#!/usr/bin/env bash
cd "$BOLT_DIR" && python3 bolt.py "\$@"
EOF
chmod +x "$LAUNCHER_DIR/bolt"
ok "Created $LAUNCHER_DIR/bolt"

# Add to PATH if needed
if [[ ":$PATH:" != *":$LAUNCHER_DIR:"* ]]; then
    info "Adding $LAUNCHER_DIR to PATH..."
    SHELL_RC="$HOME/.bashrc"
    [ -f "$HOME/.zshrc" ] && SHELL_RC="$HOME/.zshrc"
    echo "" >> "$SHELL_RC"
    echo "# BOLT" >> "$SHELL_RC"
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_RC"
    info "Added to $SHELL_RC — restart your shell or run: source $SHELL_RC"
fi

# ─── First-run setup ───
header "Running BOLT Setup"
echo ""

cd "$BOLT_DIR"
python3 setup.py

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
