"""
Unit tests for OpenEQ core modules:
- APO Parser
- Biquad Calculations
- Frequency Response Calculation
- PipeWire Filter-Chain Config Generation
- Presets Management
"""

import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from openeq.biquad import (
    FilterParams,
    FilterType,
    compute_coefficients,
    compute_frequency_response,
    compute_response_at_frequencies,
)
from openeq.apo_parser import (
    EQConfig,
    parse_apo_config,
    parse_apo_string,
    config_to_apo_string,
)
from openeq.pipewire_backend import (
    generate_filter_chain_config,
)
from openeq import pulseaudio_backend
from openeq.pulseaudio_backend import (
    calculate_mbeq_controls,
    format_controls_string,
    generate_pulseaudio_script,
    MBEQ_FREQUENCIES,
    SINK_NAME,
)
from openeq.presets import (
    BUILTIN_PRESETS,
    Preset,
    list_presets,
    load_preset_by_name,
)
from openeq.autoeq import (
    OFFLINE_AUTOEQ_DATABASE,
    AutoEQEntry,
    search_autoeq,
    get_autoeq_mode,
    set_autoeq_mode,
    is_online_mode,
    get_autoeq_status,
    parse_autoeq_index_md,
    update_autoeq_database,
)


class TestBiquadCalculations(unittest.TestCase):
    def test_peaking_filter_coefficients(self):
        fp = FilterParams(FilterType.PK, frequency=1000.0, gain=6.0, q=1.0)
        c = compute_coefficients(fp, sample_rate=48000)
        # normalized filter should have real non-zero coefficients
        self.assertNotEqual(c.b0, 0.0)
        self.assertNotEqual(c.b1, 0.0)
        self.assertNotEqual(c.a1, 0.0)
        # check stability: poles inside unit circle (|a2| < 1)
        self.assertLess(abs(c.a2), 1.0)

    def test_low_shelf_coefficients(self):
        fp = FilterParams(FilterType.LS, frequency=100.0, gain=4.0, q=0.707)
        c = compute_coefficients(fp, sample_rate=48000)
        self.assertNotEqual(c.b0, 0.0)
        self.assertLess(abs(c.a2), 1.0)

    def test_high_shelf_coefficients(self):
        fp = FilterParams(FilterType.HS, frequency=8000.0, gain=-3.0, q=0.707)
        c = compute_coefficients(fp, sample_rate=48000)
        self.assertNotEqual(c.b0, 0.0)
        self.assertLess(abs(c.a2), 1.0)

    def test_low_pass_coefficients(self):
        fp = FilterParams(FilterType.LP, frequency=5000.0, q=0.707)
        c = compute_coefficients(fp, sample_rate=48000)
        self.assertAlmostEqual(c.b0, c.b2, places=6)
        self.assertLess(abs(c.a2), 1.0)

    def test_bandwidth_to_q_conversion(self):
        fp = FilterParams(FilterType.PK, frequency=1000.0, gain=3.0, bandwidth=1.0)
        eff_q = fp.effective_q()
        # bandwidth of 1 octave corresponds to q ~ 1.414
        self.assertAlmostEqual(eff_q, 1.4142, places=3)

    def test_frequency_response(self):
        # 6 db boost at 1 khz
        fp = FilterParams(FilterType.PK, frequency=1000.0, gain=6.0, q=2.0)
        freqs, mags = compute_frequency_response([fp], preamp_db=0.0, num_points=128)
        self.assertEqual(len(freqs), 128)
        self.assertEqual(len(mags), 128)

        # find closest point to 1000 hz
        closest_idx = min(range(len(freqs)), key=lambda i: abs(freqs[i] - 1000.0))
        # at 1 khz, gain should be close to +6 db
        self.assertAlmostEqual(mags[closest_idx], 6.0, delta=0.5)

