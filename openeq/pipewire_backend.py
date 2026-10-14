"""
PipeWire filter-chain backend.

Generates PipeWire filter-chain configurations from EQ parameters
and manages the filter-chain module lifecycle via pw-cli / pw-loopback.
"""

import json
import os
import subprocess
import shutil
from pathlib import Path
from typing import Optional

from .biquad import FilterParams, FilterType, compute_coefficients
from .apo_parser import EQConfig


# default paths
_CONFIG_DIR = Path.home() / ".config" / "openeq"
_PW_FILTER_CONF = _CONFIG_DIR / "eq-filter-chain.conf"
_PW_FILTER_MODULE = "libpipewire-module-filter-chain"


def _ensure_config_dir():
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def generate_filter_chain_config(
    config: EQConfig,
    sample_rate: int = 48000,
    sink_name: str = "openeq_sink",
    description: str = "OpenEQ Equalizer",
) -> str:
    """
    Generate a PipeWire filter-chain configuration from an EQConfig.

    Matches PipeWire's canonical filter-chain design (like sink-eq6.conf):
    Mono graph nodes are linked in series, and PipeWire duplicates
    across audio.channels (stereo FL/FR) automatically.
    """
    nodes = []
    links = []

    # preamp stage using bq_highshelf
    if abs(config.preamp_db) > 0.001:
        nodes.append({
            "type": "builtin",
            "name": "eq_preamp",
            "label": "bq_highshelf",
            "control": {
                "Freq": 0.0,
                "Q": 1.0,
                "Gain": config.preamp_db,
            },
        })

    # filter nodes
    for i, fp in enumerate(config.filters):
        if not fp.enabled:
            continue

        label = _filter_type_to_pw_label(fp.filter_type)
        control = _filter_params_to_pw_control(fp)
        node_name = f"eq_band_{i + 1}"

        nodes.append({
            "type": "builtin",
            "name": node_name,
            "label": label,
            "control": control,
        })

    # link nodes sequentially in series
    for i in range(len(nodes) - 1):
        links.append({
            "output": f"{nodes[i]['name']}:Out",
            "input": f"{nodes[i + 1]['name']}:In",
        })

    # build the full config matching pipewire filter-chain specification
    pw_config = {
        "context.properties": {
            "log.level": 0
        },
        "context.spa-libs": {
            "audio.convert.*": "audioconvert/libspa-audioconvert",
            "support.*": "support/libspa-support",
        },
        "context.modules": [
            {
                "name": _PW_FILTER_MODULE,
                "args": {
                    "node.description": description,
                    "media.name": description,
                    "filter.graph": {
                        "nodes": nodes,
                        "links": links,
                    },
                    "audio.channels": 2,
                    "audio.position": ["FL", "FR"],
                    "capture.props": {
                        "node.name": f"effect_input.{sink_name}",
                        "media.class": "Audio/Sink",
                    },
                    "playback.props": {
                        "node.name": f"effect_output.{sink_name}",
                        "node.passive": True,
                    },
                },
            }
        ],
    }

    return json.dumps(pw_config, indent=2)


def _filter_type_to_pw_label(ft: FilterType) -> str:
    """Map our FilterType to PipeWire built-in biquad label."""
    mapping = {
        FilterType.PK: "bq_peaking",
        FilterType.PEQ: "bq_peaking",
        FilterType.MODAL: "bq_peaking",
        FilterType.LP: "bq_lowpass",
        FilterType.LPQ: "bq_lowpass",
        FilterType.HP: "bq_highpass",
        FilterType.HPQ: "bq_highpass",
        FilterType.BP: "bq_bandpass",
        FilterType.LS: "bq_lowshelf",
        FilterType.HS: "bq_highshelf",
        FilterType.LS6: "bq_lowshelf",
        FilterType.LS12: "bq_lowshelf",
        FilterType.HS6: "bq_highshelf",
        FilterType.HS12: "bq_highshelf",
        FilterType.NO: "bq_notch",
        FilterType.AP: "bq_allpass",
    }
    return mapping.get(ft, "bq_peaking")


