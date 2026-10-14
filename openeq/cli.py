"""
Command-line interface for OpenEQ.

Enables headless automation, script integration, and terminal control
alongside the GTK4 GUI with dual PipeWire and PulseAudio support.
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

from . import __app_name__, __version__
from .apo_parser import parse_apo_config, config_to_apo_string
from .biquad import FilterParams, FilterType
from .presets import (
    BUILTIN_PRESETS,
    Preset,
    list_presets,
    load_preset_by_name,
    save_preset,
    delete_preset,
    import_apo_preset,
    export_apo_preset,
    get_active_preset,
    set_active_preset,
)
from .backend import (
    BACKEND_PIPEWIRE,
    BACKEND_PULSEAUDIO,
    BACKEND_AUTO,
    get_active_backend_name,
    get_system_audio_info,
    apply_eq,
    remove_eq,
    is_eq_active,
    save_backend_preference,
    get_backend_preference,
    detect_available_backends,
)
from .pulseaudio_backend import generate_pulseaudio_script
from .pipewire_backend import generate_filter_chain_config
from .autoeq import (
    OFFLINE_AUTOEQ_DATABASE,
    search_autoeq,
    fetch_from_github,
    get_autoeq_mode,
    set_autoeq_mode,
    is_online_mode,
    get_autoeq_status,
    update_autoeq_database,
)


def _get_target_backend(args) -> Optional[str]:
    """Extract chosen backend from parsed args if specified."""
    return getattr(args, "backend", None)


def cmd_gui(args):
    """Launch the GTK4 graphical interface."""
    from .gui import run_gui
    backend_choice = _get_target_backend(args)
    return run_gui(backend_override=backend_choice)


def cmd_apply(args):
    """Apply a preset or APO configuration file to active audio server."""
    target = args.target
    backend_choice = _get_target_backend(args)
    active_backend = get_active_backend_name(backend_choice)

    # resolve file path if file exists
    p = Path(target)
    if p.is_file():
        print(f"Loading Equalizer APO configuration from: {p}")
        config = parse_apo_config(str(p))
        preset_name = p.stem
    else:
        preset = load_preset_by_name(target)
        if not preset:
            print(f"Error: Preset or file '{target}' not found.")
            print("Use 'openeq list' to see available presets.")
            return 1
        config = preset.config
        preset_name = preset.name

    backend_label = "PipeWire filter-chain" if active_backend == BACKEND_PIPEWIRE else "PulseAudio equalizer sink"
    print(f"Applying '{preset_name}' (Preamp: {config.preamp_db:+.1f} dB, Bands: {len(config.filters)}) to {backend_label}...")

    success = apply_eq(config, backend=active_backend)
    if success:
        set_active_preset(preset_name)
        print(f"Successfully applied equalizer to {backend_label}.")
        return 0
    else:
        print(f"Failed to apply equalizer configuration to {backend_label}.")
        return 1


def cmd_bypass(args):
    """Bypass and remove the equalizer from active audio server."""
    backend_choice = _get_target_backend(args)
    active_backend = get_active_backend_name(backend_choice)
    backend_label = "PipeWire" if active_backend == BACKEND_PIPEWIRE else "PulseAudio"

    print(f"Disabling OpenEQ ({backend_label})...")
    removed = remove_eq(backend=backend_choice)
    if removed:
        print(f"Equalizer bypassed and removed from {backend_label}.")
    else:
        print(f"Equalizer was not active on {backend_label}.")
    return 0


def cmd_list(args):
    """List all available presets."""
    active = get_active_preset()
    presets = list_presets()

    print(f"\nAvailable Presets ({len(presets)}):")
    print("-" * 50)
    for p in presets:
        marker = " [*]" if p.name == active else "    "
        tag = "[Factory]" if p.builtin else "[User]   "
        bands_count = len(p.config.filters)
        desc = f" - {p.description}" if p.description else ""
        print(f"{marker} {tag} {p.name:<18} ({bands_count} bands, {p.config.preamp_db:+.1f}dB){desc}")
    print("-" * 50)
    if active:
        print(f"Active preset: {active}")
    print()
    return 0


def cmd_status(args):
    """Show current PipeWire, PulseAudio, and OpenEQ status."""
    backend_choice = _get_target_backend(args)
    info = get_system_audio_info(backend_choice)

    print(f"\n{__app_name__} v{__version__} Status")
    print("=" * 45)

    print(f"Active Backend:       {info['active_backend'].capitalize()} ({'explicitly selected' if backend_choice else 'auto-detected'})")
    print(f"Configured Backend:   {info['configured_backend'].capitalize()}")
    print(f"Detected Audio Server: {info['detected_backend'].capitalize()}")
    print("-" * 45)
    print(f"PipeWire Available:   {'Yes' if info['pipewire_available'] else 'No'}")
    print(f"PulseAudio Available: {'Yes' if info['pulseaudio_available'] else 'No'}")

    if info["server_name"]:
        print(f"Server Name:          {info['server_name']}")
    if info["version"]:
        print(f"Server Version:       {info['version']}")
    if info["default_sink"]:
        print(f"Default Sink:         {info['default_sink']}")

    print("-" * 45)
    active = info["eq_active"]
    print(f"OpenEQ Active:        {'Yes' if active else 'No (Bypassed)'}")

    cur_preset = get_active_preset()
    if cur_preset:
        print(f"Current Preset:       {cur_preset}")

    if info["sinks"]:
        print("\nAvailable Audio Sinks:")
        for s in info["sinks"]:
            prefix = "  * " if s == info.get("default_sink") else "  - "
            print(f"{prefix}{s}")
    print()
    return 0


def cmd_backend(args):
    """View or configure default audio backend preference."""
    action = args.subaction or "get"
    if action == "get":
        cur_pref = get_backend_preference() or BACKEND_AUTO
        detected = get_active_backend_name()
        available = detect_available_backends()
        print(f"Backend Preference: {cur_pref}")
        print(f"Active Detected:    {detected}")
        print(f"PipeWire Installed: {'Yes' if available['pipewire'] else 'No'}")
        print(f"PulseAudio Installed: {'Yes' if available['pulseaudio'] else 'No'}")
        return 0
    elif action in ("set", "switch"):
        target = (args.target or "").strip().lower()
        if target in (BACKEND_PIPEWIRE, BACKEND_PULSEAUDIO, BACKEND_AUTO, "pw", "pa", "pulse"):
            save_backend_preference(target)
            canon = get_backend_preference()
            print(f"Backend preference saved: {canon}")
            return 0
        else:
            print(f"Error: Unknown backend '{target}'. Choose 'pipewire', 'pulseaudio', or 'auto'.")
            return 1
    return 0


def cmd_import(args):
    """Import an APO config file as a preset."""
    filepath = args.file
    p = Path(filepath)
    if not p.is_file():
        print(f"Error: File '{filepath}' does not exist.")
        return 1

    name = args.name or p.stem.replace("_", " ").title()
    preset = import_apo_preset(str(p), name=name)
    saved_path = save_preset(preset)
    print(f"Imported '{name}' with {len(preset.config.filters)} bands.")
    print(f"Saved to: {saved_path}")
    return 0


def cmd_export(args):
    """Export a preset to an APO config file."""
    preset = load_preset_by_name(args.preset)
    if not preset:
        print(f"Error: Preset '{args.preset}' not found.")
        return 1

    outpath = args.output
    export_apo_preset(preset, outpath)
    print(f"Exported preset '{preset.name}' to: {outpath}")
    return 0


def cmd_dump_pw(args):
    """Dump generated PipeWire filter-chain configuration to stdout."""
    preset = load_preset_by_name(args.preset)
    if not preset:
        print(f"Error: Preset '{args.preset}' not found.")
        return 1
    conf = generate_filter_chain_config(preset.config)
    print(conf)
    return 0


def cmd_dump_pa(args):
    """Dump generated PulseAudio LADSPA / pactl configuration to stdout."""
    preset = load_preset_by_name(args.preset)
    if not preset:
        print(f"Error: Preset '{args.preset}' not found.")
        return 1
    script = generate_pulseaudio_script(preset.config)
    print(script)
    return 0


def cmd_autoeq(args):
    """Handle AutoEQ subcommands: search, list, apply, update, mode."""
    subaction = args.subaction or "list"
    backend_choice = _get_target_backend(args)

    if subaction == "mode":
        target_mode = (args.query or "").strip().lower()
        if target_mode in ("online", "offline"):
            set_autoeq_mode(target_mode)
            print(f"AutoEQ mode set to: {target_mode}")
            return 0
        elif target_mode:
            print(f"Invalid mode '{target_mode}'. Choose 'online' or 'offline'.")
            return 1
        else:
            status = get_autoeq_status()
            print(f"AutoEQ Mode: {status['mode']}")
            print(f"Online Search: {'Enabled' if status['online'] else 'Disabled'}")
            print(f"Indexed Profiles: {status['entry_count']}")
            print(f"Last Updated: {status['last_updated'] or 'Never'}")
            return 0

    elif subaction == "update":
        print("Updating AutoEQ database from online repository...")
        count, msg = update_autoeq_database(force=True)
        if count > 0:
            print(f"[ok] {msg}")
            return 0
        else:
            print(f"[err] {msg}")
            return 1

    elif subaction == "list":
        status = get_autoeq_status()
        mode_str = f"Mode: {status['mode']}"
        profiles_info = f"{status['entry_count']} profiles available"
        print(f"\nAutoEQ Profiles [{mode_str} | {profiles_info}]:")
        print("-" * 65)
        for e in OFFLINE_AUTOEQ_DATABASE:
            cfg = e.get_config()
            print(f"  - {e.brand:<15} {e.model:<24} [{e.form:<8}] {e.measurer:<11} ({len(cfg.filters)} bands, {cfg.preamp_db:+.1f}dB)")
        print("-" * 65)
        if status["online"]:
            print(f"Online database contains {status['entry_count']} headphone profiles.")
        print("To search: openeq autoeq search <name>")
        print("To apply:  openeq autoeq apply <model>")
        print("To update: openeq autoeq update")
        print("To mode:   openeq autoeq mode [online|offline]")
        return 0

    elif subaction == "search":
        query = args.query or ""
        results = search_autoeq(query)
        if not results:
            print(f"No matches for '{query}'. Attempting to fetch directly from AutoEQ repository...")
            fetched = fetch_from_github(query)
            if fetched:
                results = [fetched]
            else:
                print(f"Could not find headphone profile for '{query}'.")
                return 1

        print(f"\nAutoEQ Results for '{query}' ({len(results)}):")
        print("-" * 65)
        display_results = results[:25]
        for e in display_results:
            if e.apo_text:
                cfg = e.get_config()
                bands_info = f"({len(cfg.filters)} bands, {cfg.preamp_db:+.1f}dB)"
            else:
                bands_info = "[online profile - ready to apply]"
            print(f"  - {e.brand:<15} {e.model:<24} [{e.form:<8}] {e.measurer:<11} {bands_info}")
        if len(results) > 25:
            print(f"  ... and {len(results) - 25} more results. Narrow your search query.")
        print("-" * 65)
        return 0

    elif subaction == "apply":
        target = args.query or ""
        results = search_autoeq(target)
        if not results:
            print(f"Model '{target}' not found. Trying direct GitHub fetch...")
            fetched = fetch_from_github(target)
            if fetched:
                results = [fetched]
            else:
                print(f"Error: AutoEQ profile '{target}' not found.")
                return 1

        entry = results[0]
        config = entry.get_config()
        full_name = f"{entry.brand} {entry.model}"
        active_backend = get_active_backend_name(backend_choice)
        backend_label = "PipeWire" if active_backend == BACKEND_PIPEWIRE else "PulseAudio"

        print(f"Applying AutoEQ profile to {backend_label}: {full_name} ({len(config.filters)} bands, {config.preamp_db:+.1f}dB)...")
        success = apply_eq(config, backend=active_backend)
        if success:
            set_active_preset(full_name)
            print(f"Successfully applied {full_name} to {backend_label}.")
            return 0
        else:
            print(f"Failed to apply {full_name} to {backend_label}.")
            return 1

    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="openeq",
        description="OpenEQ - Peace Equalizer APO fork for Linux (PipeWire & PulseAudio)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{__app_name__} {__version__}",
    )
    parser.add_argument(
        "--backend", "-b",
        choices=["pipewire", "pulseaudio", "auto", "pw", "pa", "pulse"],
        default=None,
        help="Audio backend to use (pipewire, pulseaudio, auto)",
    )

    subparsers = parser.add_subparsers(dest="command")

    p_gui = subparsers.add_parser("gui", help="Launch the GTK4 graphical interface (default)")
    p_gui.add_argument("--backend", "-b", choices=["pipewire", "pulseaudio", "auto", "pw", "pa", "pulse"], help="Force specific audio backend")

    p_apply = subparsers.add_parser("apply", help="Apply a preset or Equalizer APO file")
    p_apply.add_argument("target", help="Preset name or path to .txt config file")
    p_apply.add_argument("--backend", "-b", choices=["pipewire", "pulseaudio", "auto", "pw", "pa", "pulse"], help="Target audio backend")

    p_bypass = subparsers.add_parser("bypass", help="Bypass/disable equalizer processing")
    p_bypass.add_argument("--backend", "-b", choices=["pipewire", "pulseaudio", "auto", "pw", "pa", "pulse"], help="Target audio backend")

    p_list = subparsers.add_parser("list", help="List all available presets")

    p_status = subparsers.add_parser("status", help="Show audio server and equalizer status")
    p_status.add_argument("--backend", "-b", choices=["pipewire", "pulseaudio", "auto", "pw", "pa", "pulse"], help="Target audio backend")

    p_backend = subparsers.add_parser("backend", help="View or set audio backend preference")
    p_backend.add_argument("subaction", choices=["get", "set", "switch"], nargs="?", default="get")
    p_backend.add_argument("target", nargs="?", default="", help="Backend name: pipewire, pulseaudio, or auto")

    p_autoeq = subparsers.add_parser("autoeq", help="Search and apply AutoEQ headphone compensation profiles")
    p_autoeq.add_argument("subaction", choices=["list", "search", "apply", "update", "mode"], nargs="?", default="list")
    p_autoeq.add_argument("query", nargs="?", default="", help="Headphone model/brand to search or apply, or mode [online|offline]")
    p_autoeq.add_argument("--backend", "-b", choices=["pipewire", "pulseaudio", "auto", "pw", "pa", "pulse"], help="Target audio backend")

    p_import = subparsers.add_parser("import", help="Import an Equalizer APO config file")
    p_import.add_argument("file", help="Path to config file (.txt)")
    p_import.add_argument("--name", help="Custom name for the preset")

    p_export = subparsers.add_parser("export", help="Export a preset as an Equalizer APO config file")
    p_export.add_argument("preset", help="Name of preset to export")
    p_export.add_argument("output", help="Destination file path (.txt)")

    p_dump = subparsers.add_parser("dump-pw", help="Print PipeWire filter-chain JSON config for a preset")
    p_dump.add_argument("preset", default="Bass Boost", nargs="?", help="Preset name (default: Bass Boost)")

    p_dump_pa = subparsers.add_parser("dump-pa", help="Print PulseAudio LADSPA configuration script for a preset")
    p_dump_pa.add_argument("preset", default="Bass Boost", nargs="?", help="Preset name (default: Bass Boost)")

    args = parser.parse_args(argv)

    if args.command is None or args.command == "gui":
        return cmd_gui(args)
    elif args.command == "apply":
        return cmd_apply(args)
    elif args.command == "bypass":
        return cmd_bypass(args)
    elif args.command == "list":
        return cmd_list(args)
    elif args.command == "status":
        return cmd_status(args)
    elif args.command == "backend":
        return cmd_backend(args)
    elif args.command == "autoeq":
        return cmd_autoeq(args)
    elif args.command == "import":
        return cmd_import(args)
    elif args.command == "export":
        return cmd_export(args)
    elif args.command == "dump-pw":
        return cmd_dump_pw(args)
    elif args.command == "dump-pa":
        return cmd_dump_pa(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
