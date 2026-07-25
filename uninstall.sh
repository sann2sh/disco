#!/usr/bin/env bash
# uninstall.sh – Remove disco completely.
#
# curl -fsSL https://raw.githubusercontent.com/sann2sh/disco/main/uninstall.sh | bash

set -euo pipefail

GREEN='\033[0;32m'; BOLD='\033[1m'; NC='\033[0m'
info() { echo -e "${GREEN}[✓]${NC} $*"; }

echo -e "${BOLD}Uninstalling disco…${NC}"

systemctl --user stop    disco.service 2>/dev/null && info "Service stopped"   || true
systemctl --user disable disco.service 2>/dev/null && info "Service disabled"  || true
systemctl --user daemon-reload

rm -f  "$HOME/.config/systemd/user/disco.service" && info "Service file removed"
rm -rf "$HOME/.local/lib/disco"                   && info "Library removed"
rm -f  "$HOME/.local/bin/disco"                   && info "Launcher removed"

sudo rm -f /etc/udev/rules.d/99-asus-kbd-brightness.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
info "udev rule removed"

echo -e "\n${GREEN}✓ disco uninstalled.${NC}"
