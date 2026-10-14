#!/usr/bin/env bash
set -e

echo "=== OpenEQ - Peace Equalizer APO for Linux Installer ==="
echo "Configuring for PipeWire and PulseAudio..."

# detect package manager
if command -v pacman >/dev/null 2>&1; then
    echo "Detected Arch Linux / pacman. Checking dependencies..."
    sudo pacman -S --needed --noconfirm pipewire pipewire-audio wireplumber libpulse swh-plugins python-gobject gtk4 libadwaita
elif command -v dnf >/dev/null 2>&1; then
    echo "Detected Fedora / dnf. Checking dependencies..."
    sudo dnf install -y pipewire pipewire-pulseaudio wireplumber pulseaudio-utils swh-plugins python3-gobject gtk4 libadwaita
elif command -v apt-get >/dev/null 2>&1; then
    echo "Detected Debian/Ubuntu / apt. Checking dependencies..."
    sudo apt-get update
    sudo apt-get install -y pipewire wireplumber pulseaudio-utils swh-plugins python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1
elif command -v zypper >/dev/null 2>&1; then
    echo "Detected openSUSE / zypper. Checking dependencies..."
    sudo zypper install -y pipewire wireplumber pulseaudio-utils ladspa-swh-plugins python3-gobject gtk4 libadwaita-1-0
fi

# install user level
echo "Installing OpenEQ to ~/.local..."
mkdir -p "$HOME/.local/bin"
mkdir -p "$HOME/.local/lib/python3/site-packages/openeq"
mkdir -p "$HOME/.local/share/applications"
mkdir -p "$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$HOME/.config/openeq/presets"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cp -r "$SCRIPT_DIR/openeq"/* "$HOME/.local/lib/python3/site-packages/openeq/" 2>/dev/null || true
cp "$SCRIPT_DIR/bin/openeq" "$HOME/.local/bin/openeq"
chmod +x "$HOME/.local/bin/openeq"
cp "$SCRIPT_DIR/data/io.github.openeq.desktop" "$HOME/.local/share/applications/"
cp "$SCRIPT_DIR/data/io.github.openeq.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/"
cp "$SCRIPT_DIR/presets"/*.txt "$HOME/.config/openeq/presets/"

# update desktop database
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
gtk-update-icon-cache "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo "=== Installation Complete! ==="
echo "You can launch OpenEQ from your application menu or by running:"
echo "    openeq gui"
echo "CLI usage:"
echo "    openeq status"
echo "    openeq list"
echo "    openeq apply 'Bass Boost'"
echo "    openeq apply --backend pulseaudio 'Bass Boost'"
echo "    openeq apply ~/my_equalizer_apo_profile.txt"