def _filter_params_to_pw_control(fp: FilterParams) -> dict:
    """Convert filter parameters to PipeWire biquad control values."""
    control = {"Freq": fp.frequency}

    if fp.filter_type in (
        FilterType.PK, FilterType.PEQ, FilterType.MODAL,
        FilterType.LS, FilterType.HS,
        FilterType.LS6, FilterType.LS12,
        FilterType.HS6, FilterType.HS12,
    ):
        control["Gain"] = fp.gain

    q = fp.effective_q()
    control["Q"] = q

    return control


def write_config(config: EQConfig, sample_rate: int = 48000) -> Path:
    """Write the PipeWire filter-chain config file and return its path."""
    _ensure_config_dir()
    conf_str = generate_filter_chain_config(config, sample_rate)
    _PW_FILTER_CONF.write_text(conf_str, encoding="utf-8")
    return _PW_FILTER_CONF


def apply_eq(config: EQConfig, sample_rate: int = 48000) -> bool:
    """Apply the EQ configuration to PipeWire."""
    remove_eq()

    if not config.filters and abs(config.preamp_db) < 0.001:
        return True

    write_config(config, sample_rate)
    return _apply_via_dropin(config, sample_rate)


def _apply_via_dropin(config: EQConfig, sample_rate: int = 48000) -> bool:
    """Write filter-chain config to pipewire drop-in and restart pipewire."""
    dropin_dir = Path.home() / ".config" / "pipewire" / "filter-chain.conf.d"
    dropin_dir.mkdir(parents=True, exist_ok=True)

    dropin_file = dropin_dir / "openeq-eq.conf"
    conf_str = generate_filter_chain_config(config, sample_rate)
    dropin_file.write_text(conf_str, encoding="utf-8")

    pw_conf_dir = Path.home() / ".config" / "pipewire"
    pw_conf_dir.mkdir(parents=True, exist_ok=True)

    standalone = pw_conf_dir / "openeq-filter-chain.conf"
    standalone.write_text(conf_str, encoding="utf-8")

    try:
        subprocess.run(
            ["systemctl", "--user", "restart", "pipewire.service"],
            capture_output=True, text=True, timeout=10,
        )
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        try:
            subprocess.run(
                ["pw-cli", "load-module", _PW_FILTER_MODULE,
                 str(_PW_FILTER_CONF)],
                capture_output=True, text=True, timeout=5,
            )
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False


def remove_eq() -> bool:
    """Remove any existing OpenEQ filter-chain from PipeWire."""
    dropin_file = (
        Path.home() / ".config" / "pipewire" / "filter-chain.conf.d" / "openeq-eq.conf"
    )
    standalone = Path.home() / ".config" / "pipewire" / "openeq-filter-chain.conf"

    removed = False
    for f in (dropin_file, standalone):
        if f.exists():
            f.unlink()
            removed = True

    return removed


def get_pipewire_info() -> dict:
    """Get PipeWire version and status information."""
    info = {"available": False, "version": "", "sinks": []}

    try:
        result = subprocess.run(
            ["pipewire", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            info["available"] = True
            for line in result.stdout.strip().split("\n"):
                if "libpipewire" in line.lower():
                    info["version"] = line.strip()
                    break
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return info

    # get sinks
    try:
        result = subprocess.run(
            ["wpctl", "status"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            in_sinks = False
            for line in result.stdout.split("\n"):
                if "Sinks:" in line:
                    in_sinks = True
                    continue
                if in_sinks:
                    if not line.strip() or "Sources:" in line or "Filters:" in line:
                        break
                    # parse sink line
                    stripped = line.strip()
                    if stripped and stripped[0].isdigit() or stripped.startswith("*"):
                        info["sinks"].append(stripped.lstrip("* ").strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return info


def get_info() -> dict:
    """Unified interface alias for get_pipewire_info."""
    return get_pipewire_info()


def is_eq_active() -> bool:
    """Check if OpenEQ filter-chain is currently loaded in PipeWire."""
    try:
        result = subprocess.run(
            ["wpctl", "status"],
            capture_output=True, text=True, timeout=5,
        )
        return "openeq" in result.stdout.lower()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
