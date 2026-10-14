# OpenEQ

OpenEQ is a system-wide parametric equalizer for Linux with Equalizer APO / Peace compatibility and integrated AutoEQ headphone profiles. It supports both PipeWire (`filter-chain`) and PulseAudio (`module-ladspa-sink` / `module-equalizer-sink`) with automatic runtime detection.

## Dependencies

Install the required packages for your distribution:

- **Arch Linux**:
  ```bash
  sudo pacman -S --needed python python-gobject gtk4 libadwaita pipewire pipewire-audio wireplumber libpulse swh-plugins
  ```
- **Fedora**:
  ```bash
  sudo dnf install -y python3 python3-gobject gtk4 libadwaita pipewire pipewire-pulseaudio wireplumber pulseaudio-utils swh-plugins
  ```
- **Ubuntu / Debian**:
  ```bash
  sudo apt install -y python3 python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 pipewire wireplumber pulseaudio-utils swh-plugins
  ```
- **openSUSE**:
  ```bash
  sudo zypper install -y python3 python3-gobject gtk4 libadwaita-1-0 pipewire wireplumber pulseaudio-utils ladspa-swh-plugins
  ```

## Installation

### User install (recommended)

```bash
make user-install
```

Or run the install script:

```bash
./scripts/install.sh
```

Ensure `~/.local/bin` is in your `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### System-wide install

```bash
sudo make install
```

## Usage

### Graphical Interface

Launch from your desktop application launcher or run:

```bash
openeq gui
```

Force a specific audio backend:

```bash
openeq gui --backend pipewire
openeq gui --backend pulseaudio
```

### Command-Line Interface

```bash
# Check status and active sound server
openeq status

# List presets
openeq list

# Apply a preset or Equalizer APO file
openeq apply "Bass Boost"
openeq apply "Harman Target"
openeq apply /path/to/eq_config.txt

# Specify backend explicitly
openeq apply --backend pipewire "Bass Boost"
openeq apply --backend pulseaudio "Bass Boost"

# Bypass equalizer
openeq bypass

# Set default backend (auto, pipewire, or pulseaudio)
openeq backend set pipewire
openeq backend set pulseaudio
openeq backend set auto

# Search and apply AutoEQ profiles
openeq autoeq list
openeq autoeq search "HD 600"
openeq autoeq apply "HD 600"
openeq autoeq update
openeq autoeq mode [online|offline]

# Import or export Equalizer APO configs
openeq import /path/to/preset.txt --name "Custom"
openeq export "Rock" ~/exported_rock.txt

# Dump backend configuration
openeq dump-pw "Bass Boost"
openeq dump-pa "Bass Boost"
```

## Equalizer APO File Format

OpenEQ parses standard Equalizer APO configuration files:

```text
Preamp: -6.0 dB
Filter 1: ON  LS  Fc   105 Hz  Gain  5.5 dB  Q 0.71
Filter 2: ON  PK  Fc   200 Hz  Gain  1.0 dB  Q 1.00
Filter 3: ON  PK  Fc  1200 Hz  Gain -2.0 dB  BW Oct 0.50
Filter 4: ON  PK  Fc  3000 Hz  Gain  4.0 dB  Q 1.80
Filter 5: ON  HS  Fc 10000 Hz  Gain  2.0 dB  Q 0.71
```

Supported filter types: `PK`, `PEQ`, `LS`, `HS`, `HP`, `LP`, `BP`, `NO`, `AP`.

## Autostart Service

To restore the active equalizer preset on login:

```bash
systemctl --user enable --now openeq.service
```

## Testing

Run unit tests:

```bash
make test
```

## License

MIT. See [LICENSE](LICENSE).