class TestAPOParser(unittest.TestCase):
    def test_parse_sample_apo_text(self):
        sample = """
        # equalizer apo sample config
        Preamp: -6.5 dB
        Filter 1: ON PK Fc 50.0 Hz Gain -3.0 dB Q 10.00
        Filter 2: ON PEQ Fc 100.0 Hz Gain 2.5 dB BW Oct 0.167
        Filter 3: OFF LS Fc 300.0 Hz Gain 5.0 dB Q 0.707
        Filter 4: ON HP Fc 30.0 Hz
        """
        config = parse_apo_string(sample)
        self.assertAlmostEqual(config.preamp_db, -6.5)
        self.assertEqual(len(config.filters), 4)

        f1 = config.filters[0]
        self.assertEqual(f1.filter_type, FilterType.PK)
        self.assertEqual(f1.frequency, 50.0)
        self.assertEqual(f1.gain, -3.0)
        self.assertEqual(f1.q, 10.0)
        self.assertTrue(f1.enabled)

        f2 = config.filters[1]
        self.assertEqual(f2.filter_type, FilterType.PEQ)
        self.assertEqual(f2.bandwidth, 0.167)

        f3 = config.filters[2]
        self.assertFalse(f3.enabled)

        f4 = config.filters[3]
        self.assertEqual(f4.filter_type, FilterType.HP)
        self.assertEqual(f4.frequency, 30.0)

    def test_roundtrip_export(self):
        original = EQConfig(
            preamp_db=-4.0,
            filters=[
                FilterParams(FilterType.PK, 1000.0, gain=3.0, q=1.41, enabled=True),
                FilterParams(FilterType.LS, 100.0, gain=5.0, q=0.71, enabled=True),
            ],
        )
        apo_str = config_to_apo_string(original)
        reloaded = parse_apo_string(apo_str)

        self.assertAlmostEqual(reloaded.preamp_db, original.preamp_db)
        self.assertEqual(len(reloaded.filters), len(original.filters))
        self.assertEqual(reloaded.filters[0].frequency, original.filters[0].frequency)
        self.assertEqual(reloaded.filters[0].gain, original.filters[0].gain)

    def test_parse_preset_files(self):
        presets_dir = Path(__file__).parent.parent / "presets"
        for txt_file in presets_dir.glob("*.txt"):
            config = parse_apo_config(str(txt_file))
            self.assertGreater(len(config.filters), 0, f"Preset {txt_file.name} had 0 filters")


class TestPipeWireBackend(unittest.TestCase):
    def test_generate_filter_chain_json(self):
        config = EQConfig(
            preamp_db=-3.0,
            filters=[
                FilterParams(FilterType.PK, 1000.0, gain=2.5, q=1.41),
                FilterParams(FilterType.LS, 100.0, gain=4.0, q=0.71),
            ],
        )
        conf_str = generate_filter_chain_config(config)
        parsed = json.loads(conf_str)

        self.assertIn("context.modules", parsed)
        args = parsed["context.modules"][0]["args"]
        graph = args["filter.graph"]

        # check nodes: preamp + 2 bands = 3 nodes in serial chain
        self.assertEqual(len(graph["nodes"]), 3)
        # check links: 2 links connecting 3 nodes in series
        self.assertEqual(len(graph["links"]), 2)


class TestPresets(unittest.TestCase):
    def test_builtin_presets_exist(self):
        self.assertIn("Flat", BUILTIN_PRESETS)
        self.assertIn("Bass Boost", BUILTIN_PRESETS)
        self.assertIn("Rock", BUILTIN_PRESETS)
        self.assertIn("V-Shape", BUILTIN_PRESETS)

    def test_load_builtin_by_name(self):
        preset = load_preset_by_name("Bass Boost")
        self.assertIsNotNone(preset)
        self.assertEqual(preset.name, "Bass Boost")
        self.assertGreater(len(preset.config.filters), 0)


