"""
AutoEQ integration for OpenEQ.

Provides built-in offline compensation profiles and online search/download
from the Jaakko Pasanen AutoEq repository (Oratory1990, Crinacle, Rtings, etc.),
identical to Peace Equalizer's AutoEQ feature on Windows.
"""

import json
import os
import re
import urllib.request
import urllib.error
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .apo_parser import EQConfig, parse_apo_string
from .biquad import FilterParams, FilterType


_CONFIG_DIR = Path.home() / ".config" / "openeq"
_AUTOEQ_CACHE_DIR = _CONFIG_DIR / "autoeq_cache"
_AUTOEQ_CONFIG_FILE = _CONFIG_DIR / "autoeq_config.json"
_AUTOEQ_INDEX_FILE = _AUTOEQ_CACHE_DIR / "index.json"
_AUTOEQ_BASE_URL = "https://raw.githubusercontent.com/jaakkopasanen/AutoEq/master/results"
_AUTOEQ_INDEX_URL = f"{_AUTOEQ_BASE_URL}/INDEX.md"


@dataclass
class AutoEQEntry:
    """Represents a headphone compensation profile from AutoEQ."""
    model: str
    brand: str
    form: str          # "over-ear" or "in-ear"
    measurer: str      # "oratory1990", "crinacle", "rtings", etc.
    target: str = "Harman"
    apo_text: str = ""
    github_path: str = ""

    def get_config(self) -> EQConfig:
        """Parse and return the EQConfig."""
        if not self.apo_text and self.github_path:
            fetch_profile_for_entry(self)
        if self.apo_text:
            return parse_apo_string(self.apo_text)
        return EQConfig()


