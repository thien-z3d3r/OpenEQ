"""
AutoEQ Headphone Browser Dialog for OpenEQ.

Interactive GTK4 / Libadwaita window matching Peace Equalizer's AutoEQ interface:
allows users to search offline models or browse and download directly from
the AutoEQ online database (8,800+ profiles), preview curves, and load them into OpenEQ.
"""

import threading
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from .autoeq import (
    AutoEQEntry,
    OFFLINE_AUTOEQ_DATABASE,
    search_autoeq,
    fetch_from_github,
    get_autoeq_mode,
    set_autoeq_mode,
    is_online_mode,
    get_autoeq_status,
    update_autoeq_database,
)
from .curve_widget import FrequencyResponseWidget


class AutoEQDialog(Adw.Window):
    """AutoEQ headphone profile browser and loader dialog."""

    def __init__(self, parent_window, on_load_profile_callback):
        super().__init__(transient_for=parent_window, modal=True)

        self.set_title("AutoEQ - Headphone Compensation Browser")
        self.set_default_size(960, 680)
        self.set_size_request(680, 480)
        self.set_resizable(True)

        self.on_load_profile = on_load_profile_callback
        self.current_entry: AutoEQEntry = OFFLINE_AUTOEQ_DATABASE[0]
        self._is_updating = False

        self._build_ui()
        self._update_status_display()
        self._filter_and_populate("")

        # in online mode, ensure database is cached or initiate background sync
        if is_online_mode():
            status = get_autoeq_status()
            if not status.get("cached_index_exists"):
                self._trigger_background_update()

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_content(main_box)

        header = Adw.HeaderBar()

        self.btn_update = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self.btn_update.set_tooltip_text("Update AutoEQ online database from GitHub")
        self.btn_update.connect("clicked", self._on_update_clicked)
        header.pack_end(self.btn_update)

        self.btn_mode = Gtk.Button(label="Online" if is_online_mode() else "Offline")
        self.btn_mode.set_tooltip_text("Toggle between Online and Offline database mode")
        self.btn_mode.connect("clicked", self._on_toggle_mode_clicked)
        header.pack_end(self.btn_mode)

        main_box.append(header)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(340)
        paned.set_shrink_start_child(False)
        paned.set_shrink_end_child(False)
        paned.set_resize_start_child(False)
        paned.set_resize_end_child(True)
        paned.set_hexpand(True)
        paned.set_vexpand(True)
        main_box.append(paned)

        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        left_box.set_margin_start(12)
        left_box.set_margin_end(6)
        left_box.set_margin_top(12)
        left_box.set_margin_bottom(12)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Search headphones (e.g. HD 600, XM4)...")
        self.search_entry.connect("search-changed", self._on_search_changed)
        left_box.append(self.search_entry)

        self.lbl_status = Gtk.Label()
        self.lbl_status.add_css_class("caption")
        self.lbl_status.add_css_class("dim-label")
        self.lbl_status.set_halign(Gtk.Align.START)
        left_box.append(self.lbl_status)

        scrolled_list = Gtk.ScrolledWindow()
        scrolled_list.set_vexpand(True)
        left_box.append(scrolled_list)

        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_box.add_css_class("boxed-list")
        self.list_box.connect("row-selected", self._on_row_selected)
        scrolled_list.set_child(self.list_box)

        paned.set_start_child(left_box)

        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        right_box.set_margin_start(6)
        right_box.set_margin_end(12)
        right_box.set_margin_top(12)
        right_box.set_margin_bottom(12)

        info_frame = Gtk.Frame()
        info_frame.add_css_class("card")
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        info_box.set_margin_start(12)
        info_box.set_margin_end(12)
        info_box.set_margin_top(10)
        info_box.set_margin_bottom(10)

        self.lbl_model_title = Gtk.Label(label="Sennheiser HD 600")
        self.lbl_model_title.add_css_class("title-2")
        self.lbl_model_title.set_halign(Gtk.Align.START)
        info_box.append(self.lbl_model_title)

        self.lbl_meta = Gtk.Label(label="Measurer: oratory1990 | Form: over-ear | Target: Harman")
        self.lbl_meta.add_css_class("caption")
        self.lbl_meta.set_halign(Gtk.Align.START)
        info_box.append(self.lbl_meta)

        self.lbl_preamp = Gtk.Label(label="Recommended Preamp: -6.4 dB")
        self.lbl_preamp.add_css_class("dim-label")
        self.lbl_preamp.set_halign(Gtk.Align.START)
        info_box.append(self.lbl_preamp)

        info_frame.set_child(info_box)
        right_box.append(info_frame)

        preview_frame = Gtk.Frame()
        preview_frame.add_css_class("card")
        preview_frame.set_vexpand(True)
        preview_frame.set_hexpand(True)
        self.curve_preview = FrequencyResponseWidget(min_width=240, min_height=180)
        preview_frame.set_child(self.curve_preview)
        right_box.append(preview_frame)

        action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        action_bar.set_halign(Gtk.Align.END)
        action_bar.set_margin_top(4)

        btn_cancel = Gtk.Button(label="Close")
        btn_cancel.connect("clicked", lambda b: self.close())
        action_bar.append(btn_cancel)

        self.btn_load = Gtk.Button(label="Load into Equalizer")
        self.btn_load.add_css_class("suggested-action")
        self.btn_load.connect("clicked", self._on_apply_clicked)
        action_bar.append(self.btn_load)

        right_box.append(action_bar)

        # scroll container ensures controls remain accessible regardless of window height
        scrolled_right = Gtk.ScrolledWindow()
        scrolled_right.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled_right.set_vexpand(True)
        scrolled_right.set_hexpand(True)
        scrolled_right.set_child(right_box)
        paned.set_end_child(scrolled_right)

    def _update_status_display(self):
        """Update header and status label based on mode and database state."""
        status = get_autoeq_status()
        self.btn_mode.set_label("Online" if status["online"] else "Offline")
        if status["online"]:
            count = status["entry_count"]
            self.lbl_status.set_text(f"Online Mode - {count:,} profiles available")
        else:
            self.lbl_status.set_text("Offline Mode - 20 bundled profiles")

    def _on_toggle_mode_clicked(self, btn):
        """Toggle online/offline mode."""
        current_online = is_online_mode()
        new_mode = "offline" if current_online else "online"
        set_autoeq_mode(new_mode)
        self._update_status_display()
        self._filter_and_populate(self.search_entry.get_text())

    def _on_update_clicked(self, btn):
        """Trigger an on-demand update of the AutoEQ database."""
        self._trigger_background_update()

    def _trigger_background_update(self):
        """Run database update in background thread and refresh UI on completion."""
        if self._is_updating:
            return
        self._is_updating = True
        self.lbl_status.set_text("Updating AutoEQ database from GitHub...")
        self.btn_update.set_sensitive(False)

        def worker():
            update_autoeq_database(force=True)
            def on_done():
                self._is_updating = False
                self.btn_update.set_sensitive(True)
                self._update_status_display()
                self._filter_and_populate(self.search_entry.get_text())
            GLib.idle_add(on_done)

        threading.Thread(target=worker, daemon=True).start()

    def _filter_and_populate(self, query: str):
        """Filter the list box rows by query."""
        while True:
            row = self.list_box.get_first_child()
            if row is None:
                break
            self.list_box.remove(row)

        entries = search_autoeq(query)
        if not entries and query.strip():
            # fetch from github if not in local index
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(10)
            box.set_margin_end(10)
            lbl = Gtk.Label(label=f"Fetch '{query}' from AutoEQ GitHub...")
            lbl.add_css_class("accent")
            lbl.set_halign(Gtk.Align.START)
            box.append(lbl)
            row.set_child(box)
            row._is_fetch_row = True
            row._fetch_query = query
            self.list_box.append(row)
            return

        display_entries = entries[:150]
        for entry in display_entries:
            row = Gtk.ListBoxRow()
            row._entry = entry
            row._is_fetch_row = False

            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.set_margin_top(6)
            box.set_margin_bottom(6)
            box.set_margin_start(10)
            box.set_margin_end(10)

            lbl_name = Gtk.Label(label=f"{entry.brand} {entry.model}")
            lbl_name.set_halign(Gtk.Align.START)
            lbl_name.add_css_class("heading")
            box.append(lbl_name)

            lbl_sub = Gtk.Label(label=f"{entry.form} - {entry.measurer}")
            lbl_sub.set_halign(Gtk.Align.START)
            lbl_sub.add_css_class("caption")
            lbl_sub.add_css_class("dim-label")
            box.append(lbl_sub)

            row.set_child(box)
            self.list_box.append(row)

        if len(entries) > 150:
            info_row = Gtk.ListBoxRow()
            info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            info_box.set_margin_top(6)
            info_box.set_margin_bottom(6)
            info_box.set_margin_start(10)
            info_lbl = Gtk.Label(label=f"... and {len(entries) - 150:,} more. Type to narrow search.")
            info_lbl.add_css_class("dim-label")
            info_lbl.add_css_class("caption")
            info_lbl.set_halign(Gtk.Align.START)
            info_box.append(info_lbl)
            info_row.set_child(info_box)
            info_row.set_activatable(False)
            info_row.set_selectable(False)
            self.list_box.append(info_row)

        first_row = self.list_box.get_first_child()
        if first_row and getattr(first_row, "_entry", None):
            self.list_box.select_row(first_row)

    def _on_search_changed(self, entry):
        text = entry.get_text()
        self._filter_and_populate(text)

    def _on_row_selected(self, list_box, row):
        if not row:
            return

        if getattr(row, "_is_fetch_row", False):
            q = row._fetch_query
            self.lbl_preamp.set_text("Fetching profile from GitHub...")
            def worker():
                fetched = fetch_from_github(q)
                def on_done():
                    if fetched:
                        self.current_entry = fetched
                        self._update_details(fetched)
                    else:
                        self.lbl_preamp.set_text("Could not find profile on GitHub.")
                GLib.idle_add(on_done)
            threading.Thread(target=worker, daemon=True).start()
            return

        entry = getattr(row, "_entry", None)
        if entry:
            self.current_entry = entry
            self._update_details(entry)

    def _update_details(self, entry: AutoEQEntry):
        """Update right pane with entry's data and render preview curve."""
        self.lbl_model_title.set_text(f"{entry.brand} {entry.model}")
        self.lbl_meta.set_text(f"Measurer: {entry.measurer} | Type: {entry.form} | Target: {entry.target}")

        if entry.apo_text:
            config = entry.get_config()
            self.lbl_preamp.set_text(f"Recommended Preamp: {config.preamp_db:+.1f} dB (Bands: {len(config.filters)})")
            self.curve_preview.set_data(config.filters, config.preamp_db)
        else:
            self.lbl_preamp.set_text("Loading curve from online repository...")
            target_entry = entry

            def fetch_worker():
                config = target_entry.get_config()
                def on_done():
                    if self.current_entry == target_entry:
                        self.lbl_preamp.set_text(f"Recommended Preamp: {config.preamp_db:+.1f} dB (Bands: {len(config.filters)})")
                        self.curve_preview.set_data(config.filters, config.preamp_db)
                GLib.idle_add(on_done)

            threading.Thread(target=fetch_worker, daemon=True).start()

    def _on_apply_clicked(self, btn):
        """Apply the selected headphone profile to OpenEQ and close."""
        if self.current_entry:
            config = self.current_entry.get_config()
            profile_name = f"{self.current_entry.brand} {self.current_entry.model}"
            self.on_load_profile(config, profile_name)
            self.close()

