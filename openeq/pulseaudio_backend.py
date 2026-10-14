"""
PulseAudio equalizer backend.

Applies EQ curves to PulseAudio using LADSPA multiband filter sink
(module-ladspa-sink with mbeq_1197) or module-equalizer-sink,
managing module lifecycle, sink routing, and stream redirection via pactl.
"""

import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .apo_parser import EQConfig
from .biquad import compute_response_at_frequencies

logger = logging.getLogger(__name__)

# standard 15 center frequencies for mbeq_1197 plugin
MBEQ_FREQUENCIES = [
    50.0, 100.0, 156.0, 220.0, 311.0, 440.0, 622.0, 880.0,
    1250.0, 1750.0, 2500.0, 3500.0, 5000.0, 10000.0, 20000.0,
]

SINK_NAME = "openeq_sink"
SINK_DESCRIPTION = "OpenEQ Equalizer"
LADSPA_PLUGIN_MBEQ = "mbeq_1197"
LADSPA_LABEL_MBEQ = "mbeq"

_CONFIG_DIR = Path.home() / ".config" / "openeq"
_STATE_FILE = _CONFIG_DIR / "pulseaudio_state.json"
_PULSE_CONF_FILE = _CONFIG_DIR / "openeq-pulse.pa"


def _ensure_config_dir() -> Path:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return _CONFIG_DIR


