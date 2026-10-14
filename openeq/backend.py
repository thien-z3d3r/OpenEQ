"""
Unified audio backend router for OpenEQ.

Dispatches EQ operations to PipeWire (via libpipewire-module-filter-chain)
or PulseAudio (via module-ladspa-sink / pactl) based on runtime detection
or explicit user configuration.
"""

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .apo_parser import EQConfig
from . import pipewire_backend
from . import pulseaudio_backend

logger = logging.getLogger(__name__)

BACKEND_PIPEWIRE = "pipewire"
BACKEND_PULSEAUDIO = "pulseaudio"
BACKEND_AUTO = "auto"

VALID_BACKENDS = {BACKEND_PIPEWIRE, BACKEND_PULSEAUDIO, BACKEND_AUTO}
BACKEND_ALIASES = {
    "pw": BACKEND_PIPEWIRE,
    "pipewire": BACKEND_PIPEWIRE,
    "pa": BACKEND_PULSEAUDIO,
    "pulse": BACKEND_PULSEAUDIO,
    "pulseaudio": BACKEND_PULSEAUDIO,
    "auto": BACKEND_AUTO,
}

_CONFIG_DIR = Path.home() / ".config" / "openeq"
_SETTINGS_FILE = _CONFIG_DIR / "config.json"


def _canonicalize_backend_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    cleaned = name.strip().lower()
    return BACKEND_ALIASES.get(cleaned, cleaned)


def get_backend_preference() -> Optional[str]:
    """Retrieve saved backend preference from ~/.config/openeq/config.json."""
    if _SETTINGS_FILE.is_file():
        try:
            data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            backend = data.get("backend")
            return _canonicalize_backend_name(backend)
        except (json.JSONDecodeError, OSError):
            return None
    return None


def save_backend_preference(backend: str) -> None:
    """Save backend preference to ~/.config/openeq/config.json."""
    canonical = _canonicalize_backend_name(backend) or BACKEND_AUTO
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    settings = {}
    if _SETTINGS_FILE.is_file():
        try:
            settings = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    settings["backend"] = canonical
    try:
        _SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("Failed to save backend setting: %s", e)