class TestAutoEQ(unittest.TestCase):
    def test_database_not_empty(self):
        self.assertGreaterEqual(len(OFFLINE_AUTOEQ_DATABASE), 20)

    def test_all_entries_parse_correctly(self):
        for entry in OFFLINE_AUTOEQ_DATABASE:
            cfg = entry.get_config()
            self.assertGreater(len(cfg.filters), 0, f"{entry.brand} {entry.model} has 0 filters")
            self.assertLess(cfg.preamp_db, 0.0, f"{entry.brand} {entry.model} preamp should be negative")

    def test_search_autoeq(self):
        hd600_results = search_autoeq("HD 600")
        self.assertGreater(len(hd600_results), 0)
        self.assertEqual(hd600_results[0].model, "HD 600")

        sony_results = search_autoeq("Sony")
        self.assertGreater(len(sony_results), 0)

        empty_results = search_autoeq("nonexistentheadphone12345")
        self.assertEqual(len(empty_results), 0)

    def test_lsc_hsc_filter_parsing(self):
        apo_text = (
            "Filter 1: ON LSC Fc 105 Hz Gain 5.5 dB Q 0.70\n"
            "Filter 2: ON HSC Fc 10000 Hz Gain -1.1 dB Q 0.70\n"
        )
        cfg = parse_apo_string(apo_text)
        self.assertEqual(len(cfg.filters), 2)
        self.assertEqual(cfg.filters[0].filter_type, FilterType.LS)
        self.assertEqual(cfg.filters[1].filter_type, FilterType.HS)

    def test_autoeq_mode_toggle(self):
        set_autoeq_mode("offline")
        self.assertEqual(get_autoeq_mode(), "offline")
        self.assertFalse(is_online_mode())

        set_autoeq_mode("online")
        self.assertEqual(get_autoeq_mode(), "online")
        self.assertTrue(is_online_mode())

    def test_parse_autoeq_index_md(self):
        sample_md = (
            "# Index\n"
            "- [Sennheiser HD 600](./oratory1990/over-ear/Sennheiser%20HD%20600) by oratory1990\n"
            "- [Moondrop Blessing 2](./crinacle/711%20in-ear/Moondrop%20Blessing%202) by crinacle on 711\n"
        )
        entries = parse_autoeq_index_md(sample_md)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].brand, "Sennheiser")
        self.assertEqual(entries[0].model, "HD 600")
        self.assertEqual(entries[0].form, "over-ear")
        self.assertEqual(entries[0].measurer, "oratory1990")

        self.assertEqual(entries[1].brand, "Moondrop")
        self.assertEqual(entries[1].model, "Blessing 2")
        self.assertEqual(entries[1].form, "in-ear")
        self.assertEqual(entries[1].measurer, "crinacle")

    def test_get_autoeq_status(self):
        set_autoeq_mode("online")
        status = get_autoeq_status()
        self.assertEqual(status["mode"], "online")
        self.assertTrue(status["online"])
        self.assertIn("entry_count", status)