def _run_pactl(args: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess:
    """Run a pactl command with standard timeout and capture."""
    return subprocess.run(
        ["pactl"] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def save_state(state: dict) -> None:
    """Save PulseAudio backend state to JSON."""
    _ensure_config_dir()
    try:
        _STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("Failed to save PulseAudio state: %s", e)


def load_state() -> dict:
    """Load PulseAudio backend state from JSON."""
    if _STATE_FILE.is_file():
        try:
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def clear_state() -> None:
    """Clear stored state file."""
    if _STATE_FILE.exists():
        try:
            _STATE_FILE.unlink()
        except OSError:
            pass


def calculate_mbeq_controls(config: EQConfig, sample_rate: int = 48000) -> list[float]:
    """
    Calculate the 15-band gain controls for the mbeq_1197 LADSPA plugin.

    Computes the exact combined response of all enabled filters + preamp
    evaluated at each of the 15 MBEQ center frequencies.
    Clamps the output within the valid LADSPA gain range [-70.0 dB, +30.0 dB].
    """
    gains = compute_response_at_frequencies(
        filters=config.filters,
        preamp_db=config.preamp_db,
        frequencies=MBEQ_FREQUENCIES,
        sample_rate=sample_rate,
    )
    # clamp to ladspa valid range [-70 db, +30 db]
    clamped = [max(-70.0, min(30.0, round(g, 2))) for g in gains]
    return clamped


def format_controls_string(controls: list[float]) -> str:
    """Format float controls list into a comma-separated string for pactl."""
    return ",".join(f"{c:.2f}" for c in controls)


def generate_pulseaudio_script(
    config: EQConfig,
    master_sink: Optional[str] = None,
    sample_rate: int = 48000,
    sink_name: str = SINK_NAME,
    description: str = SINK_DESCRIPTION,
) -> str:
    """
    Generate a PulseAudio script (.pa format) to load and configure the EQ sink.
    """
    controls = calculate_mbeq_controls(config, sample_rate)
    ctrl_str = format_controls_string(controls)
    master_arg = f"sink_master={master_sink} " if master_sink else ""

    lines = [
        f"# OpenEQ PulseAudio LADSPA Equalizer Configuration",
        f"# Center frequencies: {', '.join(str(int(f)) if f.is_integer() else str(f) for f in MBEQ_FREQUENCIES)} Hz",
        f"# Controls: {ctrl_str}",
        f"load-module module-ladspa-sink sink_name={sink_name} {master_arg}"
        f"plugin={LADSPA_PLUGIN_MBEQ} label={LADSPA_LABEL_MBEQ} control={ctrl_str} "
        f'sink_properties=device.description="{description}"',
        f"set-default-sink {sink_name}",
    ]
    return "\n".join(lines) + "\n"


def get_default_sink() -> Optional[str]:
    """Get the currently configured default PulseAudio sink name."""
    try:
        res = _run_pactl(["get-default-sink"], timeout=2.0)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    try:
        res = _run_pactl(["info"], timeout=3.0)
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                if line.startswith("Default Sink:"):
                    return line.split(":", 1)[1].strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return None


def get_master_sink(exclude_openeq: bool = True) -> Optional[str]:
    """
    Get the hardware/real audio output sink name to use as master.

    If the current default sink is already openeq_sink, returns the previously
    saved master sink or the first non-openeq sink available.
    """
    state = load_state()
    saved_master = state.get("master_sink")

    cur_default = get_default_sink()
    if cur_default and (not exclude_openeq or cur_default != SINK_NAME):
        return cur_default

    if saved_master and saved_master != SINK_NAME:
        return saved_master

    sinks = list_sinks()
    for s in sinks:
        if s != SINK_NAME:
            return s

    return cur_default


def list_sinks() -> list[str]:
    """List all available PulseAudio sink names."""
    sinks = []
    try:
        res = _run_pactl(["list", "sinks", "short"], timeout=3.0)
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    sinks.append(parts[1])
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return sinks


def get_active_module_ids(sink_name: str = SINK_NAME) -> list[int]:
    """
    Find module ID(s) associated with our equalizer sink in PulseAudio.
    """
    module_ids = []

    # inspect loaded modules via pactl list modules
    try:
        res = _run_pactl(["list", "modules"], timeout=4.0)
        if res.returncode == 0:
            current_id = None
            is_openeq_mod = False

            for line in res.stdout.splitlines():
                line_str = line.strip()
                if line_str.startswith("Module #"):
                    if current_id is not None and is_openeq_mod:
                        module_ids.append(current_id)
                    try:
                        current_id = int(line_str.split("#")[1])
                    except (ValueError, IndexError):
                        current_id = None
                    is_openeq_mod = False
                elif current_id is not None:
                    if f"sink_name={sink_name}" in line_str or f'sink_name="{sink_name}"' in line_str:
                        is_openeq_mod = True
                    elif "module-ladspa-sink" in line_str and sink_name in line_str:
                        is_openeq_mod = True
                    elif "module-equalizer-sink" in line_str and sink_name in line_str:
                        is_openeq_mod = True

            if current_id is not None and is_openeq_mod:
                module_ids.append(current_id)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # check saved state if not found
    if not module_ids:
        state = load_state()
        saved_id = state.get("module_id")
        if saved_id is not None:
            module_ids.append(int(saved_id))

    return list(dict.fromkeys(module_ids))


def is_eq_active(sink_name: str = SINK_NAME) -> bool:
    """Check if OpenEQ equalizer sink is currently loaded and active in PulseAudio."""
    sinks = list_sinks()
    if sink_name in sinks:
        return True
    return bool(get_active_module_ids(sink_name))


def get_pulseaudio_info() -> dict:
    """
    Get PulseAudio status, server details, sinks, and EQ active state.
    """
    info = {
        "available": False,
        "server_name": "",
        "is_native_pulse": False,
        "version": "",
        "default_sink": "",
        "master_sink": "",
        "sinks": [],
        "eq_active": False,
    }

    try:
        res = _run_pactl(["info"], timeout=3.0)
        if res.returncode != 0:
            return info

        info["available"] = True
        for line in res.stdout.splitlines():
            line_str = line.strip()
            if line_str.startswith("Server Name:"):
                s_name = line_str.split(":", 1)[1].strip()
                info["server_name"] = s_name
                # determine whether it is native pulseaudio or pipewire pulse layer
                info["is_native_pulse"] = "on PipeWire" not in s_name
            elif line_str.startswith("Server Version:"):
                info["version"] = line_str.split(":", 1)[1].strip()
            elif line_str.startswith("Default Sink:"):
                info["default_sink"] = line_str.split(":", 1)[1].strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return info

    info["sinks"] = list_sinks()
    info["master_sink"] = get_master_sink() or ""
    info["eq_active"] = is_eq_active()

    return info


def get_info() -> dict:
    """Unified interface alias for get_pulseaudio_info."""
    return get_pulseaudio_info()


def _move_sink_inputs(target_sink: str) -> None:
    """Move all active playback streams to target_sink."""
    try:
        res = _run_pactl(["list", "sink-inputs", "short"], timeout=2.0)
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                parts = line.split()
                if parts:
                    input_id = parts[0]
                    _run_pactl(["move-sink-input", input_id, target_sink], timeout=2.0)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


def apply_eq(
    config: EQConfig,
    sample_rate: int = 48000,
    master_sink: Optional[str] = None,
    sink_name: str = SINK_NAME,
) -> bool:
    """Apply EQ configuration to PulseAudio."""
    if not master_sink:
        master_sink = get_master_sink(exclude_openeq=True)

    remove_eq(keep_master_state=True)

    if not config.filters and abs(config.preamp_db) < 0.001:
        return True

    controls = calculate_mbeq_controls(config, sample_rate)
    ctrl_str = format_controls_string(controls)

    cmd = [
        "load-module",
        "module-ladspa-sink",
        f"sink_name={sink_name}",
    ]
    if master_sink:
        cmd.append(f"sink_master={master_sink}")
    cmd.extend([
        f"plugin={LADSPA_PLUGIN_MBEQ}",
        f"label={LADSPA_LABEL_MBEQ}",
        f"control={ctrl_str}",
        f'sink_properties=device.description="{SINK_DESCRIPTION}"',
    ])

    loaded_id = None
    try:
        res = _run_pactl(cmd, timeout=5.0)
        if res.returncode == 0 and res.stdout.strip().isdigit():
            loaded_id = int(res.stdout.strip())
        else:
            logger.info("module-ladspa-sink output: %s %s", res.stdout, res.stderr)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("pactl failed: %s", e)

    if loaded_id is None:
        eq_cmd = [
            "load-module",
            "module-equalizer-sink",
            f"sink_name={sink_name}",
        ]
        if master_sink:
            eq_cmd.append(f"sink_master={master_sink}")
        eq_cmd.append(f'sink_properties=device.description="{SINK_DESCRIPTION}"')

        try:
            res_eq = _run_pactl(eq_cmd, timeout=5.0)
            if res_eq.returncode == 0 and res_eq.stdout.strip().isdigit():
                loaded_id = int(res_eq.stdout.strip())
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    if loaded_id is not None:
        _run_pactl(["set-default-sink", sink_name], timeout=3.0)
        _move_sink_inputs(sink_name)

        state = {
            "module_id": loaded_id,
            "sink_name": sink_name,
            "master_sink": master_sink or "",
            "preamp_db": config.preamp_db,
            "controls": controls,
        }
        save_state(state)

        script_text = generate_pulseaudio_script(config, master_sink=master_sink, sample_rate=sample_rate)
        try:
            _PULSE_CONF_FILE.write_text(script_text, encoding="utf-8")
        except OSError:
            pass

        return True

    script_text = generate_pulseaudio_script(config, master_sink=master_sink, sample_rate=sample_rate)
    try:
        _PULSE_CONF_FILE.write_text(script_text, encoding="utf-8")
    except OSError:
        pass

    return False


def remove_eq(keep_master_state: bool = False, sink_name: str = SINK_NAME) -> bool:
    """Remove OpenEQ equalizer sink and restore original routing in PulseAudio."""
    state = load_state()
    saved_master = state.get("master_sink")
    module_ids = get_active_module_ids(sink_name)

    if saved_master and saved_master != sink_name:
        _run_pactl(["set-default-sink", saved_master], timeout=3.0)
        _move_sink_inputs(saved_master)
    else:
        other_sinks = [s for s in list_sinks() if s != sink_name]
        if other_sinks:
            _run_pactl(["set-default-sink", other_sinks[0]], timeout=3.0)
            _move_sink_inputs(other_sinks[0])

    unloaded = False
    for mid in module_ids:
        try:
            res = _run_pactl(["unload-module", str(mid)], timeout=3.0)
            if res.returncode == 0:
                unloaded = True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    if not keep_master_state:
        clear_state()
    else:
        if saved_master:
            save_state({"master_sink": saved_master})

    return unloaded or (sink_name not in list_sinks())
