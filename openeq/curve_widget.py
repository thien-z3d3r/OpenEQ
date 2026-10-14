"""
Cairo-based Frequency Response Curve Widget for OpenEQ.

Visualizes the aggregate frequency response (20 Hz - 20 kHz)
and individual filter nodes on a logarithmic frequency scale.
"""

import math
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from .biquad import FilterParams, FilterType, compute_frequency_response


class FrequencyResponseWidget(Gtk.DrawingArea):
    """
    Interactive/responsive frequency response visualization widget.
    Plots gain (dB) vs log frequency (Hz).
    """

    def __init__(self, min_width: int = 240, min_height: int = 160):
        super().__init__()
        self.set_content_width(min_width)
        self.set_content_height(min_height)
        self.set_hexpand(True)
        self.set_vexpand(True)

        self._filters: list[FilterParams] = []
        self._preamp_db: float = 0.0
        self._min_freq = 20.0
        self._max_freq = 20000.0
        self._min_db = -24.0
        self._max_db = 24.0

        self.set_draw_func(self._on_draw)

    def set_data(self, filters: list[FilterParams], preamp_db: float = 0.0):
        """Update filter data and redraw."""
        self._filters = filters
        self._preamp_db = preamp_db
        self.queue_draw()

    def _freq_to_x(self, freq: float, width: float) -> float:
        """Map logarithmic frequency to X pixel coordinate."""
        log_min = math.log10(self._min_freq)
        log_max = math.log10(self._max_freq)
        log_f = math.log10(max(self._min_freq, min(freq, self._max_freq)))
        return ((log_f - log_min) / (log_max - log_min)) * width

    def _db_to_y(self, db: float, height: float) -> float:
        """Map dB to Y pixel coordinate."""
        clamped = max(self._min_db, min(db, self._max_db))
        normalized = (clamped - self._min_db) / (self._max_db - self._min_db)
        return height * (1.0 - normalized)

    def _on_draw(self, area, cr, width, height):
        """Render background, grid, zero line, response curve, and filter nodes."""
        cr.set_source_rgb(0.12, 0.12, 0.15)
        cr.paint()

        grid_freqs = [
            (30, "30"), (50, "50"), (100, "100"), (200, "200"),
            (500, "500"), (1000, "1k"), (2000, "2k"), (5000, "5k"),
            (10000, "10k"), (20000, "20k")
        ]
        cr.set_line_width(1.0)
        cr.set_source_rgba(0.25, 0.25, 0.32, 0.6)

        for freq, label in grid_freqs:
            x = self._freq_to_x(freq, width)
            cr.move_to(x, 0)
            cr.line_to(x, height)
            cr.stroke()

            cr.set_source_rgba(0.6, 0.6, 0.7, 0.8)
            cr.set_font_size(9.0)
            cr.move_to(x + 2, height - 5)
            cr.show_text(label)
            cr.set_source_rgba(0.25, 0.25, 0.32, 0.6)

        db_steps = [-18, -12, -6, 0, 6, 12, 18]
        for db in db_steps:
            y = self._db_to_y(db, height)
            if db == 0:
                # 0 db baseline
                cr.set_source_rgba(0.5, 0.5, 0.6, 0.8)
                cr.set_line_width(1.2)
            else:
                cr.set_source_rgba(0.25, 0.25, 0.32, 0.5)
                cr.set_line_width(0.8)

            cr.move_to(0, y)
            cr.line_to(width, y)
            cr.stroke()

            cr.set_source_rgba(0.6, 0.6, 0.7, 0.8)
            cr.set_font_size(9.0)
            sign = "+" if db > 0 else ""
            cr.move_to(4, y - 2)
            cr.show_text(f"{sign}{db}dB")

        num_points = 256
        freqs, mags = compute_frequency_response(
            self._filters,
            preamp_db=self._preamp_db,
            sample_rate=48000,
            num_points=num_points,
        )

        if freqs and mags:
            cr.save()
            first_x = self._freq_to_x(freqs[0], width)
            first_y = self._db_to_y(mags[0], height)
            zero_y = self._db_to_y(0.0, height)

            cr.move_to(first_x, zero_y)
            for f, m in zip(freqs, mags):
                x = self._freq_to_x(f, width)
                y = self._db_to_y(m, height)
                cr.line_to(x, y)
            last_x = self._freq_to_x(freqs[-1], width)
            cr.line_to(last_x, zero_y)
            cr.close_path()

            cr.set_source_rgba(0.25, 0.55, 0.95, 0.18)
            cr.fill()
            cr.restore()

            cr.set_source_rgb(0.30, 0.72, 1.0)
            cr.set_line_width(2.2)

            cr.move_to(first_x, first_y)
            for f, m in zip(freqs[1:], mags[1:]):
                x = self._freq_to_x(f, width)
                y = self._db_to_y(m, height)
                cr.line_to(x, y)
            cr.stroke()

        for i, fp in enumerate(self._filters):
            if not fp.enabled:
                continue
            x = self._freq_to_x(fp.frequency, width)
            node_db = fp.gain + self._preamp_db
            y = self._db_to_y(node_db, height)

            cr.set_source_rgb(0.95, 0.45, 0.25)
            cr.arc(x, y, 4.5, 0, 2 * math.pi)
            cr.fill()

            cr.set_source_rgb(1.0, 1.0, 1.0)
            cr.set_line_width(1.2)
            cr.arc(x, y, 4.5, 0, 2 * math.pi)
            cr.stroke()

            cr.set_font_size(8.5)
            cr.set_source_rgba(0.9, 0.9, 0.9, 0.85)
            cr.move_to(x - 3, y - 7)
            cr.show_text(str(i + 1))