def detect_backend() -> str:
    """
    Detect whether the host system is actively running PipeWire or native PulseAudio.

    Detection strategy:
    1. Query pactl info (standard audio server status).
       - If Server Name contains "on PipeWire", PipeWire is managing audio.
       - If Server Name indicates native PulseAudio (and not PipeWire), PulseAudio is used.
    2. Check PipeWire daemon (pipewire process or pw-cli).
    3. Check PulseAudio daemon (pulseaudio process or pulseaudio --check).
    4. Default to PipeWire if pipewire executable is present, else PulseAudio.
    """
    try:
        res = subprocess.run(
            ["pactl", "info"],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if res.returncode == 0:
            stdout = res.stdout
            for line in stdout.splitlines():
                if line.startswith("Server Name:"):
                    s_name = line.split(":", 1)[1].strip()
                    if "on PipeWire" in s_name or "pipewire" in s_name.lower():
                        return BACKEND_PIPEWIRE
                    if "pulseaudio" in s_name.lower():
                        return BACKEND_PULSEAUDIO
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    try:
        res = subprocess.run(
            ["pw-cli", "info", "0"],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if res.returncode == 0:
            return BACKEND_PIPEWIRE
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    try:
        res = subprocess.run(
            ["pulseaudio", "--check"],
            capture_output=True,
            timeout=2.0,
        )
        if res.returncode == 0:
            return BACKEND_PULSEAUDIO
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    if shutil.which("pipewire"):
        return BACKEND_PIPEWIRE
    if shutil.which("pulseaudio") or shutil.which("pactl"):
        return BACKEND_PULSEAUDIO

    return BACKEND_PIPEWIRE


def get_active_backend_name(override: Optional[str] = None) -> str:
    """
    Determine the active backend name in order of precedence:
    1. Explicit caller override
    2. OPENEQ_BACKEND environment variable
    3. Stored setting in ~/.config/openeq/config.json
    4. Auto-detection
    """
    if override:
        canon = _canonicalize_backend_name(override)
        if canon and canon != BACKEND_AUTO:
            return canon

    env_val = _canonicalize_backend_name(os.environ.get("OPENEQ_BACKEND"))
    if env_val and env_val != BACKEND_AUTO:
        return env_val

    pref_val = get_backend_preference()
    if pref_val and pref_val != BACKEND_AUTO:
        return pref_val

    return detect_backend()


def get_backend(name: Optional[str] = None):
    """
    Retrieve the backend implementation module for the active or requested backend.
    """
    backend_name = get_active_backend_name(name)
    if backend_name == BACKEND_PULSEAUDIO:
        return pulseaudio_backend
    return pipewire_backend


def detect_available_backends() -> dict[str, bool]:
    """Check availability of both PipeWire and PulseAudio on this system."""
    pw_avail = False
    pa_avail = False

    # check pipewire
    try:
        pw_info = pipewire_backend.get_pipewire_info()
        pw_avail = bool(pw_info.get("available"))
    except Exception:
        pw_avail = bool(shutil.which("pipewire"))

    # check pulseaudio
    try:
        pa_info = pulseaudio_backend.get_pulseaudio_info()
        pa_avail = bool(pa_info.get("available"))
    except Exception:
        pa_avail = bool(shutil.which("pactl"))

    return {
        BACKEND_PIPEWIRE: pw_avail,
        BACKEND_PULSEAUDIO: pa_avail,
    }


def get_system_audio_info(backend_name: Optional[str] = None) -> dict:
    """
    Get consolidated audio status across both backends and current active routing.
    """
    active_name = get_active_backend_name(backend_name)
    backend_mod = get_backend(active_name)
    available_map = detect_available_backends()

    info = {
        "active_backend": active_name,
        "configured_backend": get_backend_preference() or "auto",
        "detected_backend": detect_backend(),
        "pipewire_available": available_map.get(BACKEND_PIPEWIRE, False),
        "pulseaudio_available": available_map.get(BACKEND_PULSEAUDIO, False),
        "available": False,
        "server_name": "",
        "version": "",
        "eq_active": False,
        "sinks": [],
        "default_sink": "",
    }

    try:
        b_info = backend_mod.get_info()
        info["available"] = b_info.get("available", False)
        info["server_name"] = b_info.get("server_name", "")
        info["version"] = b_info.get("version", "")
        info["sinks"] = b_info.get("sinks", [])
        info["default_sink"] = b_info.get("default_sink", "")
        info["eq_active"] = backend_mod.is_eq_active()
    except Exception as e:
        logger.warning("Failed to query backend info: %s", e)

    return info


def apply_eq(
    config: EQConfig,
    sample_rate: int = 48000,
    backend: Optional[str] = None,
) -> bool:
    """
    Apply EQ configuration through the active or specified audio backend.
    """
    backend_mod = get_backend(backend)
    return backend_mod.apply_eq(config, sample_rate=sample_rate)


def remove_eq(backend: Optional[str] = None) -> bool:
    """
    Bypass/remove the EQ configuration across the active or specified backend.
    Also cleans up both backends if auto/unspecified to avoid lingering filters.
    """
    if backend:
        backend_mod = get_backend(backend)
        return backend_mod.remove_eq()

    # clean up inactive backend if orphaned
    active_backend = get_backend()
    res1 = active_backend.remove_eq()

    other_name = BACKEND_PULSEAUDIO if get_active_backend_name() == BACKEND_PIPEWIRE else BACKEND_PIPEWIRE
    other_backend = get_backend(other_name)
    try:
        if other_backend.is_eq_active():
            other_backend.remove_eq()
    except Exception:
        pass

    return res1


def is_eq_active(backend: Optional[str] = None) -> bool:
    """Check if EQ is active on the selected or detected backend."""
    if backend:
        return get_backend(backend).is_eq_active()
    return pipewire_backend.is_eq_active() or pulseaudio_backend.is_eq_active()
