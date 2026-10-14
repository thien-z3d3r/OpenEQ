"""
OpenEQ GTK4 / Libadwaita Graphical User Interface.

Provides a modern Linux interface matching the capabilities of
Peace Equalizer (Equalizer APO extension):
  - Parametric EQ band controls (gain, freq, Q, type, enable)
  - Real-time frequency response curve display
  - Preamp control with clipping warning
  - Built-in and user presets
  - Import/Export of Equalizer APO / Peace config files
  - Live PipeWire filter-chain integration
"""

import os
import sys
from pathlib import Path
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib

from .biquad import FilterParams, FilterType
from .apo_parser import EQConfig, parse_apo_config, config_to_apo_string
from .curve_widget import FrequencyResponseWidget
from .autoeq_dialog import AutoEQDialog
from .presets import (
    BUILTIN_PRESETS,
    Preset,
    list_presets,
    save_preset,
    delete_preset,
    import_apo_preset,
    export_apo_preset,
    get_active_preset,
    set_active_preset,
    load_preset_by_name,
)
from .backend import (
    apply_eq,
    remove_eq,
    is_eq_active,
    get_system_audio_info,
    get_active_backend_name,
    save_backend_preference,
    get_backend_preference,
    BACKEND_PIPEWIRE,
    BACKEND_PULSEAUDIO,
    BACKEND_AUTO,
)