# curated offline database of top headphones with exact autoeq parameters
OFFLINE_AUTOEQ_DATABASE: list[AutoEQEntry] = [
    AutoEQEntry(
        model="HD 600",
        brand="Sennheiser",
        form="over-ear",
        measurer="oratory1990",
        target="Harman Over-Ear",
        apo_text="""
Preamp: -6.4 dB
Filter 1: ON  LS       Fc      45 Hz  Gain   6.0 dB  Q 0.70
Filter 2: ON  PK       Fc      30 Hz  Gain  -2.5 dB  Q 1.40
Filter 3: ON  PK       Fc     160 Hz  Gain  -1.8 dB  Q 0.80
Filter 4: ON  PK       Fc    1350 Hz  Gain  -1.5 dB  Q 2.50
Filter 5: ON  PK       Fc    3200 Hz  Gain   3.8 dB  Q 2.20
Filter 6: ON  PK       Fc    5800 Hz  Gain  -3.2 dB  Q 3.50
Filter 7: ON  HS       Fc   10000 Hz  Gain   1.5 dB  Q 0.70
""",
    ),
    AutoEQEntry(
        model="HD 650 / HD 6XX",
        brand="Sennheiser",
        form="over-ear",
        measurer="oratory1990",
        target="Harman Over-Ear",
        apo_text="""
Preamp: -7.0 dB
Filter 1: ON  LS       Fc      50 Hz  Gain   7.0 dB  Q 0.70
Filter 2: ON  PK       Fc     180 Hz  Gain  -2.2 dB  Q 0.85
Filter 3: ON  PK       Fc    1250 Hz  Gain  -1.2 dB  Q 2.00
Filter 4: ON  PK       Fc    3100 Hz  Gain   4.0 dB  Q 2.00
Filter 5: ON  PK       Fc    5600 Hz  Gain  -2.5 dB  Q 3.00
Filter 6: ON  HS       Fc   10000 Hz  Gain   2.0 dB  Q 0.70
""",
    ),
    AutoEQEntry(
        model="HD 560S",
        brand="Sennheiser",
        form="over-ear",
        measurer="oratory1990",
        target="Harman Over-Ear",
        apo_text="""
Preamp: -4.5 dB
Filter 1: ON  LS       Fc      65 Hz  Gain   4.5 dB  Q 0.70
Filter 2: ON  PK       Fc    1300 Hz  Gain  -1.5 dB  Q 1.80
Filter 3: ON  PK       Fc    4400 Hz  Gain  -3.0 dB  Q 3.00
Filter 4: ON  PK       Fc    5800 Hz  Gain  -2.5 dB  Q 3.50
Filter 5: ON  HS       Fc   10000 Hz  Gain   1.0 dB  Q 0.70
""",
    ),
    AutoEQEntry(
        model="ATH-M50x",
        brand="Audio-Technica",
        form="over-ear",
        measurer="oratory1990",
        target="Harman Over-Ear",
        apo_text="""
Preamp: -5.5 dB
Filter 1: ON  PK       Fc     180 Hz  Gain  -4.0 dB  Q 0.80
Filter 2: ON  PK       Fc     320 Hz  Gain   1.5 dB  Q 1.20
Filter 3: ON  PK       Fc    2100 Hz  Gain   3.5 dB  Q 1.50
Filter 4: ON  PK       Fc    4200 Hz  Gain  -3.5 dB  Q 2.50
Filter 5: ON  PK       Fc    9000 Hz  Gain  -4.0 dB  Q 2.00
Filter 6: ON  LS       Fc      70 Hz  Gain   2.0 dB  Q 0.70
""",
    ),
    AutoEQEntry(
        model="WH-1000XM4",
        brand="Sony",
        form="over-ear",
        measurer="oratory1990",
        target="Harman Over-Ear",
        apo_text="""
Preamp: -6.0 dB
Filter 1: ON  PK       Fc     120 Hz  Gain  -4.5 dB  Q 0.70
Filter 2: ON  PK       Fc     650 Hz  Gain   2.0 dB  Q 1.50
Filter 3: ON  PK       Fc    1800 Hz  Gain   3.5 dB  Q 1.20
Filter 4: ON  PK       Fc    3500 Hz  Gain   4.0 dB  Q 1.80
Filter 5: ON  PK       Fc    6800 Hz  Gain  -4.5 dB  Q 3.00
Filter 6: ON  HS       Fc    9500 Hz  Gain   2.5 dB  Q 0.70
""",
    ),
    AutoEQEntry(
        model="WH-1000XM5",
        brand="Sony",
        form="over-ear",
        measurer="oratory1990",
        target="Harman Over-Ear",
        apo_text="""
Preamp: -5.0 dB
Filter 1: ON  PK       Fc     140 Hz  Gain  -4.0 dB  Q 0.75
Filter 2: ON  PK       Fc     800 Hz  Gain   1.8 dB  Q 1.40
Filter 3: ON  PK       Fc    2500 Hz  Gain   3.0 dB  Q 1.50
Filter 4: ON  PK       Fc    5200 Hz  Gain  -3.0 dB  Q 2.50
Filter 5: ON  HS       Fc   10000 Hz  Gain   2.0 dB  Q 0.70
""",
    ),
    AutoEQEntry(
        model="DT 770 Pro (80 Ohm)",
        brand="Beyerdynamic",
        form="over-ear",
        measurer="oratory1990",
        target="Harman Over-Ear",
        apo_text="""
Preamp: -6.0 dB
Filter 1: ON  PK       Fc     110 Hz  Gain  -2.5 dB  Q 0.80
Filter 2: ON  PK       Fc    3800 Hz  Gain   3.0 dB  Q 1.50
Filter 3: ON  PK       Fc    5800 Hz  Gain  -5.5 dB  Q 3.50
Filter 4: ON  PK       Fc    8200 Hz  Gain  -4.0 dB  Q 3.00
Filter 5: ON  LS       Fc      60 Hz  Gain   3.0 dB  Q 0.70
""",
    ),
    AutoEQEntry(
        model="DT 990 Pro (250 Ohm)",
        brand="Beyerdynamic",
        form="over-ear",
        measurer="oratory1990",
        target="Harman Over-Ear",
        apo_text="""
Preamp: -7.5 dB
Filter 1: ON  LS       Fc      80 Hz  Gain   5.0 dB  Q 0.70
Filter 2: ON  PK       Fc     600 Hz  Gain  -1.5 dB  Q 1.00
Filter 3: ON  PK       Fc    4200 Hz  Gain   2.5 dB  Q 1.80
Filter 4: ON  PK       Fc    5900 Hz  Gain  -7.0 dB  Q 4.00
Filter 5: ON  PK       Fc    8500 Hz  Gain  -6.5 dB  Q 3.00
""",
    ),
    AutoEQEntry(
        model="Sundara (2020)",
        brand="HiFiMan",
        form="over-ear",
        measurer="oratory1990",
        target="Harman Over-Ear",
        apo_text="""
Preamp: -6.5 dB
Filter 1: ON  LS       Fc      75 Hz  Gain   6.0 dB  Q 0.70
Filter 2: ON  PK       Fc     700 Hz  Gain  -1.0 dB  Q 1.50
Filter 3: ON  PK       Fc    2100 Hz  Gain   3.5 dB  Q 1.80
Filter 4: ON  PK       Fc    6200 Hz  Gain  -3.0 dB  Q 3.00
Filter 5: ON  PK       Fc    9000 Hz  Gain  -2.0 dB  Q 2.50
""",
    ),
    AutoEQEntry(
        model="Edition XS",
        brand="HiFiMan",
        form="over-ear",
        measurer="oratory1990",
        target="Harman Over-Ear",
        apo_text="""
Preamp: -5.5 dB
Filter 1: ON  LS       Fc      65 Hz  Gain   5.0 dB  Q 0.70
Filter 2: ON  PK       Fc    1800 Hz  Gain   2.5 dB  Q 1.50
Filter 3: ON  PK       Fc    3200 Hz  Gain  -1.5 dB  Q 2.00
Filter 4: ON  PK       Fc    6000 Hz  Gain  -2.5 dB  Q 3.00
Filter 5: ON  HS       Fc   11000 Hz  Gain   1.5 dB  Q 0.70
""",
    ),
    AutoEQEntry(
        model="AirPods Pro (2nd Gen)",
        brand="Apple",
        form="in-ear",
        measurer="crinacle",
        target="Harman In-Ear",
        apo_text="""
Preamp: -3.5 dB
Filter 1: ON  PK       Fc     180 Hz  Gain  -1.5 dB  Q 1.00
Filter 2: ON  PK       Fc    2800 Hz  Gain   2.0 dB  Q 1.50
Filter 3: ON  PK       Fc    6200 Hz  Gain  -2.5 dB  Q 2.50
Filter 4: ON  HS       Fc   10000 Hz  Gain   2.0 dB  Q 0.70
""",
    ),
    AutoEQEntry(
        model="AirPods Max",
        brand="Apple",
        form="over-ear",
        measurer="oratory1990",
        target="Harman Over-Ear",
        apo_text="""
Preamp: -4.0 dB
Filter 1: ON  PK       Fc     140 Hz  Gain  -2.0 dB  Q 0.80
Filter 2: ON  PK       Fc    1200 Hz  Gain   1.5 dB  Q 1.80
Filter 3: ON  PK       Fc    4200 Hz  Gain   3.0 dB  Q 1.60
Filter 4: ON  PK       Fc    6500 Hz  Gain  -3.0 dB  Q 3.00
Filter 5: ON  HS       Fc   10500 Hz  Gain   1.5 dB  Q 0.70
""",
    ),
    AutoEQEntry(
        model="Blessing 2",
        brand="Moondrop",
        form="in-ear",
        measurer="crinacle",
        target="Harman In-Ear",
        apo_text="""
Preamp: -4.5 dB
Filter 1: ON  LS       Fc     105 Hz  Gain   4.0 dB  Q 0.70
Filter 2: ON  PK       Fc    1200 Hz  Gain  -1.5 dB  Q 1.50
Filter 3: ON  PK       Fc    6000 Hz  Gain  -3.0 dB  Q 2.50
Filter 4: ON  HS       Fc   10000 Hz  Gain   2.0 dB  Q 0.70
""",
    ),
    AutoEQEntry(
        model="Aria / Chu",
        brand="Moondrop",
        form="in-ear",
        measurer="crinacle",
        target="Harman In-Ear",
        apo_text="""
Preamp: -3.0 dB
Filter 1: ON  PK       Fc     200 Hz  Gain  -1.5 dB  Q 1.00
Filter 2: ON  PK       Fc    3500 Hz  Gain   1.5 dB  Q 1.50
Filter 3: ON  PK       Fc    6200 Hz  Gain  -2.5 dB  Q 2.50
Filter 4: ON  HS       Fc    9000 Hz  Gain   2.0 dB  Q 0.70
""",
    ),
    AutoEQEntry(
        model="K371",
        brand="AKG",
        form="over-ear",
        measurer="oratory1990",
        target="Harman Over-Ear",
        apo_text="""
Preamp: -2.5 dB
Filter 1: ON  PK       Fc      80 Hz  Gain  -1.5 dB  Q 1.00
Filter 2: ON  PK       Fc     400 Hz  Gain   1.2 dB  Q 1.40
Filter 3: ON  PK       Fc    3800 Hz  Gain  -2.0 dB  Q 2.00
Filter 4: ON  HS       Fc    9000 Hz  Gain   1.5 dB  Q 0.70
""",
    ),
    AutoEQEntry(
        model="Fidelio X2HR",
        brand="Philips",
        form="over-ear",
        measurer="oratory1990",
        target="Harman Over-Ear",
        apo_text="""
Preamp: -5.0 dB
Filter 1: ON  PK       Fc     120 Hz  Gain  -3.0 dB  Q 0.80
Filter 2: ON  PK       Fc    1800 Hz  Gain   2.5 dB  Q 1.40
Filter 3: ON  PK       Fc    4800 Hz  Gain  -4.0 dB  Q 2.50
Filter 4: ON  PK       Fc    8200 Hz  Gain  -3.5 dB  Q 3.00
Filter 5: ON  LS       Fc      60 Hz  Gain   3.5 dB  Q 0.70
""",
    ),
    AutoEQEntry(
        model="QuietComfort 35 II / 45",
        brand="Bose",
        form="over-ear",
        measurer="oratory1990",
        target="Harman Over-Ear",
        apo_text="""
Preamp: -4.0 dB
Filter 1: ON  PK       Fc     160 Hz  Gain  -2.5 dB  Q 0.90
Filter 2: ON  PK       Fc    1400 Hz  Gain   2.0 dB  Q 1.50
Filter 3: ON  PK       Fc    4200 Hz  Gain   2.5 dB  Q 1.80
Filter 4: ON  PK       Fc    7000 Hz  Gain  -3.0 dB  Q 2.50
Filter 5: ON  HS       Fc   10000 Hz  Gain   1.5 dB  Q 0.70
""",
    ),
    AutoEQEntry(
        model="Cloud II",
        brand="HyperX",
        form="over-ear",
        measurer="rtings",
        target="Harman Over-Ear",
        apo_text="""
Preamp: -4.5 dB
Filter 1: ON  PK       Fc     150 Hz  Gain  -3.0 dB  Q 0.80
Filter 2: ON  PK       Fc     800 Hz  Gain   1.5 dB  Q 1.20
Filter 3: ON  PK       Fc    3500 Hz  Gain   3.5 dB  Q 1.50
Filter 4: ON  PK       Fc    6500 Hz  Gain  -3.5 dB  Q 2.50
Filter 5: ON  LS       Fc      65 Hz  Gain   3.0 dB  Q 0.70
""",
    ),
    AutoEQEntry(
        model="Arctis Nova Pro",
        brand="SteelSeries",
        form="over-ear",
        measurer="rtings",
        target="Harman Over-Ear",
        apo_text="""
Preamp: -4.0 dB
Filter 1: ON  PK       Fc     220 Hz  Gain  -2.5 dB  Q 0.90
Filter 2: ON  PK       Fc    1200 Hz  Gain   1.8 dB  Q 1.40
Filter 3: ON  PK       Fc    3800 Hz  Gain   2.5 dB  Q 1.60
Filter 4: ON  PK       Fc    6800 Hz  Gain  -3.0 dB  Q 2.50
Filter 5: ON  LS       Fc      70 Hz  Gain   3.0 dB  Q 0.70
""",
    ),
    AutoEQEntry(
        model="LCD-X",
        brand="Audeze",
        form="over-ear",
        measurer="oratory1990",
        target="Harman Over-Ear",
        apo_text="""
Preamp: -7.0 dB
Filter 1: ON  LS       Fc      60 Hz  Gain   4.0 dB  Q 0.70
Filter 2: ON  PK       Fc     750 Hz  Gain  -1.5 dB  Q 1.50
Filter 3: ON  PK       Fc    3500 Hz  Gain   6.5 dB  Q 1.80
Filter 4: ON  PK       Fc    5800 Hz  Gain  -3.0 dB  Q 3.00
Filter 5: ON  HS       Fc    9000 Hz  Gain   2.0 dB  Q 0.70
""",
    ),
]


