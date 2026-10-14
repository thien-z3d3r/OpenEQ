"""
Equalizer APO configuration file parser.

Parses the text-based config format used by Equalizer APO and Peace,
extracting Preamp, Filter, GraphicEQ, and Include directives.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .biquad import FilterParams, FilterType


@dataclass
class EQConfig:
    """Represents a parsed Equalizer APO configuration."""
    preamp_db: float = 0.0
    filters: list[FilterParams] = field(default_factory=list)
    graphic_eq: Optional[list[tuple[float, float]]] = None  # [(freq, gain_db)]
    source_file: Optional[str] = None

    def clear(self):
        self.preamp_db = 0.0
        self.filters.clear()
        self.graphic_eq = None


# map apo filter type strings to filtertype enum
_FILTER_TYPE_MAP = {
    "PK": FilterType.PK,
    "PEQ": FilterType.PEQ,
    "MODAL": FilterType.MODAL,
    "LP": FilterType.LP,
    "LPQ": FilterType.LPQ,
    "HP": FilterType.HP,
    "HPQ": FilterType.HPQ,
    "BP": FilterType.BP,
    "LS": FilterType.LS,
    "LSC": FilterType.LS,
    "HS": FilterType.HS,
    "HSC": FilterType.HS,
    "LS 6DB": FilterType.LS6,
    "LS 12DB": FilterType.LS12,
    "HS 6DB": FilterType.HS6,
    "HS 12DB": FilterType.HS12,
    "NO": FilterType.NO,
    "AP": FilterType.AP,
}


def _parse_filter_line(line: str) -> Optional[FilterParams]:
    """
    Parse a single Filter line from APO config.

    Examples:
        Filter  1: ON  PK       Fc     50 Hz   Gain  -3.0 dB  Q 10.00
        Filter  2: ON  PEQ      Fc     100 Hz  Gain   1.0 dB  BW Oct 0.167
        Filter: ON  NO       Fc     50 Hz
    """
    line = re.sub(r"^Filter\s*\d*\s*:\s*", "", line, flags=re.IGNORECASE).strip()

    enabled_match = re.match(r"(ON|OFF)\s+", line, re.IGNORECASE)
    if not enabled_match:
        return None
    enabled = enabled_match.group(1).upper() == "ON"
    line = line[enabled_match.end():]

    filter_type = None
    for type_str in sorted(_FILTER_TYPE_MAP.keys(), key=len, reverse=True):
        pattern = r"^" + re.escape(type_str) + r"\b"
        m = re.match(pattern, line, re.IGNORECASE)
        if m:
            filter_type = _FILTER_TYPE_MAP[type_str]
            line = line[m.end():].strip()
            break

    if filter_type is None:
        return None

    fc_match = re.search(r"Fc\s+([\d.]+)\s*Hz", line, re.IGNORECASE)
    if not fc_match:
        return None
    frequency = float(fc_match.group(1))

    gain = 0.0
    gain_match = re.search(r"Gain\s+([-\d.]+)\s*dB", line, re.IGNORECASE)
    if gain_match:
        gain = float(gain_match.group(1))

    q = None
    bw = None
    q_match = re.search(r"\bQ\s+([\d.]+)", line, re.IGNORECASE)
    bw_match = re.search(r"BW\s+Oct\s+([\d.]+)", line, re.IGNORECASE)

    if q_match:
        q = float(q_match.group(1))
    if bw_match:
        bw = float(bw_match.group(1))

    return FilterParams(
        filter_type=filter_type,
        frequency=frequency,
        gain=gain,
        q=q,
        bandwidth=bw,
        enabled=enabled,
    )


def _parse_preamp_line(line: str) -> Optional[float]:
    """Parse a Preamp line. Returns gain in dB."""
    m = re.match(r"Preamp\s*:\s*([-\d.]+)\s*dB", line, re.IGNORECASE)
    if m:
        return float(m.group(1))
    return None


def _parse_graphic_eq_line(line: str) -> Optional[list[tuple[float, float]]]:
    """Parse a GraphicEQ line into frequency-gain pairs."""
    m = re.match(r"GraphicEQ\s*:\s*(.+)", line, re.IGNORECASE)
    if not m:
        return None

    bands_str = m.group(1)
    bands = []
    for band in bands_str.split(";"):
        band = band.strip()
        if not band:
            continue
        parts = band.split()
        if len(parts) >= 2:
            try:
                freq = float(parts[0])
                gain = float(parts[1])
                bands.append((freq, gain))
            except ValueError:
                continue
    return bands if bands else None


def parse_apo_config(filepath: str, base_dir: Optional[str] = None) -> EQConfig:
    """
    Parse an Equalizer APO configuration file.

    Supports:
      - Preamp
      - Filter (all types)
      - GraphicEQ
      - Include (recursive)
      - Comments (# prefix)

    Args:
        filepath: Path to the config file
        base_dir: Base directory for resolving Include paths

    Returns:
        EQConfig with parsed settings
    """
    config = EQConfig(source_file=filepath)

    if base_dir is None:
        base_dir = str(Path(filepath).parent)

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError) as e:
        print(f"Warning: could not read {filepath}: {e}")
        return config

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        preamp = _parse_preamp_line(line)
        if preamp is not None:
            config.preamp_db += preamp
            continue

        if re.match(r"Filter\s*\d*\s*:", line, re.IGNORECASE):
            fp = _parse_filter_line(line)
            if fp is not None:
                config.filters.append(fp)
            continue

        if line.upper().startswith("GRAPHICEQ"):
            bands = _parse_graphic_eq_line(line)
            if bands:
                config.graphic_eq = bands
            continue

        inc_match = re.match(r"Include\s*:\s*(.+)", line, re.IGNORECASE)
        if inc_match:
            inc_path = inc_match.group(1).strip()
            if not os.path.isabs(inc_path):
                inc_path = os.path.join(base_dir, inc_path)
            if os.path.isfile(inc_path):
                sub_config = parse_apo_config(inc_path, os.path.dirname(inc_path))
                config.preamp_db += sub_config.preamp_db
                config.filters.extend(sub_config.filters)
                if sub_config.graphic_eq:
                    config.graphic_eq = sub_config.graphic_eq
            continue

    return config


def parse_apo_string(text: str) -> EQConfig:
    """Parse APO config from a string (for pasting configs directly)."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(text)
        f.flush()
        config = parse_apo_config(f.name)
    os.unlink(f.name)
    return config


def config_to_apo_string(config: EQConfig) -> str:
    """Export an EQConfig back to Equalizer APO config format."""
    lines = []

    if config.preamp_db != 0.0:
        lines.append(f"Preamp: {config.preamp_db:.1f} dB")

    for i, fp in enumerate(config.filters, 1):
        status = "ON" if fp.enabled else "OFF"
        ft_name = fp.filter_type.value

        parts = [f"Filter {i:2d}: {status}  {ft_name:<8s} Fc {fp.frequency:10.1f} Hz"]

        if fp.filter_type in (
            FilterType.PK, FilterType.PEQ, FilterType.MODAL,
            FilterType.LS, FilterType.HS,
            FilterType.LS6, FilterType.LS12,
            FilterType.HS6, FilterType.HS12,
        ):
            parts.append(f"Gain {fp.gain:6.1f} dB")

        if fp.q is not None:
            parts.append(f"Q {fp.q:.4f}")
        elif fp.bandwidth is not None:
            parts.append(f"BW Oct {fp.bandwidth:.3f}")

        lines.append("  ".join(parts))

    if config.graphic_eq:
        bands = "; ".join(f"{freq:.2f} {gain:.2f}" for freq, gain in config.graphic_eq)
        lines.append(f"GraphicEQ: {bands}")

    return "\n".join(lines)