class TestPulseAudioBackend(unittest.TestCase):
    def setUp(self):
        self.sample_config = EQConfig(
            preamp_db=-3.0,
            filters=[
                FilterParams(FilterType.PK, frequency=1000.0, gain=6.0, q=1.41),
                FilterParams(FilterType.LS, frequency=100.0, gain=4.0, q=0.71),
            ],
        )

    def test_calculate_mbeq_controls(self):
        controls = calculate_mbeq_controls(self.sample_config)
        self.assertEqual(len(controls), 15)
        # verify all controls are within valid ladspa bounds [-70, +30] db
        for c in controls:
            self.assertGreaterEqual(c, -70.0)
            self.assertLessEqual(c, 30.0)

        # preamp is -3.0 db, ls at 100hz should boost 50hz and 100hz above preamp
        idx_100hz = MBEQ_FREQUENCIES.index(100.0)
        self.assertGreater(controls[idx_100hz], -3.0)

        # pk at 1000hz should boost adjacent frequencies (880hz and 1250hz)
        idx_880hz = MBEQ_FREQUENCIES.index(880.0)
        self.assertGreater(controls[idx_880hz], 0.0)

    def test_format_controls_string(self):
        ctrls = [1.5, -2.25, 0.0]
        formatted = format_controls_string(ctrls)
        self.assertEqual(formatted, "1.50,-2.25,0.00")

    def test_generate_pulseaudio_script(self):
        script = generate_pulseaudio_script(
            self.sample_config,
            master_sink="alsa_output.pci.stereo",
            sink_name="openeq_sink",
        )
        self.assertIn("load-module module-ladspa-sink", script)
        self.assertIn("sink_name=openeq_sink", script)
        self.assertIn("sink_master=alsa_output.pci.stereo", script)
        self.assertIn("plugin=mbeq_1197", script)
        self.assertIn("set-default-sink openeq_sink", script)

    def test_state_management(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_state_file = Path(tmpdir) / "state.json"
            from unittest.mock import patch
            with patch("openeq.pulseaudio_backend._STATE_FILE", test_state_file), \
                 patch("openeq.pulseaudio_backend._CONFIG_DIR", Path(tmpdir)):
                pulseaudio_backend.save_state({"master_sink": "test_sink", "module_id": 42})
                state = pulseaudio_backend.load_state()
                self.assertEqual(state.get("master_sink"), "test_sink")
                self.assertEqual(state.get("module_id"), 42)

                pulseaudio_backend.clear_state()
                cleared = pulseaudio_backend.load_state()
                self.assertEqual(cleared, {})

    @patch("subprocess.run")
    def test_get_pulseaudio_info_parsing(self, mock_run):
        mock_pactl_info = (
            "Server String: /run/user/1000/pulse/native\n"
            "Server Name: pulseaudio\n"
            "Server Version: 16.1\n"
            "Default Sink: alsa_output.pci-0000.analog\n"
        )
        mock_pactl_sinks = (
            "1\talsa_output.pci-0000.analog\tmodule-alsa-card.c\ts16le 2ch 44100Hz\tIDLE\n"
            "2\topeneq_sink\tmodule-ladspa-sink.c\tfloat32le 2ch 48000Hz\tRUNNING\n"
        )

        def side_effect(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            if "info" in cmd:
                m.stdout = mock_pactl_info
            elif "sinks" in cmd:
                m.stdout = mock_pactl_sinks
            elif "modules" in cmd:
                m.stdout = "Module #23\n\tName: module-ladspa-sink\n\tArgument: sink_name=openeq_sink\n"
            else:
                m.stdout = ""
            return m

        from unittest.mock import MagicMock
        mock_run.side_effect = side_effect

        info = pulseaudio_backend.get_pulseaudio_info()
        self.assertTrue(info["available"])
        self.assertTrue(info["is_native_pulse"])
        self.assertEqual(info["server_name"], "pulseaudio")
        self.assertEqual(info["version"], "16.1")
        self.assertIn("openeq_sink", info["sinks"])
        self.assertTrue(info["eq_active"])

    @patch("subprocess.run")
    def test_apply_and_remove_eq_pulseaudio(self, mock_run):
        from unittest.mock import MagicMock
        def side_effect(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            if "load-module" in cmd:
                m.stdout = "105\n"
            elif "sinks" in cmd:
                m.stdout = "1\talsa_output.analog\n"
            elif "info" in cmd:
                m.stdout = "Default Sink: alsa_output.analog\n"
            else:
                m.stdout = ""
            return m

        mock_run.side_effect = side_effect

        with tempfile.TemporaryDirectory() as tmpdir:
            from unittest.mock import patch
            with patch("openeq.pulseaudio_backend._STATE_FILE", Path(tmpdir) / "state.json"), \
                 patch("openeq.pulseaudio_backend._PULSE_CONF_FILE", Path(tmpdir) / "eq.pa"), \
                 patch("openeq.pulseaudio_backend._CONFIG_DIR", Path(tmpdir)):
                success = pulseaudio_backend.apply_eq(self.sample_config)
                self.assertTrue(success)

                # remove
                removed = pulseaudio_backend.remove_eq()
                self.assertTrue(removed)


class TestBackendRouter(unittest.TestCase):
    def test_canonicalize_backend_name(self):
        from openeq.backend import _canonicalize_backend_name
        self.assertEqual(_canonicalize_backend_name("pw"), "pipewire")
        self.assertEqual(_canonicalize_backend_name("PIPEWIRE"), "pipewire")
        self.assertEqual(_canonicalize_backend_name("pa"), "pulseaudio")
        self.assertEqual(_canonicalize_backend_name("pulse"), "pulseaudio")
        self.assertEqual(_canonicalize_backend_name("auto"), "auto")

    @patch("subprocess.run")
    def test_detect_backend_pipewire(self, mock_run):
        from unittest.mock import MagicMock
        from openeq import backend
        m = MagicMock()
        m.returncode = 0
        m.stdout = "Server Name: PulseAudio (on PipeWire 1.6.9)\n"
        mock_run.return_value = m

        detected = backend.detect_backend()
        self.assertEqual(detected, "pipewire")

    @patch("subprocess.run")
    def test_detect_backend_native_pulse(self, mock_run):
        from unittest.mock import MagicMock
        from openeq import backend
        m = MagicMock()
        m.returncode = 0
        m.stdout = "Server Name: pulseaudio\n"
        mock_run.return_value = m

        detected = backend.detect_backend()
        self.assertEqual(detected, "pulseaudio")

    def test_get_active_backend_precedence(self):
        from openeq import backend
        # explicit override wins
        self.assertEqual(backend.get_active_backend_name("pulse"), "pulseaudio")
        self.assertEqual(backend.get_active_backend_name("pipewire"), "pipewire")

        # openeq_backend env var wins over auto
        with patch.dict(os.environ, {"OPENEQ_BACKEND": "pulseaudio"}):
            self.assertEqual(backend.get_active_backend_name(), "pulseaudio")

        with patch.dict(os.environ, {"OPENEQ_BACKEND": "pipewire"}):
            self.assertEqual(backend.get_active_backend_name(), "pipewire")

    def test_get_backend_modules(self):
        from openeq import backend
        pw_mod = backend.get_backend("pipewire")
        pa_mod = backend.get_backend("pulseaudio")
        self.assertEqual(pw_mod.__name__, "openeq.pipewire_backend")
        self.assertEqual(pa_mod.__name__, "openeq.pulseaudio_backend")

    def test_backend_settings_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_cfg = Path(tmpdir) / "config.json"
            from unittest.mock import patch
            from openeq import backend
            with patch("openeq.backend._SETTINGS_FILE", test_cfg), \
                 patch("openeq.backend._CONFIG_DIR", Path(tmpdir)):
                backend.save_backend_preference("pulseaudio")
                pref = backend.get_backend_preference()
                self.assertEqual(pref, "pulseaudio")

                backend.save_backend_preference("pipewire")
                pref = backend.get_backend_preference()
                self.assertEqual(pref, "pipewire")


class TestCLICommands(unittest.TestCase):
    def test_dump_pw(self):
        from io import StringIO
        import sys
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            from openeq.cli import main
            ret = main(["dump-pw", "Bass Boost"])
            output = sys.stdout.getvalue()
            self.assertEqual(ret, 0)
            self.assertIn("libpipewire-module-filter-chain", output)
        finally:
            sys.stdout = old_stdout

    def test_dump_pa(self):
        from io import StringIO
        import sys
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            from openeq.cli import main
            ret = main(["dump-pa", "Bass Boost"])
            output = sys.stdout.getvalue()
            self.assertEqual(ret, 0)
            self.assertIn("module-ladspa-sink", output)
            self.assertIn("mbeq_1197", output)
        finally:
            sys.stdout = old_stdout

    def test_backend_get_cli(self):
        from io import StringIO
        import sys
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            from openeq.cli import main
            ret = main(["backend", "get"])
            output = sys.stdout.getvalue()
            self.assertEqual(ret, 0)
            self.assertIn("Backend Preference:", output)
            self.assertIn("Active Detected:", output)
        finally:
            sys.stdout = old_stdout

    def test_backend_set_cli(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from unittest.mock import patch
            with patch("openeq.backend._SETTINGS_FILE", Path(tmpdir) / "config.json"), \
                 patch("openeq.backend._CONFIG_DIR", Path(tmpdir)):
                from openeq.cli import main
                ret = main(["backend", "set", "pulseaudio"])
                self.assertEqual(ret, 0)
                from openeq.backend import get_backend_preference
                self.assertEqual(get_backend_preference(), "pulseaudio")



if __name__ == "__main__":
    unittest.main()
