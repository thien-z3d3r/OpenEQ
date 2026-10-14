"""
Preset management for OpenEQ.

Handles loading, saving, and organizing EQ presets.
Includes built-in presets and supports importing Peace/APO configs.
"""

import json
import os
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from .biquad import FilterParams, FilterType
from .apo_parser import EQConfig, parse_apo_config, config_to_apo_string


_PRESETS_DIR = Path.home() / ".config" / "openeq" / "presets"
_ACTIVE_PRESET_FILE = Path.home() / ".config" / "openeq" / "active_preset.json"


@dataclass
class Preset:
    """A named EQ preset."""
    name: str
    config: EQConfig
    description: str = ""
    author: str = ""
    builtin: bool = False

    def to_dict(self) -> dict:
        filters = []
        for fp in self.config.filters:
            filters.append({
                "type": fp.filter_type.value,
                "frequency": fp.frequency,
                "gain": fp.gain,
                "q": fp.q,
                "bandwidth": fp.bandwidth,
                "enabled": fp.enabled,
            })
        return {
            "name": self.name,
            "description": self.description,
            "author": self.author,
            "preamp_db": self.config.preamp_db,
            "filters": filters,
        }

    @classmethod
    def from_dict(cls, data: dict, builtin: bool = False) -> "Preset":
        filters = []
        for fd in data.get("filters", []):
            ft = FilterType(fd["type"])
            filters.append(FilterParams(
                filter_type=ft,
                frequency=fd["frequency"],
                gain=fd.get("gain", 0.0),
                q=fd.get("q"),
                bandwidth=fd.get("bandwidth"),
                enabled=fd.get("enabled", True),
            ))

        config = EQConfig(
            preamp_db=data.get("preamp_db", 0.0),
            filters=filters,
        )

        return cls(
            name=data["name"],
            config=config,
            description=data.get("description", ""),
            author=data.get("author", ""),
            builtin=builtin,
        )


# built-in presets
BUILTIN_PRESETS = {
    "Flat": Preset(
        name="Flat",
        config=EQConfig(),
        description="No equalization (bypass)",
        builtin=True,
    ),
    "Bass Boost": Preset(
        name="Bass Boost",
        config=EQConfig(
            preamp_db=-3.0,
            filters=[
                FilterParams(FilterType.LS, 105.0, gain=6.0, q=0.71),
                FilterParams(FilterType.PK, 55.0, gain=3.0, q=1.0),
            ],
        ),
        description="Warm bass enhancement",
        builtin=True,
    ),
    "Treble Boost": Preset(
        name="Treble Boost",
        config=EQConfig(
            preamp_db=-3.0,
            filters=[
                FilterParams(FilterType.HS, 4000.0, gain=4.0, q=0.71),
                FilterParams(FilterType.PK, 8000.0, gain=2.0, q=1.5),
            ],
        ),
        description="Bright, detailed highs",
        builtin=True,
    ),
    "V-Shape": Preset(
        name="V-Shape",
        config=EQConfig(
            preamp_db=-4.0,
            filters=[
                FilterParams(FilterType.LS, 100.0, gain=5.0, q=0.71),
                FilterParams(FilterType.PK, 400.0, gain=-2.0, q=0.8),
                FilterParams(FilterType.PK, 1500.0, gain=-3.0, q=0.7),
                FilterParams(FilterType.HS, 6000.0, gain=4.0, q=0.71),
            ],
        ),
        description="Boosted bass and treble, recessed mids",
        builtin=True,
    ),
    "Vocal Clarity": Preset(
        name="Vocal Clarity",
        config=EQConfig(
            preamp_db=-2.0,
            filters=[
                FilterParams(FilterType.HP, 80.0, q=0.71),
                FilterParams(FilterType.PK, 2500.0, gain=3.0, q=1.2),
                FilterParams(FilterType.PK, 5000.0, gain=2.0, q=1.5),
            ],
        ),
        description="Enhanced vocal presence and clarity",
        builtin=True,
    ),
    "Rock": Preset(
        name="Rock",
        config=EQConfig(
            preamp_db=-4.0,
            filters=[
                FilterParams(FilterType.PK, 60.0, gain=4.0, q=1.0),
                FilterParams(FilterType.PK, 250.0, gain=-2.0, q=0.8),
                FilterParams(FilterType.PK, 1000.0, gain=1.0, q=0.7),
                FilterParams(FilterType.PK, 3500.0, gain=3.0, q=1.2),
                FilterParams(FilterType.PK, 8000.0, gain=4.0, q=1.0),
            ],
        ),
        description="Classic rock EQ curve",
        builtin=True,
    ),
    "Jazz": Preset(
        name="Jazz",
        config=EQConfig(
            preamp_db=-2.0,
            filters=[
                FilterParams(FilterType.PK, 80.0, gain=2.0, q=0.8),
                FilterParams(FilterType.PK, 500.0, gain=1.5, q=0.7),
                FilterParams(FilterType.PK, 2000.0, gain=-1.0, q=1.0),
                FilterParams(FilterType.PK, 5000.0, gain=2.0, q=1.5),
                FilterParams(FilterType.HS, 10000.0, gain=1.5, q=0.71),
            ],
        ),
        description="Warm, smooth jazz tone",
        builtin=True,
    ),
    "Electronic": Preset(
        name="Electronic",
        config=EQConfig(
            preamp_db=-5.0,
            filters=[
                FilterParams(FilterType.PK, 40.0, gain=5.0, q=1.0),
                FilterParams(FilterType.PK, 80.0, gain=3.0, q=0.8),
                FilterParams(FilterType.PK, 500.0, gain=-2.0, q=0.7),
                FilterParams(FilterType.PK, 4000.0, gain=3.0, q=1.2),
                FilterParams(FilterType.PK, 10000.0, gain=4.0, q=1.0),
            ],
        ),
        description="Deep bass and sparkling highs for EDM",
        builtin=True,
    ),
    "Loudness": Preset(
        name="Loudness",
        config=EQConfig(
            preamp_db=-6.0,
            filters=[
                FilterParams(FilterType.LS, 80.0, gain=6.0, q=0.71),
                FilterParams(FilterType.PK, 200.0, gain=2.0, q=0.8),
                FilterParams(FilterType.HS, 8000.0, gain=5.0, q=0.71),
            ],
        ),
        description="Fletcher-Munson loudness compensation",
        builtin=True,
    ),
    "Night Mode": Preset(
        name="Night Mode",
        config=EQConfig(
            preamp_db=-2.0,
            filters=[
                FilterParams(FilterType.HP, 40.0, q=0.71),
                FilterParams(FilterType.PK, 80.0, gain=-3.0, q=0.8),
                FilterParams(FilterType.PK, 3000.0, gain=2.0, q=1.0),
                FilterParams(FilterType.LP, 12000.0, q=0.71),
            ],
        ),
        description="Reduced bass and treble for quiet listening",
        builtin=True,
    ),
}


