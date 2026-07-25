#!/usr/bin/env bash
# install.sh – Install disco as a systemd user service.
#
# Curl one-liner (after pushing to GitHub):
#   curl -fsSL https://raw.githubusercontent.com/sann2sh/disco/main/install.sh | bash
#
# Or from a local clone:
#   ./install.sh
#
# Optional: pass custom disco args
#   DISCO_ARGS="--beat --sensitivity 1.2" bash install.sh

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
GITHUB_USER="sann2sh"     # ← change to your GitHub username before pushing
GITHUB_REPO="disco"
GITHUB_BRANCH="main"
BASE_URL="https://raw.githubusercontent.com/$GITHUB_USER/$GITHUB_REPO/$GITHUB_BRANCH"

DISCO_ARGS="${DISCO_ARGS:---beat}"   # override with env var if needed
INSTALL_DIR="$HOME/.local/lib/disco"
BIN_DIR="$HOME/.local/bin"
SERVICE_DIR="$HOME/.config/systemd/user"

# Source files to fetch
FILES=(disco.py audio.py processor.py keyboard.py config.py
       config.example.json 99-asus-kbd-brightness.rules disco.service)

# ── Colour output ─────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
info()    { echo -e "${GREEN}[✓]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
error()   { echo -e "${RED}[✗]${NC} $*"; exit 1; }
section() { echo -e "\n${BOLD}── $* ──────────────────────────────────────────${NC}"; }

echo -e "${BOLD}"
echo "   ██████╗ ██╗███████╗ ██████╗ ██████╗ "
echo "   ██╔══██╗██║██╔════╝██╔════╝██╔═══██╗"
echo "   ██║  ██║██║███████╗██║     ██║   ██║"
echo "   ██║  ██║██║╚════██║██║     ██║   ██║"
echo "   ██████╔╝██║███████║╚██████╗╚██████╔╝"
echo "   ╚═════╝ ╚═╝╚══════╝ ╚═════╝ ╚═════╝ "
echo -e "${NC}   audio-reactive ASUS TUF keyboard backlight\n"

# ── Locate Python ─────────────────────────────────────────────────────────────
section "Checking Python"
PYTHON=$(command -v python3 2>/dev/null || command -v python 2>/dev/null) \
    || error "Python not found. Install python3 and try again."
PYTHON_VER=$("$PYTHON" -c "import sys; print('.'.join(map(str,sys.version_info[:2])))")
info "Python $PYTHON_VER at $PYTHON"
[[ "$PYTHON_VER" < "3.10" ]] && error "Python 3.10+ required (got $PYTHON_VER)"

# ── Install Python deps ───────────────────────────────────────────────────────
section "Installing Python dependencies"
"$PYTHON" -m pip install --quiet --upgrade soundcard numpy \
    || error "pip install failed. Make sure pip is available."
info "soundcard + numpy ready"

# ── Get disco source files ────────────────────────────────────────────────────
section "Downloading disco"

# If we're running from a local clone that has the files, use them directly.
# Otherwise (curl | bash), download everything from GitHub.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-install.sh}")" 2>/dev/null && pwd || echo "")"

if [[ -f "$SCRIPT_DIR/disco.py" ]]; then
    info "Local source detected – using $SCRIPT_DIR"
    SRC="$SCRIPT_DIR"
else
    info "Downloading from github.com/$GITHUB_USER/$GITHUB_REPO"
    SRC=$(mktemp -d)
    trap 'rm -rf "$SRC"' EXIT
    for f in "${FILES[@]}"; do
        curl -fsSL "$BASE_URL/$f" -o "$SRC/$f" \
            || error "Failed to download $f from $BASE_URL"
    done
    info "Downloaded to $SRC"
fi

# ── Install files ─────────────────────────────────────────────────────────────
section "Installing to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR" "$BIN_DIR"
for f in "${FILES[@]}"; do
    [[ -f "$SRC/$f" ]] && cp "$SRC/$f" "$INSTALL_DIR/"
done
info "Files copied"

# Launcher wrapper in ~/.local/bin
cat > "$BIN_DIR/disco" << WRAPPER
#!/bin/bash
exec "$PYTHON" "$INSTALL_DIR/disco.py" "\$@"
WRAPPER
chmod +x "$BIN_DIR/disco"
info "Launcher: ~/.local/bin/disco"

# ── udev rule ─────────────────────────────────────────────────────────────────
section "Installing udev rule (requires sudo)"
sudo cp "$INSTALL_DIR/99-asus-kbd-brightness.rules" /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
info "Non-root sysfs access enabled"

# ── Systemd user service ──────────────────────────────────────────────────────
section "Setting up systemd service"
mkdir -p "$SERVICE_DIR"
sed \
    -e "s|PYTHON_BIN|$PYTHON|g" \
    -e "s|DISCO_SCRIPT|$INSTALL_DIR/disco.py|g" \
    -e "s|--beat|$DISCO_ARGS|g" \
    "$INSTALL_DIR/disco.service" > "$SERVICE_DIR/disco.service"

systemctl --user daemon-reload
systemctl --user enable disco.service
systemctl --user restart disco.service
info "Service enabled and started"

# ── Linger ────────────────────────────────────────────────────────────────────
loginctl enable-linger "$USER" 2>/dev/null \
    && info "Linger enabled – starts at boot even without login" \
    || warn "Could not enable linger – service starts on login only"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}✓ disco is installed and running!${NC}"
echo ""
echo "  Status:   systemctl --user status disco"
echo "  Logs:     journalctl --user -u disco -f"
echo "  Stop:     systemctl --user stop disco"
echo "  Disable:  systemctl --user disable disco"
echo "  Config:   $INSTALL_DIR/config.example.json"
echo "  Remove:   curl -fsSL $BASE_URL/uninstall.sh | bash"
echo ""