_KNOWN_MULTI_WORD_BRANDS = [
    "Audio-Technica", "Audio Technica", "Bang & Olufsen", "Bowers & Wilkins",
    "Bowers and Wilkins", "Dan Clark Audio", "Campfire Audio", "Final Audio",
    "Kiwi Ears", "Empire Ears", "64 Audio", "Tin HiFi", "7Hz", "Tangzu",
    "Drop + Sennheiser", "Drop + Dan Clark Audio", "Drop + Hifiman",
    "Drop + Focal", "Drop + Beyerdynamic", "Drop + THX", "Drop + JVC",
    "Drop + EPOS", "Drop + MrSpeakers", "Drop + Koss", "Audeze LCD",
    "Ultimate Ears", "Custom Art", "Fearless Audio", "Noble Audio",
    "Master & Dynamic", "Periodic Audio", "Kinera Imperial", "Unique Melody",
    "Moondrop", "Letshuoer", "Thieaudio", "SeeAudio", "Tanchjim", "Sennheiser",
    "Beyerdynamic", "HiFiMAN", "Hifiman", "Audeze", "Sony", "Apple", "Bose",
    "AKG", "Focal", "Shure", "Grado", "Koss", "Philips",
]


def _parse_brand_model(name: str) -> tuple[str, str]:
    """Extract brand and model from a headphone name string."""
    name = name.strip()
    for b in _KNOWN_MULTI_WORD_BRANDS:
        if name.lower().startswith(b.lower()):
            model = name[len(b):].strip()
            return b, model or name
    parts = name.split(None, 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return parts[0], parts[0]


def parse_autoeq_index_md(content: str) -> list[AutoEQEntry]:
    """
    Parse Jaakko Pasanen AutoEq results INDEX.md into AutoEQEntry objects.
    Lines have formats such as:
      - [1Custom SA02](./crinacle/711%20in-ear/1Custom%20SA02) by crinacle on 711
      - [HD 600](./oratory1990/over-ear/Sennheiser%20HD%20600) by oratory1990
    """
    pattern = re.compile(r"^-\s+\[(.*?)\]\(\./(.*?)\)(?:\s+by\s+(.*?)(?:\s+on\s+(.*))?)?$")
    entries: list[AutoEQEntry] = []

    for line in content.splitlines():
        line = line.strip()
        m = pattern.match(line)
        if not m:
            continue
        name, rel_path, measurer_txt, rig_txt = m.groups()
        brand, model = _parse_brand_model(name)

        parts = rel_path.split("/")
        measurer_name = (measurer_txt or (parts[0] if len(parts) > 0 else "AutoEq")).strip()

        form_str = "over-ear"
        if len(parts) >= 2:
            p_form = parts[1].lower()
            if "in-ear" in p_form:
                form_str = "in-ear"
            elif "earbud" in p_form:
                form_str = "earbud"
            elif "over-ear" in p_form:
                form_str = "over-ear"

        folder = parts[-1]
        github_url = f"{_AUTOEQ_BASE_URL}/{rel_path}/{folder}%20ParametricEQ.txt"

        entries.append(
            AutoEQEntry(
                model=model,
                brand=brand,
                form=form_str,
                measurer=measurer_name,
                target="Harman",
                apo_text="",
                github_path=github_url,
            )
        )

    return entries


def ensure_autoeq_cache_dir():
    """Ensure AutoEQ configuration and cache directories exist."""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _AUTOEQ_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_autoeq_mode() -> str:
    """Return current AutoEQ mode: 'online' (default) or 'offline'."""
    ensure_autoeq_cache_dir()
    if _AUTOEQ_CONFIG_FILE.exists():
        try:
            data = json.loads(_AUTOEQ_CONFIG_FILE.read_text(encoding="utf-8"))
            return data.get("mode", "online")
        except (json.JSONDecodeError, OSError):
            pass
    return "online"


def set_autoeq_mode(mode: str) -> str:
    """Set AutoEQ mode to 'online' or 'offline' and save to config."""
    ensure_autoeq_cache_dir()
    mode = mode.lower().strip()
    if mode not in ("online", "offline"):
        raise ValueError("AutoEQ mode must be 'online' or 'offline'")

    config_data = {}
    if _AUTOEQ_CONFIG_FILE.exists():
        try:
            config_data = json.loads(_AUTOEQ_CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            config_data = {}

    config_data["mode"] = mode
    _AUTOEQ_CONFIG_FILE.write_text(json.dumps(config_data, indent=2), encoding="utf-8")
    return mode


def is_online_mode() -> bool:
    """Check if AutoEQ is operating in online mode."""
    return get_autoeq_mode() == "online"


def get_autoeq_status() -> dict:
    """Return current AutoEQ status: mode, entry count, last updated timestamp."""
    mode = get_autoeq_mode()
    last_updated = None
    entry_count = len(OFFLINE_AUTOEQ_DATABASE)
    if _AUTOEQ_CONFIG_FILE.exists():
        try:
            data = json.loads(_AUTOEQ_CONFIG_FILE.read_text(encoding="utf-8"))
            last_updated = data.get("last_updated")
        except (json.JSONDecodeError, OSError):
            pass
    if _AUTOEQ_INDEX_FILE.exists():
        try:
            index_data = json.loads(_AUTOEQ_INDEX_FILE.read_text(encoding="utf-8"))
            entry_count = len(index_data)
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "mode": mode,
        "online": mode == "online",
        "entry_count": entry_count,
        "last_updated": last_updated,
        "cached_index_exists": _AUTOEQ_INDEX_FILE.exists(),
    }


_INDEX_ENTRIES_CACHE: Optional[list[AutoEQEntry]] = None


def update_autoeq_database(force: bool = False, timeout: int = 15) -> tuple[int, str]:
    """
    Download and update the AutoEQ online database index directly from GitHub.
    Saves the parsed index locally for instant searches.
    Returns (entry_count, message).
    """
    global _INDEX_ENTRIES_CACHE
    ensure_autoeq_cache_dir()
    try:
        req = urllib.request.Request(
            _AUTOEQ_INDEX_URL,
            headers={"User-Agent": "OpenEQ-Linux-Audio-Client"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content = response.read().decode("utf-8")

        entries = parse_autoeq_index_md(content)
        if not entries:
            return 0, "No entries found in AutoEQ index."

        raw_list = [
            {
                "model": e.model,
                "brand": e.brand,
                "form": e.form,
                "measurer": e.measurer,
                "target": e.target,
                "github_path": e.github_path,
            }
            for e in entries
        ]
        _AUTOEQ_INDEX_FILE.write_text(json.dumps(raw_list), encoding="utf-8")
        _INDEX_ENTRIES_CACHE = entries

        now_str = datetime.now(timezone.utc).isoformat()
        config_data = {}
        if _AUTOEQ_CONFIG_FILE.exists():
            try:
                config_data = json.loads(_AUTOEQ_CONFIG_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                config_data = {}
        config_data["mode"] = config_data.get("mode", "online")
        config_data["last_updated"] = now_str
        config_data["entry_count"] = len(entries)
        _AUTOEQ_CONFIG_FILE.write_text(json.dumps(config_data, indent=2), encoding="utf-8")

        return len(entries), f"Successfully updated AutoEQ database with {len(entries)} profiles."
    except Exception as exc:
        return 0, f"Failed to update AutoEQ database: {exc}"


def load_online_index(auto_fetch: bool = True) -> list[AutoEQEntry]:
    """
    Load cached online index entries.
    If the index file does not exist and auto_fetch is True in online mode,
    fetches and updates the database immediately.
    """
    global _INDEX_ENTRIES_CACHE
    if _INDEX_ENTRIES_CACHE is not None:
        return _INDEX_ENTRIES_CACHE

    ensure_autoeq_cache_dir()
    if not _AUTOEQ_INDEX_FILE.exists():
        if auto_fetch and is_online_mode():
            count, _ = update_autoeq_database()
            if count > 0 and _INDEX_ENTRIES_CACHE is not None:
                return _INDEX_ENTRIES_CACHE
        return []

    try:
        raw_list = json.loads(_AUTOEQ_INDEX_FILE.read_text(encoding="utf-8"))
        entries = [
            AutoEQEntry(
                model=item.get("model", ""),
                brand=item.get("brand", ""),
                form=item.get("form", "over-ear"),
                measurer=item.get("measurer", "AutoEq"),
                target=item.get("target", "Harman"),
                apo_text=item.get("apo_text", ""),
                github_path=item.get("github_path", ""),
            )
            for item in raw_list
        ]
        _INDEX_ENTRIES_CACHE = entries
        return entries
    except (json.JSONDecodeError, OSError):
        return []


def fetch_profile_for_entry(entry: AutoEQEntry, timeout: int = 6) -> bool:
    """Fetch ParametricEQ text from GitHub for an entry and cache it locally."""
    if entry.apo_text:
        return True

    ensure_autoeq_cache_dir()
    slug = f"{entry.brand}_{entry.model}_{entry.measurer}".lower().replace(" ", "_").replace("/", "_")
    cache_file = _AUTOEQ_CACHE_DIR / f"{slug}.json"

    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            if data.get("apo_text"):
                entry.apo_text = data["apo_text"]
                return True
        except (json.JSONDecodeError, OSError):
            pass

    url = entry.github_path
    if not url:
        safe_name = urllib.parse.quote(f"{entry.brand} {entry.model}".strip())
        url = f"{_AUTOEQ_BASE_URL}/{entry.measurer}/{entry.form}/{safe_name}/{safe_name}%20ParametricEQ.txt"

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "OpenEQ-Linux-Audio-Client"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            text = response.read().decode("utf-8")

        entry.apo_text = text
        entry.github_path = url

        cache_data = {
            "model": entry.model,
            "brand": entry.brand,
            "form": entry.form,
            "measurer": entry.measurer,
            "target": entry.target,
            "apo_text": entry.apo_text,
            "github_path": entry.github_path,
        }
        cache_file.write_text(json.dumps(cache_data, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def search_autoeq(query: str, online: Optional[bool] = None) -> list[AutoEQEntry]:
    """
    Search the AutoEQ database by model, brand, or measurer.

    If online is True (or online mode is enabled), searches the online AutoEQ
    database (8,800+ models) along with offline and cached profiles.
    Case-insensitive search across all fields.
    """
    q = query.lower().strip()
    if online is None:
        online = is_online_mode()

    results: list[tuple[int, AutoEQEntry]] = []
    seen: set[tuple[str, str, str, str]] = set()

    def add_entry(e: AutoEQEntry, score_boost: int = 0):
        key = (e.brand.lower(), e.model.lower(), e.measurer.lower(), e.form.lower())
        if key not in seen:
            seen.add(key)
            full_text = f"{e.brand} {e.model} {e.form} {e.measurer}".lower()
            if not q or q in full_text:
                score = score_boost
                model_low = e.model.lower()
                full_low = f"{e.brand} {e.model}".lower()
                if model_low == q or full_low == q:
                    score += 100
                elif model_low.startswith(q) or full_low.startswith(q):
                    score += 50
                elif q in model_low:
                    score += 25
                elif q in e.brand.lower():
                    score += 10
                results.append((score, e))

    # offline curated database
    for entry in OFFLINE_AUTOEQ_DATABASE:
        add_entry(entry, score_boost=20)

    # local cache directory
    ensure_autoeq_cache_dir()
    for f in _AUTOEQ_CACHE_DIR.glob("*.json"):
        if f.name == "index.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            e = AutoEQEntry(
                model=data.get("model", f.stem),
                brand=data.get("brand", "Custom"),
                form=data.get("form", "over-ear"),
                measurer=data.get("measurer", "AutoEq"),
                target=data.get("target", "Harman"),
                apo_text=data.get("apo_text", ""),
                github_path=data.get("github_path", ""),
            )
            add_entry(e, score_boost=15)
        except (json.JSONDecodeError, KeyError, OSError):
            continue

    # online index database (if online mode enabled)
    if online:
        index_entries = load_online_index(auto_fetch=True)
        for e in index_entries:
            add_entry(e, score_boost=0)

    # sort by score descending, then brand, model
    results.sort(key=lambda item: (-item[0], item[1].brand, item[1].model))
    return [item[1] for item in results]


def fetch_from_github(
    headphone_name: str,
    measurer: Optional[str] = None,
    form: Optional[str] = None,
) -> Optional[AutoEQEntry]:
    """
    Fetch an AutoEQ parametric EQ file directly from the GitHub repository.

    Searches online index for exact or fuzzy match first.
    Caches the downloaded file locally for instant offline reuse.
    """
    ensure_autoeq_cache_dir()
    q = headphone_name.lower().strip()

    # search in online index
    online_entries = load_online_index(auto_fetch=True)
    candidate: Optional[AutoEQEntry] = None
    for e in online_entries:
        full = f"{e.brand} {e.model}".lower()
        if (q == full or q == e.model.lower() or q in full) and (
            measurer is None or e.measurer.lower() == measurer.lower()
        ) and (
            form is None or e.form.lower() == form.lower()
        ):
            candidate = e
            break

    if candidate:
        if fetch_profile_for_entry(candidate):
            return candidate

    # fall back to direct path construction
    measurer_val = measurer or "oratory1990"
    form_val = form or "over-ear"
    safe_name = urllib.parse.quote(headphone_name)
    url = f"{_AUTOEQ_BASE_URL}/{measurer_val}/{form_val}/{safe_name}/{safe_name}%20ParametricEQ.txt"

    entry = AutoEQEntry(
        model=headphone_name,
        brand=headphone_name.split()[0] if headphone_name else "Unknown",
        form=form_val,
        measurer=measurer_val,
        target="Harman",
        github_path=url,
    )
    if fetch_profile_for_entry(entry):
        return entry
    return None