def ensure_presets_dir():
    """Create presets directory if it doesn't exist."""
    _PRESETS_DIR.mkdir(parents=True, exist_ok=True)


def list_presets() -> list[Preset]:
    """List all available presets (built-in + user)."""
    presets = list(BUILTIN_PRESETS.values())

    ensure_presets_dir()
    for f in sorted(_PRESETS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            preset = Preset.from_dict(data, builtin=False)
            presets.append(preset)
        except (json.JSONDecodeError, KeyError, ValueError):
            continue

    return presets


def save_preset(preset: Preset) -> Path:
    """Save a preset to the user presets directory."""
    ensure_presets_dir()
    filename = preset.name.lower().replace(" ", "_") + ".json"
    filepath = _PRESETS_DIR / filename
    filepath.write_text(
        json.dumps(preset.to_dict(), indent=2),
        encoding="utf-8",
    )
    return filepath


def delete_preset(name: str) -> bool:
    """Delete a user preset by name. Cannot delete built-in presets."""
    if name in BUILTIN_PRESETS:
        return False

    ensure_presets_dir()
    filename = name.lower().replace(" ", "_") + ".json"
    filepath = _PRESETS_DIR / filename
    if filepath.exists():
        filepath.unlink()
        return True
    return False


def import_apo_preset(filepath: str, name: Optional[str] = None) -> Preset:
    """Import an Equalizer APO config file as a preset."""
    config = parse_apo_config(filepath)
    if name is None:
        name = Path(filepath).stem.replace("_", " ").title()

    return Preset(
        name=name,
        config=config,
        description=f"Imported from {Path(filepath).name}",
    )


def export_apo_preset(preset: Preset, filepath: str):
    """Export a preset as an Equalizer APO config file."""
    apo_str = config_to_apo_string(preset.config)
    Path(filepath).write_text(apo_str, encoding="utf-8")


def get_active_preset() -> Optional[str]:
    """Get the name of the currently active preset."""
    if _ACTIVE_PRESET_FILE.exists():
        try:
            data = json.loads(_ACTIVE_PRESET_FILE.read_text(encoding="utf-8"))
            return data.get("active_preset")
        except (json.JSONDecodeError, KeyError):
            pass
    return None


def set_active_preset(name: str):
    """Record which preset is currently active."""
    _ACTIVE_PRESET_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ACTIVE_PRESET_FILE.write_text(
        json.dumps({"active_preset": name}),
        encoding="utf-8",
    )


def load_preset_by_name(name: str) -> Optional[Preset]:
    """Load a preset by name (checking built-in first, then user presets)."""
    if name in BUILTIN_PRESETS:
        return BUILTIN_PRESETS[name]

    ensure_presets_dir()
    filename = name.lower().replace(" ", "_") + ".json"
    filepath = _PRESETS_DIR / filename
    if filepath.exists():
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            return Preset.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

    # search by name field
    for f in _PRESETS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("name") == name:
                return Preset.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError):
            continue

    return None