# standard iso octave frequencies
ISO_10_BANDS = [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
PEACE_13_BANDS = [10, 21, 42, 83, 166, 333, 577, 1000, 2000, 4000, 8000, 16000, 20000]

FILTER_TYPE_CHOICES = [
    ("Peaking (PK)", FilterType.PK),
    ("Low Shelf (LS)", FilterType.LS),
    ("High Shelf (HS)", FilterType.HS),
    ("Low Pass (LP)", FilterType.LP),
    ("High Pass (HP)", FilterType.HP),
    ("Band Pass (BP)", FilterType.BP),
    ("Notch (NO)", FilterType.NO),
]


class BandStrip(Gtk.Box):
    """A vertical slider strip representing one EQ band."""

    def __init__(self, index: int, params: FilterParams, on_changed_callback, on_delete_callback):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.set_margin_start(4)
        self.set_margin_end(4)
        self.set_margin_top(4)
        self.set_margin_bottom(4)

        self.index = index
        self.params = params
        self.on_changed = on_changed_callback
        self.on_delete = on_delete_callback
        self._updating = False

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.lbl_idx = Gtk.Label(label=f"#{index + 1}")
        self.lbl_idx.add_css_class("dim-label")
        self.lbl_idx.set_hexpand(True)
        header_box.append(self.lbl_idx)

        self.btn_power = Gtk.ToggleButton()
        self.btn_power.set_active(self.params.enabled)
        self.btn_power.set_icon_name("media-playback-start-symbolic" if self.params.enabled else "process-stop-symbolic")
        self.btn_power.set_tooltip_text("Enable/Disable Band")
        self.btn_power.add_css_class("flat")
        self.btn_power.connect("toggled", self._on_toggle_power)
        header_box.append(self.btn_power)

        self.append(header_box)

        type_strings = [name for name, _ in FILTER_TYPE_CHOICES]
        self.combo_type = Gtk.DropDown.new_from_strings(type_strings)
        current_idx = 0
        for i, (_, ft) in enumerate(FILTER_TYPE_CHOICES):
            if ft == self.params.filter_type:
                current_idx = i
                break
        self.combo_type.set_selected(current_idx)
        self.combo_type.connect("notify::selected", self._on_type_changed)
        self.append(self.combo_type)

        self.lbl_gain = Gtk.Label(label=f"{self.params.gain:+.1f} dB")
        self.lbl_gain.add_css_class("heading")
        self.append(self.lbl_gain)

        self.adj_gain = Gtk.Adjustment(
            value=self.params.gain,
            lower=-30.0,
            upper=30.0,
            step_increment=0.5,
            page_increment=3.0,
        )
        self.scale_gain = Gtk.Scale(
            orientation=Gtk.Orientation.VERTICAL,
            adjustment=self.adj_gain,
        )
        self.scale_gain.set_inverted(True)
        self.scale_gain.set_vexpand(True)
        self.scale_gain.set_size_request(-1, 160)
        self.scale_gain.add_mark(0.0, Gtk.PositionType.RIGHT, "0")
        self.adj_gain.connect("value-changed", self._on_gain_changed)
        self.append(self.scale_gain)

        lbl_f = Gtk.Label(label="Freq (Hz)")
        lbl_f.add_css_class("caption")
        self.append(lbl_f)

        self.adj_freq = Gtk.Adjustment(
            value=self.params.frequency,
            lower=10.0,
            upper=22000.0,
            step_increment=10.0,
            page_increment=100.0,
        )
        self.spin_freq = Gtk.SpinButton(adjustment=self.adj_freq, climb_rate=1.0, digits=0)
        self.spin_freq.connect("value-changed", self._on_freq_changed)
        self.append(self.spin_freq)

        lbl_q = Gtk.Label(label="Q Factor")
        lbl_q.add_css_class("caption")
        self.append(lbl_q)

        self.adj_q = Gtk.Adjustment(
            value=self.params.effective_q(),
            lower=0.1,
            upper=30.0,
            step_increment=0.1,
            page_increment=1.0,
        )
        self.spin_q = Gtk.SpinButton(adjustment=self.adj_q, climb_rate=0.1, digits=2)
        self.spin_q.connect("value-changed", self._on_q_changed)
        self.append(self.spin_q)

        self.btn_del = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        self.btn_del.add_css_class("flat")
        self.btn_del.add_css_class("destructive-action")
        self.btn_del.set_tooltip_text("Delete Band")
        self.btn_del.connect("clicked", lambda b: self.on_delete(self))
        self.append(self.btn_del)

    def _on_toggle_power(self, btn):
        if self._updating:
            return
        self.params.enabled = btn.get_active()
        btn.set_icon_name("media-playback-start-symbolic" if self.params.enabled else "process-stop-symbolic")
        self.on_changed()

    def _on_type_changed(self, drop_down, pspec):
        if self._updating:
            return
        selected = drop_down.get_selected()
        if 0 <= selected < len(FILTER_TYPE_CHOICES):
            self.params.filter_type = FILTER_TYPE_CHOICES[selected][1]
            self.on_changed()

    def _on_gain_changed(self, adj):
        if self._updating:
            return
        self.params.gain = round(adj.get_value(), 1)
        self.lbl_gain.set_text(f"{self.params.gain:+.1f} dB")
        self.on_changed()

    def _on_freq_changed(self, adj):
        if self._updating:
            return
        self.params.frequency = round(adj.get_value(), 1)
        self.on_changed()

    def _on_q_changed(self, adj):
        if self._updating:
            return
        self.params.q = round(adj.get_value(), 3)
        self.params.bandwidth = None
        self.on_changed()

    def update_from_params(self, params: FilterParams):
        """Update strip controls without triggering change callbacks."""
        self._updating = True
        self.params = params
        self.btn_power.set_active(params.enabled)
        self.btn_power.set_icon_name("media-playback-start-symbolic" if params.enabled else "process-stop-symbolic")

        for i, (_, ft) in enumerate(FILTER_TYPE_CHOICES):
            if ft == params.filter_type:
                self.combo_type.set_selected(i)
                break

        self.adj_gain.set_value(params.gain)
        self.lbl_gain.set_text(f"{params.gain:+.1f} dB")
        self.adj_freq.set_value(params.frequency)
        self.adj_q.set_value(params.effective_q())
        self._updating = False


class OpenEQWindow(Adw.ApplicationWindow):
    """Main window for OpenEQ Equalizer."""

    def __init__(self, backend_override: Optional[str] = None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.backend_choice = backend_override or get_backend_preference() or BACKEND_AUTO
        self.set_title("OpenEQ - Peace Equalizer for Linux")
        self.set_default_size(980, 720)

        self.config = EQConfig()
        self.strips: list[BandStrip] = []
        self._auto_apply = True

        self._load_default_bands()
        self._build_ui()
        self._update_curve()
        self._check_audio_status()

    def _load_default_bands(self):
        """Initialize default 13-band Peace EQ layout."""
        self.config.filters = [
            FilterParams(FilterType.PK, freq, gain=0.0, q=1.41)
            for freq in PEACE_13_BANDS
        ]

    def _build_ui(self):
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.toast_overlay.set_child(main_vbox)

        header = Adw.HeaderBar()
        main_vbox.append(header)

        left_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        self.switch_power = Gtk.Switch()
        self.switch_power.set_active(True)
        self.switch_power.set_tooltip_text("Toggle Equalizer Processing")
        self.switch_power.connect("notify::active", self._on_global_power_toggled)
        left_box.append(self.switch_power)

        lbl_power = Gtk.Label(label="EQ Active")
        lbl_power.add_css_class("heading")
        left_box.append(lbl_power)

        header.pack_start(left_box)

        right_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        self.combo_backend = Gtk.DropDown.new_from_strings(["Auto-detect", "PipeWire", "PulseAudio"])
        init_idx = 0
        if self.backend_choice == BACKEND_PIPEWIRE:
            init_idx = 1
        elif self.backend_choice == BACKEND_PULSEAUDIO:
            init_idx = 2
        self.combo_backend.set_selected(init_idx)
        self.combo_backend.set_tooltip_text("Audio Backend: Auto-detect, PipeWire, or PulseAudio")
        self.combo_backend.connect("notify::selected", self._on_backend_selected)
        right_box.append(self.combo_backend)

        btn_autoeq = Gtk.Button.new_from_icon_name("audio-headphones-symbolic")
        btn_autoeq.set_tooltip_text("AutoEQ Headphone Profiles")
        btn_autoeq.connect("clicked", lambda b: self._open_autoeq_dialog())
        right_box.append(btn_autoeq)

        btn_apply = Gtk.Button(label="Apply to Audio")
        btn_apply.add_css_class("suggested-action")
        btn_apply.connect("clicked", lambda b: self._apply_to_audio())
        right_box.append(btn_apply)

        self.btn_presets = Gtk.MenuButton()
        self.btn_presets.set_icon_name("document-open-symbolic")
        self.btn_presets.set_tooltip_text("Presets & Files")
        self._setup_presets_menu()
        right_box.append(self.btn_presets)

        header.pack_end(right_box)

        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_vexpand(True)
        main_vbox.append(scrolled_window)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_start(16)
        content_box.set_margin_end(16)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(16)
        scrolled_window.set_child(content_box)

        self.banner_status = Gtk.Label(label="Initializing PipeWire backend...")
        self.banner_status.add_css_class("dim-label")
        content_box.append(self.banner_status)

        curve_frame = Gtk.Frame()
        curve_frame.add_css_class("card")
        self.curve_widget = FrequencyResponseWidget()
        curve_frame.set_child(self.curve_widget)
        content_box.append(curve_frame)

        ctrl_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        ctrl_bar.add_css_class("toolbar")

        lbl_preamp = Gtk.Label(label="Preamp:")
        lbl_preamp.add_css_class("heading")
        ctrl_bar.append(lbl_preamp)

        self.adj_preamp = Gtk.Adjustment(
            value=self.config.preamp_db,
            lower=-24.0,
            upper=12.0,
            step_increment=0.5,
            page_increment=2.0,
        )
        self.scale_preamp = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL,
            adjustment=self.adj_preamp,
        )
        self.scale_preamp.set_hexpand(True)
        self.scale_preamp.add_mark(0.0, Gtk.PositionType.BOTTOM, "0 dB")
        self.adj_preamp.connect("value-changed", self._on_preamp_changed)
        ctrl_bar.append(self.scale_preamp)

        self.lbl_preamp_val = Gtk.Label(label=f"{self.config.preamp_db:+.1f} dB")
        self.lbl_preamp_val.set_width_chars(8)
        self.lbl_preamp_val.add_css_class("heading")
        ctrl_bar.append(self.lbl_preamp_val)

        chk_auto = Gtk.CheckButton(label="Auto-apply changes")
        chk_auto.set_active(self._auto_apply)
        chk_auto.connect("toggled", lambda c: setattr(self, "_auto_apply", c.get_active()))
        ctrl_bar.append(chk_auto)

        content_box.append(ctrl_bar)

        rack_frame = Gtk.Frame()
        rack_frame.add_css_class("card")

        rack_scroller = Gtk.ScrolledWindow()
        rack_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        rack_scroller.set_min_content_height(340)
        rack_frame.set_child(rack_scroller)

        self.bands_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.bands_box.set_margin_start(8)
        self.bands_box.set_margin_end(8)
        self.bands_box.set_margin_top(8)
        self.bands_box.set_margin_bottom(8)
        rack_scroller.set_child(self.bands_box)

        self._refresh_bands_ui()
        content_box.append(rack_frame)

        bottom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        btn_add_band = Gtk.Button(label="+ Add Band")
        btn_add_band.connect("clicked", lambda b: self._add_band())
        bottom_box.append(btn_add_band)

        btn_flat = Gtk.Button(label="Reset (Flat)")
        btn_flat.connect("clicked", lambda b: self._reset_flat())
        bottom_box.append(btn_flat)

        btn_10_band = Gtk.Button(label="10-Band ISO")
        btn_10_band.connect("clicked", lambda b: self._set_iso_bands(ISO_10_BANDS))
        bottom_box.append(btn_10_band)

        btn_peace = Gtk.Button(label="Peace 13-Band")
        btn_peace.connect("clicked", lambda b: self._set_iso_bands(PEACE_13_BANDS))
        bottom_box.append(btn_peace)

        btn_autoeq_bar = Gtk.Button(label="AutoEQ Profiles...")
        btn_autoeq_bar.connect("clicked", lambda b: self._open_autoeq_dialog())
        bottom_box.append(btn_autoeq_bar)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        bottom_box.append(spacer)

        btn_import = Gtk.Button(label="Import APO / Peace...")
        btn_import.connect("clicked", lambda b: self._open_import_dialog())
        bottom_box.append(btn_import)

        btn_export = Gtk.Button(label="Export APO...")
        btn_export.connect("clicked", lambda b: self._open_export_dialog())
        bottom_box.append(btn_export)

        btn_save_preset = Gtk.Button(label="Save Preset...")
        btn_save_preset.connect("clicked", lambda b: self._open_save_preset_dialog())
        bottom_box.append(btn_save_preset)

        content_box.append(bottom_box)

    def _setup_presets_menu(self):
        """Construct the presets dropdown menu."""
        menu = Gio.Menu()

        builtin_section = Gio.Menu()
        for name in BUILTIN_PRESETS.keys():
            builtin_section.append(name, f"app.load_preset::{name}")
        menu.append_section("Factory Presets", builtin_section)

        user_presets = [p for p in list_presets() if not p.builtin]
        if user_presets:
            user_section = Gio.Menu()
            for p in user_presets:
                user_section.append(p.name, f"app.load_preset::{p.name}")
            menu.append_section("My Presets", user_section)

        self.btn_presets.set_menu_model(menu)

    def _refresh_bands_ui(self):
        """Re-render all band strips from self.config.filters."""
        while True:
            child = self.bands_box.get_first_child()
            if child is None:
                break
            self.bands_box.remove(child)
        self.strips.clear()

        for i, fp in enumerate(self.config.filters):
            strip = BandStrip(
                index=i,
                params=fp,
                on_changed_callback=self._on_band_changed,
                on_delete_callback=self._on_delete_band,
            )
            self.strips.append(strip)
            self.bands_box.append(strip)

    def _on_band_changed(self):
        """Called whenever a band strip's parameters change."""
        self._update_curve()
        if self._auto_apply and self.switch_power.get_active():
            self._apply_to_audio()

    def _on_preamp_changed(self, adj):
        self.config.preamp_db = round(adj.get_value(), 1)
        self.lbl_preamp_val.set_text(f"{self.config.preamp_db:+.1f} dB")
        self._update_curve()
        if self._auto_apply and self.switch_power.get_active():
            self._apply_to_audio()

    def _on_global_power_toggled(self, switch, pspec):
        active = switch.get_active()
        target = self.backend_choice if self.backend_choice != BACKEND_AUTO else None
        if active:
            self._apply_to_audio()
            self._show_toast("Equalizer Active")
        else:
            remove_eq(backend=target)
            self._check_audio_status()
            self._show_toast("Equalizer Bypassed")

    def _add_band(self):
        """Append a new parametric peaking band."""
        # default frequency for added band
        new_freq = 1000.0
        if self.config.filters:
            new_freq = min(20000.0, self.config.filters[-1].frequency * 1.5)

        fp = FilterParams(FilterType.PK, frequency=new_freq, gain=0.0, q=1.41)
        self.config.filters.append(fp)
        self._refresh_bands_ui()
        self._update_curve()

    def _on_delete_band(self, strip: BandStrip):
        """Remove a band strip."""
        if strip.params in self.config.filters:
            self.config.filters.remove(strip.params)
            self._refresh_bands_ui()
            self._update_curve()
            if self._auto_apply:
                self._apply_to_audio()

    def _reset_flat(self):
        """Reset all band gains and preamp to 0 dB."""
        self.config.preamp_db = 0.0
        self.adj_preamp.set_value(0.0)
        for fp in self.config.filters:
            fp.gain = 0.0
        for strip in self.strips:
            strip.update_from_params(strip.params)
        self._update_curve()
        if self._auto_apply:
            self._apply_to_audio()
        self._show_toast("Reset to Flat curve")

    def _set_iso_bands(self, freqs: list[float]):
        """Replace current bands with specified frequency layout."""
        self.config.filters = [
            FilterParams(FilterType.PK, f, gain=0.0, q=1.41) for f in freqs
        ]
        self._refresh_bands_ui()
        self._update_curve()
        if self._auto_apply:
            self._apply_to_audio()

    def _update_curve(self):
        """Refresh the frequency response curve visualization."""
        self.curve_widget.set_data(self.config.filters, self.config.preamp_db)

    def _on_backend_selected(self, dropdown, pspec):
        idx = dropdown.get_selected()
        choices = [BACKEND_AUTO, BACKEND_PIPEWIRE, BACKEND_PULSEAUDIO]
        selected_backend = choices[idx] if idx < len(choices) else BACKEND_AUTO
        self.backend_choice = selected_backend
        save_backend_preference(selected_backend)
        self._check_audio_status()
        if self._auto_apply and self.switch_power.get_active():
            self._apply_to_audio()

    def _check_audio_status(self):
        """Check audio backend availability and populate status banner."""
        target = self.backend_choice if self.backend_choice != BACKEND_AUTO else None
        info = get_system_audio_info(target)
        backend_name = info["active_backend"].capitalize()

        if info["available"]:
            server_ver = info.get("version") or info.get("server_name") or backend_name
            sinks = ", ".join(info.get("sinks", [info.get("default_sink", "Default Sink")]))
            active_str = " (Active)" if info["eq_active"] else " (Bypassed)"
            self.banner_status.set_text(f"[{backend_name}] {server_ver} | Output: {sinks}{active_str}")
        else:
            self.banner_status.set_text(f"{backend_name} audio server not detected. Audio will not be filtered.")

    def _check_pipewire_status(self):
        """Compatibility alias for _check_audio_status."""
        self._check_audio_status()

    def _apply_to_audio(self):
        """Send current EQ configuration to active audio backend (PipeWire or PulseAudio)."""
        target = self.backend_choice if self.backend_choice != BACKEND_AUTO else None
        active_backend = get_active_backend_name(target)
        backend_name = "PipeWire" if active_backend == BACKEND_PIPEWIRE else "PulseAudio"

        success = apply_eq(self.config, backend=active_backend)
        if success:
            self._show_toast(f"EQ applied to {backend_name}")
            self._check_audio_status()
        else:
            self._show_toast(f"Failed to apply EQ to {backend_name}")

    def _apply_to_pipewire(self):
        """Compatibility alias for _apply_to_audio."""
        self._apply_to_audio()

    def _show_toast(self, message: str):
        toast = Adw.Toast.new(message)
        toast.set_timeout(2)
        self.toast_overlay.add_toast(toast)

    def load_preset(self, preset_name: str):
        """Load a preset into the interface."""
        preset = load_preset_by_name(preset_name)
        if not preset:
            return

        self.config = preset.config
        self.adj_preamp.set_value(self.config.preamp_db)
        self._refresh_bands_ui()
        self._update_curve()
        set_active_preset(preset_name)

        if self._auto_apply and self.switch_power.get_active():
            self._apply_to_audio()

        self._show_toast(f"Loaded preset: {preset_name}")

    def _open_autoeq_dialog(self):
        """Open the AutoEQ headphone compensation browser."""
        dialog = AutoEQDialog(self, self._on_autoeq_loaded)
        dialog.present()

    def _on_autoeq_loaded(self, config: EQConfig, profile_name: str):
        """Callback when an AutoEQ profile is selected."""
        self.config = config
        self.adj_preamp.set_value(config.preamp_db)
        self._refresh_bands_ui()
        self._update_curve()
        if self._auto_apply and self.switch_power.get_active():
            self._apply_to_audio()
        self._show_toast(f"Loaded AutoEQ: {profile_name}")

    def _open_import_dialog(self):
        """Open file chooser to import an Equalizer APO / Peace config."""
        dialog = Gtk.FileDialog()
        dialog.set_title("Import Equalizer APO / Peace Config")

        filters = Gio.ListStore.new(Gtk.FileFilter)
        f_txt = Gtk.FileFilter()
        f_txt.set_name("Equalizer APO Config (*.txt)")
        f_txt.add_pattern("*.txt")
        filters.append(f_txt)

        f_all = Gtk.FileFilter()
        f_all.set_name("All Files")
        f_all.add_pattern("*")
        filters.append(f_all)

        dialog.set_filters(filters)

        def on_open_finish(dlg, res):
            try:
                gfile = dlg.open_finish(res)
                if gfile:
                    path = gfile.get_path()
                    preset = import_apo_preset(path)
                    self.config = preset.config
                    self.adj_preamp.set_value(self.config.preamp_db)
                    self._refresh_bands_ui()
                    self._update_curve()
                    if self._auto_apply:
                        self._apply_to_audio()
                    self._show_toast(f"Imported {os.path.basename(path)}")
            except GLib.Error as e:
                pass

        dialog.open(self, None, on_open_finish)

    def _open_export_dialog(self):
        """Open file chooser to export as Equalizer APO config."""
        dialog = Gtk.FileDialog()
        dialog.set_title("Export Equalizer APO Config")
        dialog.set_initial_name("peace_eq.txt")

        def on_save_finish(dlg, res):
            try:
                gfile = dlg.save_finish(res)
                if gfile:
                    path = gfile.get_path()
                    preset = Preset(name="Export", config=self.config)
                    export_apo_preset(preset, path)
                    self._show_toast(f"Exported to {os.path.basename(path)}")
            except GLib.Error:
                pass

        dialog.save(self, None, on_save_finish)

    def _open_save_preset_dialog(self):
        """Prompt user for a preset name and save."""
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Save Preset",
            body="Enter a name for your preset:",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Save")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

        entry = Gtk.Entry()
        entry.set_placeholder_text("My Custom EQ")
        entry.set_margin_top(12)
        entry.set_margin_bottom(12)
        dialog.set_extra_child(entry)

        def on_response(dlg, response):
            if response == "save":
                name = entry.get_text().strip()
                if name:
                    p = Preset(name=name, config=self.config)
                    save_preset(p)
                    self._setup_presets_menu()
                    self._show_toast(f"Saved preset: {name}")

        dialog.connect("response", on_response)
        dialog.present()


class OpenEQApp(Adw.Application):
    """Main Adwaita application class."""

    def __init__(self, backend_override: Optional[str] = None):
        super().__init__(
            application_id="io.github.openeq",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.backend_override = backend_override

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = OpenEQWindow(backend_override=self.backend_override, application=self)
            self._setup_actions(win)
        win.present()

    def _setup_actions(self, win: OpenEQWindow):
        action = Gio.SimpleAction.new("load_preset", GLib.VariantType.new("s"))

        def on_load_preset(act, param):
            name = param.get_string()
            win.load_preset(name)

        action.connect("activate", on_load_preset)
        self.add_action(action)


def run_gui(backend_override: Optional[str] = None):
    """Main entry point to start the OpenEQ GUI."""
    app = OpenEQApp(backend_override=backend_override)
    return app.run(sys.argv)
