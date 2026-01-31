import dearpygui.dearpygui as dpg

from pathlib import Path
import math
import json
import time

from squidbilli.keybindings import Actions, default_keybindings
from squidbilli.library import TrackLibrary, default_cache_root, track_id_for_path
from squidbilli.stems import StemManager
from squidbilli.dj_proxy import DJProxy
from squidbilli.synth_proxy import SynthProxy


class UI:
    def __init__(self, transport_a, transport_b, mixer_state, stem_manager_a, stem_manager_b, audio, ingest=None):
        self.transport_a = transport_a
        self.transport_b = transport_b
        self.mixer_state = mixer_state
        self.stem_manager = stem_manager_a
        self.deck_b = stem_manager_b
        self.audio = audio
        self.ingest = ingest
        self._deck_b_cue_samples = 0

        self.keybindings = default_keybindings()
        self.library = TrackLibrary(cache_root=default_cache_root())
        self.library.add_folder(Path.home() / "Music")
        self.library.scan()

        self._space_key = getattr(dpg, "mvKey_Spacebar", getattr(dpg, "mvKey_Space", None))
        self._waveform_plotted = False
        self._deck_b_waveform_plotted = False
        self._updating_position_slider = False
        self._last_library_refresh = 0.0
        self._zoom_window_sec = 8.0
        self._zoom_points = 800
        self._last_zoom_update = 0.0

        self._last_deck_a_playhead_draw = 0.0
        self._last_deck_b_playhead_draw = 0.0
        self._last_waveform_debug_draw = 0.0
        self._last_deck_a_waveform_draw = 0.0
        self._last_deck_b_waveform_draw = 0.0
        self._last_deck_a_zoom_draw = 0.0
        self._last_deck_b_zoom_draw = 0.0

        self._overview_cache_key_a = None
        self._overview_cache_key_b = None
        self._zoom_cache_key_a = None
        self._zoom_cache_key_b = None

        self._debug_mode = False
        self._font_default = None

        self._vim_pending = None
        self._vim_pending_time = 0.0

        self._cmd_mode = None
        self._cmd_deck = None
        self._cmd_lane = None
        self._cmd_kind = None

        self._drag_target = None
        self._drag_last_y = None
        self._drag_step = 0.005

        self._tutorial = None
        self._tutorial_loaded_path = None
        self._tutorial_running = False
        self._tutorial_start_time = 0.0
        self._tutorial_next_idx = 0
        self._tutorial_actions = []
        self._tutorial_name = ""

        self._tutorial_recording = False
        self._tutorial_record_start = 0.0
        self._tutorial_recorded_actions = []

        self._clip_theme_default = None
        self._clip_theme_pending = None
        self._clip_theme_active = None
        self._clip_theme_stop_pending = None
        self._scene_theme_default = None
        self._scene_theme_a = None
        self._scene_theme_b = None
        self._scene_theme_ab = None
        self._last_clip_grid_refresh = 0.0

        self._clip_grid_deck = "A"

        self._deck_a_clip_page = 0
        self._deck_a_follow_page = True

        self._stem_eq_panel = "A"

        self._ingest_last_state = None
        self._ingest_last_track_id = None

        self._default_live_code = (
            "synth.enable(True)\n"
            "synth.gain(0.7)\n"
            "synth.lane_gain(0, 1.0)\n"
            "synth.lane_pan(0, -0.15)\n"
            "synth.lane_gain(1, 0.8)\n"
            "synth.lane_pan(1, 0.15)\n"
            "\n"
            "synth.set_pattern(0, 'C2 ~ C2 ~ C2 ~ C2 ~')\n"
            "synth.set_pattern(1, 'E4 G4 A4 G4 E4 ~ ~ ~')\n"
            "\n"
            "synth.set_patch(0, osc='saw', amp=0.7, cutoff=1400.0, attack=0.005, decay=0.08, sustain=0.0, release=0.08)\n"
            "synth.set_patch(1, osc='square', amp=0.3, cutoff=4000.0)\n"
            "\n"
            "# Beatmatch helpers (audio-worker-backed)\n"
            "# dj.beatmatch('A', 'B')\n"
            "# dj.jump_bars('A', 4)\n"
            "# dj.jump_beats('B', -4)\n"
        )
        try:
            candidates = [Path("default.sqbl"), (default_cache_root() / "default.sqbl")]
            for p in candidates:
                try:
                    if p.exists() and p.is_file():
                        self._default_live_code = p.read_text()
                        break
                except Exception:
                    continue
        except Exception:
            pass

    def setup(self):
        dpg.create_context()

        try:
            with dpg.font_registry():
                font_candidates = [
                    "/System/Library/Fonts/Helvetica.ttc",
                    "/System/Library/Fonts/HelveticaNeue.ttc",
                    "/System/Library/Fonts/Supplemental/Helvetica.ttf",
                    "/System/Library/Fonts/Supplemental/Arial.ttf",
                ]
                for p in font_candidates:
                    try:
                        if Path(p).exists():
                            self._font_default = dpg.add_font(p, 16)
                            break
                    except Exception:
                        continue
        except Exception:
            self._font_default = None

        dpg.create_viewport(title="SquidBilli: Octo-laned DJ Stem Mixer", width=1280, height=800)

        if self._font_default is not None:
            try:
                dpg.bind_font(self._font_default)
            except Exception:
                pass

        try:
            with dpg.theme() as self._clip_theme_default:
                with dpg.theme_component(dpg.mvButton):
                    dpg.add_theme_color(dpg.mvThemeCol_Button, (60, 60, 60, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (80, 80, 80, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (100, 100, 100, 255))

            with dpg.theme() as self._clip_theme_pending:
                with dpg.theme_component(dpg.mvButton):
                    dpg.add_theme_color(dpg.mvThemeCol_Button, (180, 120, 0, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (210, 145, 0, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (230, 165, 0, 255))

            with dpg.theme() as self._clip_theme_active:
                with dpg.theme_component(dpg.mvButton):
                    dpg.add_theme_color(dpg.mvThemeCol_Button, (0, 150, 90, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (0, 175, 105, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (0, 195, 120, 255))

            with dpg.theme() as self._clip_theme_stop_pending:
                with dpg.theme_component(dpg.mvButton):
                    dpg.add_theme_color(dpg.mvThemeCol_Button, (150, 40, 40, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (175, 55, 55, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (195, 70, 70, 255))

            with dpg.theme() as self._scene_theme_default:
                with dpg.theme_component(dpg.mvButton):
                    dpg.add_theme_color(dpg.mvThemeCol_Button, (50, 50, 50, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (70, 70, 70, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (90, 90, 90, 255))

            with dpg.theme() as self._scene_theme_a:
                with dpg.theme_component(dpg.mvButton):
                    dpg.add_theme_color(dpg.mvThemeCol_Button, (95, 60, 190, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (120, 80, 215, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (140, 95, 235, 255))

            with dpg.theme() as self._scene_theme_b:
                with dpg.theme_component(dpg.mvButton):
                    dpg.add_theme_color(dpg.mvThemeCol_Button, (30, 120, 190, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (45, 145, 215, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (60, 165, 235, 255))

            with dpg.theme() as self._scene_theme_ab:
                with dpg.theme_component(dpg.mvButton):
                    dpg.add_theme_color(dpg.mvThemeCol_Button, (180, 180, 180, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (210, 210, 210, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (235, 235, 235, 255))
        except Exception:
            self._clip_theme_default = None
            self._clip_theme_pending = None
            self._clip_theme_active = None
            self._clip_theme_stop_pending = None
            self._scene_theme_default = None
            self._scene_theme_a = None
            self._scene_theme_b = None
            self._scene_theme_ab = None

        with dpg.handler_registry():
            dpg.add_key_press_handler(callback=self.key_press_callback)
            dpg.add_key_down_handler(callback=self.key_down_callback)
            dpg.add_mouse_move_handler(callback=self._mouse_move_callback)

        with dpg.file_dialog(
            directory_selector=False,
            show=False,
            callback=self._tutorial_file_selected,
            tag="tutorial_file_dialog",
            width=720,
            height=420,
        ):
            dpg.add_file_extension(".json")

        with dpg.file_dialog(
            directory_selector=False,
            show=False,
            callback=self._audio_file_selected,
            tag="audio_file_dialog",
            width=720,
            height=420,
        ):
            dpg.add_file_extension(".mp3")
            dpg.add_file_extension(".wav")
            dpg.add_file_extension(".aiff")
            dpg.add_file_extension(".aif")
            dpg.add_file_extension(".flac")
            dpg.add_file_extension(".m4a")

        with dpg.window(tag="Primary Window"):
            with dpg.group(horizontal=True):
                dpg.add_text("SquidBilli")
                dpg.add_button(label="Load Track", callback=self.load_track_callback)
                dpg.add_button(label="Separate Stems", callback=self.separate_callback)
                dpg.add_button(label="Help (Cmd+Shift+?)", callback=self._toggle_help)
                dpg.add_text("Status: Idle", tag="status_text")

            dpg.add_text("", tag="debug_status", color=(160, 160, 160, 255))

            dpg.add_separator()

            with dpg.tab_bar(tag="main_tabs"):
                with dpg.tab(label="Mixing", tag="tab_mixing"):
                    with dpg.collapsing_header(label="Tutorial", default_open=False):
                        with dpg.group(horizontal=True):
                            dpg.add_button(label="Load Tutorial JSON", callback=self.tutorial_load_callback)
                            dpg.add_button(label="Start", callback=self.tutorial_start_callback)
                            dpg.add_button(label="Stop", callback=self.tutorial_stop_callback)
                            dpg.add_button(label="Record", callback=self.tutorial_record_start_callback)
                            dpg.add_button(label="Stop Rec", callback=self.tutorial_record_stop_callback)
                            dpg.add_button(label="Clear Rec", callback=self.tutorial_record_clear_callback)
                        dpg.add_text("None", tag="tutorial_status")

                        dpg.add_input_text(tag="tutorial_record_output", multiline=True, readonly=True, height=160, width=1180)

                    with dpg.collapsing_header(label="Waveform", default_open=True):
                        with dpg.group(horizontal=True):
                            dpg.add_button(label="Rebuild Waveform", callback=self.waveform_rebuild)
                            dpg.add_slider_float(
                                tag="position_slider",
                                label="Pos",
                                default_value=0.0,
                                min_value=0.0,
                                max_value=1.0,
                                width=420,
                                callback=self.position_slider_callback,
                            )

                        with dpg.group(horizontal=True):
                            with dpg.group():
                                dpg.add_text("Deck A")
                                with dpg.group():
                                    dpg.add_drawlist(tag="deck_a_overview", width=1035, height=70)
                                    dpg.add_drawlist(tag="deck_a_zoom", width=1035, height=140)

                                dpg.add_text("Deck B")
                                with dpg.group():
                                    dpg.add_drawlist(tag="deck_b_overview", width=1035, height=70)
                                    dpg.add_drawlist(tag="deck_b_zoom", width=1035, height=140)

                            with dpg.group():
                                dpg.add_text("DJ")
                                dpg.add_button(label="Beatmatch A→B", width=150, callback=self._dj_beatmatch_a_to_b)
                                dpg.add_button(label="Beatmatch B→A", width=150, callback=self._dj_beatmatch_b_to_a)
                                dpg.add_separator()
                                dpg.add_button(label="Nudge B -10ms", width=150, callback=lambda: self._dj_nudge_ms("B", -10.0))
                                dpg.add_button(label="Nudge B +10ms", width=150, callback=lambda: self._dj_nudge_ms("B", 10.0))
                                dpg.add_separator()
                                dpg.add_button(label="Bend B -", width=150, callback=lambda: self._dj_bend("B", 0.99))
                                dpg.add_button(label="Bend B +", width=150, callback=lambda: self._dj_bend("B", 1.01))
                                dpg.add_button(label="Bend B =", width=150, callback=lambda: self._dj_bend("B", 1.0))

                        with dpg.item_handler_registry(tag="deck_a_overview_handlers"):
                            dpg.add_item_clicked_handler(callback=self.deck_a_overview_clicked)
                        dpg.bind_item_handler_registry("deck_a_overview", "deck_a_overview_handlers")

                        with dpg.item_handler_registry(tag="deck_a_zoom_handlers"):
                            dpg.add_item_clicked_handler(callback=self.deck_a_zoom_clicked)
                        dpg.bind_item_handler_registry("deck_a_zoom", "deck_a_zoom_handlers")

                        with dpg.item_handler_registry(tag="deck_b_overview_handlers"):
                            dpg.add_item_clicked_handler(callback=self.deck_b_overview_clicked)
                        dpg.bind_item_handler_registry("deck_b_overview", "deck_b_overview_handlers")

                        with dpg.item_handler_registry(tag="deck_b_zoom_handlers"):
                            dpg.add_item_clicked_handler(callback=self.deck_b_zoom_clicked)
                        dpg.bind_item_handler_registry("deck_b_zoom", "deck_b_zoom_handlers")

                        with dpg.group(horizontal=True):
                            dpg.add_button(label="Play/Pause A (Space)", callback=self.toggle_play_a)
                            dpg.add_button(label="Play/Pause B", callback=self.toggle_play_b)
                            dpg.add_text("BPM:")
                            dpg.add_button(label="-", width=30, callback=lambda: self._set_bpm_both(self.transport_a.bpm - 1.0))
                            dpg.add_slider_float(tag="bpm_slider", width=220, min_value=40.0, max_value=220.0, default_value=float(self.transport_a.bpm), callback=self.bpm_callback)
                            dpg.add_button(label="+", width=30, callback=lambda: self._set_bpm_both(self.transport_a.bpm + 1.0))
                            dpg.add_text("", tag="bpm_readout")
                            dpg.add_text("XFade:")
                            dpg.add_slider_float(tag="crossfade_slider", width=200, min_value=0.0, max_value=1.0, default_value=float(getattr(self.mixer_state, "deck_crossfade", 0.0)), callback=self.crossfade_callback)
                            dpg.add_text("Stem:")
                            dpg.add_slider_float(tag="stem_blend_slider", width=160, min_value=0.0, max_value=1.0, default_value=float(getattr(self.mixer_state, "stem_blend", 1.0)), callback=self.stem_blend_callback)
                            dpg.add_text("Master:")
                            dpg.add_slider_float(tag="master_gain_slider", width=180, min_value=0.0, max_value=2.0, default_value=float(getattr(self.mixer_state, "master_gain", 1.0)), callback=self.master_gain_callback)
                            dpg.add_text("Bar: 1.1.1", tag="transport_text")

                            dpg.add_button(label="-1s", callback=lambda: self.jump_seconds(-1.0))
                            dpg.add_button(label="-4s", callback=lambda: self.jump_seconds(-4.0))
                            dpg.add_button(label="-16s", callback=lambda: self.jump_seconds(-16.0))

                    with dpg.collapsing_header(label="Library", default_open=True):
                        with dpg.group(horizontal=True):
                            dpg.add_input_text(tag="library_folder", default_value=str(Path.home() / "Music"), width=500)
                            dpg.add_button(label="Add Folder", callback=self.library_add_folder_callback)
                            dpg.add_button(label="Scan", callback=self.library_scan_callback)

                        with dpg.group(horizontal=True):
                            dpg.add_input_text(tag="library_search", hint="search...", width=500, callback=self.library_search_callback)
                            dpg.add_button(label="Load Selected (Enter)", callback=self.library_load_selected)
                            dpg.add_button(label="Load to B", callback=self.library_load_selected_to_b)

                            dpg.add_text("Key:")
                            dpg.add_color_button(tag="library_key_color", default_value=(0, 0, 0, 255), width=18, height=18)
                            dpg.add_text("--", tag="library_key_text")

                        with dpg.group(horizontal=True):
                            dpg.add_input_text(tag="ingest_url", hint="SoundCloud/URL...", width=740)
                            dpg.add_button(label="Import URL", callback=self._ingest_import_url_clicked)
                        dpg.add_text("", tag="ingest_status", color=(160, 160, 160, 255))

                        dpg.add_listbox(tag="library_list", items=[], num_items=12, width=900, callback=self.library_select_callback)
                        self.library_refresh_listbox()

                    with dpg.collapsing_header(label="Patterns", default_open=True):
                        dpg.add_text("Per-lane bar patterns (Tidal-ish): tokens 1-8 or ~")
                        with dpg.group(horizontal=True):
                            dpg.add_button(label="Apply Patterns", callback=self.patterns_apply_callback)
                            dpg.add_button(label="Clear Patterns", callback=self.patterns_clear_callback)

                        with dpg.group(horizontal=True):
                            with dpg.group():
                                dpg.add_text("d1")
                                dpg.add_input_text(tag="pat_0", width=240, default_value="")
                                dpg.add_text("d2")
                                dpg.add_input_text(tag="pat_1", width=240, default_value="")
                                dpg.add_text("d3")
                                dpg.add_input_text(tag="pat_2", width=240, default_value="")
                                dpg.add_text("d4")
                                dpg.add_input_text(tag="pat_3", width=240, default_value="")

                            with dpg.group():
                                dpg.add_text("d5")
                                dpg.add_input_text(tag="pat_4", width=240, default_value="")
                                dpg.add_text("d6")
                                dpg.add_input_text(tag="pat_5", width=240, default_value="")
                                dpg.add_text("d7")
                                dpg.add_input_text(tag="pat_6", width=240, default_value="")
                                dpg.add_text("d8")
                                dpg.add_input_text(tag="pat_7", width=240, default_value="")

                    with dpg.collapsing_header(label="Scenes (A/B)", default_open=True):
                        dpg.add_text("Select Scene A / Scene B and morph between them")
                        with dpg.group(horizontal=True):
                            dpg.add_text("A:")
                            for s in range(8):
                                dpg.add_button(label=f"A{s+1}", width=45, callback=self.scene_a_callback, user_data=s)
                        with dpg.group(horizontal=True):
                            dpg.add_text("B:")
                            for s in range(8):
                                dpg.add_button(label=f"B{s+1}", width=45, callback=self.scene_b_callback, user_data=s)

                        with dpg.group(horizontal=True):
                            dpg.add_text("A:")
                            dpg.add_text("--", tag="scene_a_sel")
                            dpg.add_button(label="Store A", callback=self.scene_store_a_callback)
                            dpg.add_text("B:")
                            dpg.add_text("--", tag="scene_b_sel")
                            dpg.add_button(label="Store B", callback=self.scene_store_b_callback)
                            dpg.add_text("Morph:")
                            dpg.add_slider_float(tag="scene_morph_slider", width=260, min_value=0.0, max_value=1.0, default_value=float(getattr(self.mixer_state, "scene_xfade", 0.0)), callback=self.scene_morph_callback)

                    dpg.add_separator()

                    with dpg.group(horizontal=True):
                        dpg.add_text("Stem EQ Panel:")
                        dpg.add_radio_button(
                            items=["Deck A", "Deck B"],
                            horizontal=True,
                            default_value="Deck A",
                            callback=self._stem_eq_panel_changed,
                            tag="stem_eq_panel",
                        )
                        dpg.add_checkbox(
                            label="Clip-only A",
                            tag="clip_only_a",
                            default_value=bool(getattr(self.mixer_state, "clip_only_a", False)),
                            callback=self._clip_only_changed,
                            user_data="A",
                        )
                        dpg.add_checkbox(
                            label="Clip-only B",
                            tag="clip_only_b",
                            default_value=bool(getattr(self.mixer_state, "clip_only_b", False)),
                            callback=self._clip_only_changed,
                            user_data="B",
                        )

                    with dpg.group(horizontal=True):
                        for i in range(8):
                            with dpg.group():
                                dpg.add_text(self.mixer_state.lane_names[i])

                                with dpg.group(horizontal=True):
                                    dpg.add_checkbox(
                                        label="M",
                                        tag=f"mute_{i}",
                                        callback=self.lane_param_callback,
                                        user_data=i,
                                    )
                                    dpg.add_checkbox(
                                        label="S",
                                        tag=f"solo_{i}",
                                        callback=self.lane_param_callback,
                                        user_data=i,
                                    )

                                dpg.add_slider_float(
                                    label="Gain",
                                    tag=f"gain_{i}",
                                    default_value=0.0,
                                    min_value=-60.0,
                                    max_value=6.0,
                                    width=80,
                                    vertical=True,
                                    height=150,
                                    callback=self.lane_param_callback,
                                    user_data=i,
                                )

                                dpg.add_knob_float(
                                    label="Pan",
                                    tag=f"pan_{i}",
                                    default_value=0.0,
                                    min_value=-1.0,
                                    max_value=1.0,
                                    width=80,
                                    callback=self.lane_param_callback,
                                    user_data=i,
                                )

                                dpg.add_knob_float(
                                    label="HP",
                                    tag=f"hp_{i}",
                                    default_value=0.0,
                                    min_value=0.0,
                                    max_value=20000.0,
                                    width=80,
                                    callback=self.lane_param_callback,
                                    user_data=i,
                                )
                                dpg.add_knob_float(
                                    label="LP",
                                    tag=f"lp_{i}",
                                    default_value=20000.0,
                                    min_value=20.0,
                                    max_value=20000.0,
                                    width=80,
                                    callback=self.lane_param_callback,
                                    user_data=i,
                                )

                                dpg.add_knob_float(
                                    label="Rev",
                                    tag=f"rev_{i}",
                                    default_value=0.0,
                                    min_value=0.0,
                                    max_value=1.0,
                                    width=80,
                                    callback=self.lane_param_callback,
                                    user_data=i,
                                )
                                dpg.add_knob_float(
                                    label="Dly",
                                    tag=f"dly_{i}",
                                    default_value=0.0,
                                    min_value=0.0,
                                    max_value=1.0,
                                    width=80,
                                    callback=self.lane_param_callback,
                                    user_data=i,
                                )

                    dpg.add_separator()

                    with dpg.collapsing_header(label="Clip Grid", default_open=True):
                        with dpg.group(horizontal=True):
                            dpg.add_text("Target:")
                            dpg.add_radio_button(
                                items=["Deck A", "Deck B"],
                                horizontal=True,
                                default_value="Deck A",
                                callback=self._clip_grid_deck_changed,
                                tag="clip_grid_deck",
                            )

                        dpg.add_text("Scene arrows: purple=Scene A, blue=Scene B, white=A+B, gray=none")

                        with dpg.group(horizontal=True):
                            dpg.add_text("Deck A Page:")
                            dpg.add_slider_int(
                                tag="deck_a_clip_page",
                                default_value=0,
                                min_value=0,
                                max_value=0,
                                width=200,
                                callback=self._deck_a_clip_page_changed,
                            )
                            dpg.add_checkbox(
                                label="Follow",
                                tag="deck_a_clip_follow",
                                default_value=True,
                                callback=self._deck_a_clip_follow_changed,
                            )

                            dpg.add_text("   Deck B Page:")
                            dpg.add_slider_int(
                                tag="deck_b_clip_page",
                                default_value=0,
                                min_value=0,
                                max_value=0,
                                width=200,
                                callback=self._deck_b_clip_page_changed,
                            )
                            dpg.add_checkbox(
                                label="Follow",
                                tag="deck_b_clip_follow",
                                default_value=True,
                                callback=self._deck_b_clip_follow_changed,
                            )

                        with dpg.group(horizontal=True):
                            dpg.add_text("       ")
                            for i in range(8):
                                dpg.add_text(f"Lane {i+1} ")

                        for r in range(8):
                            with dpg.group(horizontal=True):
                                dpg.add_text(f"Sc {r+1} ")
                                for c in range(8):
                                    dpg.add_button(
                                        label=f"[{c+1}-{r+1}]",
                                        tag=f"clip_btn_{c}_{r}",
                                        width=50,
                                        callback=self.clip_callback,
                                        user_data=(c, r),
                                    )

                                dpg.add_button(label=">", tag=f"scene_btn_{r}", callback=self.scene_callback, user_data=r)

                        with dpg.group(horizontal=True):
                            dpg.add_text("Stop: ")
                            for c in range(8):
                                dpg.add_button(
                                    label="STOP",
                                    tag=f"clip_btn_{c}_-1",
                                    width=50,
                                    callback=self.clip_callback,
                                    user_data=(c, -1),
                                )

                with dpg.tab(label="Live Coding", tag="tab_live_coding"):
                    dpg.add_text("Context available: 'mixer', 'transport', 'stems'")
                    dpg.add_input_text(
                        tag="live_code_input",
                        multiline=True,
                        default_value=str(getattr(self, "_default_live_code", "")),
                        height=300,
                    )
                    dpg.add_button(label="Execute Code", callback=self.eval_callback)
                    dpg.add_text("", tag="eval_status", color=(255, 100, 100))

        with dpg.window(
            tag="help_modal",
            label="SquidBilli Help",
            show=False,
            modal=True,
            no_resize=True,
            width=720,
            height=520,
        ):
            dpg.add_text("Keyboard")
            dpg.add_separator()
            dpg.add_text("Cmd+Shift+?: Toggle this help")
            dpg.add_text("gt / gT: Switch tabs (Mixing <-> Live Coding)")
            dpg.add_separator()
            dpg.add_text("Transport")
            dpg.add_text("Space: Play/Pause Deck A")
            dpg.add_text("Shift+Space: Play/Pause Deck B")
            dpg.add_text("[ / ]: BPM down / up")
            dpg.add_text(",: Jump -1s")
            dpg.add_text("-: Jump -4s")
            dpg.add_text("Backspace: Jump -16s")
            dpg.add_separator()
            dpg.add_text("Library")
            dpg.add_text("F: Focus library search")
            dpg.add_text("Up/Down: Navigate library")
            dpg.add_text("Enter: Load selected track")
            dpg.add_text("Shift+Enter: Load selected to Deck B")
            dpg.add_separator()
            dpg.add_text("Mixer quick toggles")
            dpg.add_text("1-8: Mute lane 1-8 (current Stem EQ Panel)")
            dpg.add_text("Shift+1-8: Solo lane 1-8 (current Stem EQ Panel)")
            dpg.add_separator()
            dpg.add_text("Modal deck command mode (vim-ish)")
            dpg.add_text("Esc: Cancel current command/mode")
            dpg.add_text("a / b: Arm Deck A / Deck B mode")
            dpg.add_text("c: Clips mode   s: Scenes mode   e: DSP mode")
            dpg.add_text("Clips: a|b  [lane 1-8]  [slot 1-8]")
            dpg.add_text("Scenes: a|b  s  [scene 1-8]")
            dpg.add_text("DSP: a|b  e  [lane 1-8]  then one of:")
            dpg.add_text("  g=gain  p=pan  h=HP  l=LP  r=rev  d=dly  u=mute  o=solo")
            dpg.add_text("  then hold left mouse + drag up/down to adjust")
            dpg.add_separator()
            dpg.add_text("Mouse-drag adjust (global)")
            dpg.add_text("x: Arm crossfader drag")
            dpg.add_text("v: Arm stem blend drag")
            dpg.add_text("m: Arm master gain drag")
            dpg.add_separator()
            dpg.add_button(label="Close", width=120, callback=self._toggle_help)

        dpg.set_primary_window("Primary Window", True)
        dpg.setup_dearpygui()
        dpg.show_viewport()

        self._wire_keybindings()
        self._position_debug_window()

    def key_press_callback(self, sender, app_data):
        key = app_data

        try:
            if self._is_help_combo(key):
                self._toggle_help()
                return
        except Exception:
            pass

        if dpg.does_item_exist("live_code_input") and dpg.is_item_focused("live_code_input"):
            esc_key = getattr(dpg, "mvKey_Escape", None)
            allowed = []
            if self._space_key is not None:
                allowed.append(self._space_key)
            if esc_key is not None:
                allowed.append(esc_key)
            # Allow tab switching keys even while editing live code.
            g_key = getattr(dpg, "mvKey_G", None)
            t_key = getattr(dpg, "mvKey_T", None)
            if g_key is not None:
                allowed.append(g_key)
            if t_key is not None:
                allowed.append(t_key)
            allowed.extend([ord("g"), ord("G"), ord("t"), ord("T")])
            if key not in tuple(allowed):
                return

        try:
            if self._handle_modal_keys(key):
                return
        except Exception:
            pass

        try:
            if self._handle_modal_param_key(key):
                return
        except Exception:
            pass

        try:
            if self._handle_vim_tab_keys(key):
                return
        except Exception:
            pass

        self.keybindings.handle_keypress(key)

    def key_down_callback(self, sender, app_data):
        key = app_data
        # Fallback: some focused widgets can suppress key_press events.
        # Keep this handler narrowly scoped to tab switching so we don't double-trigger other actions.
        try:
            self._handle_vim_tab_keys(int(key))
        except Exception:
            pass

    def _handle_modal_keys(self, key: int) -> bool:
        esc_key = getattr(dpg, "mvKey_Escape", None)
        if esc_key is not None and key == esc_key:
            self._cmd_mode = None
            self._cmd_deck = None
            self._cmd_lane = None
            self._cmd_kind = None
            self._drag_target = None
            self._drag_last_y = None
            return True

        # Arm mouse-drag adjustment for continuous controls.
        if key == ord("x") or key == ord("X"):
            self._start_drag("crossfade_slider", step=0.01)
            return True
        if key == ord("v") or key == ord("V"):
            self._start_drag("stem_blend_slider", step=0.01)
            return True
        if key == ord("m") or key == ord("M"):
            self._start_drag("master_gain_slider", step=0.02)
            return True

        # Deck prefix modes.
        if key == ord("a") or key == ord("A"):
            self._cmd_deck = "A"
            self._cmd_mode = "deck"
            self._cmd_kind = "clips"
            self._cmd_lane = None
            return True
        if key == ord("b") or key == ord("B"):
            self._cmd_deck = "B"
            self._cmd_mode = "deck"
            self._cmd_kind = "clips"
            self._cmd_lane = None
            return True

        # Switch kind within deck mode.
        if self._cmd_mode == "deck":
            if key == ord("e") or key == ord("E"):
                self._cmd_kind = "dsp"
                self._cmd_lane = None
                return True
            if key == ord("s") or key == ord("S"):
                self._cmd_kind = "scenes"
                self._cmd_lane = None
                return True
            if key == ord("c") or key == ord("C"):
                self._cmd_kind = "clips"
                self._cmd_lane = None
                return True

        # Digits handling.
        lane = self._digit_1_to_8(key)
        if lane is None:
            return False

        if self._cmd_mode == "deck" and self._cmd_deck in ("A", "B"):
            if self._cmd_kind == "scenes":
                # Scene trigger: deck + s + [1-8]
                try:
                    self._trigger_scene(self._cmd_deck, int(lane), record=True)
                except Exception:
                    pass
                return True

            if self._cmd_kind == "dsp":
                # DSP mode: deck + e + [lane] then [param]
                if self._cmd_lane is None:
                    self._cmd_lane = int(lane)
                    try:
                        if dpg.does_item_exist("stem_eq_panel"):
                            dpg.set_value("stem_eq_panel", "Deck B" if self._cmd_deck == "B" else "Deck A")
                        self._stem_eq_panel = str(self._cmd_deck)
                    except Exception:
                        pass
                    return True
                return True

            # Clip trigger: deck + [lane] + [slot]
            if self._cmd_lane is None:
                self._cmd_lane = int(lane)
                return True
            slot = int(lane)
            try:
                self._queue_clip(self._cmd_deck, int(self._cmd_lane), int(slot), record=True)
            except Exception:
                pass
            self._cmd_lane = None
            return True

        return False

    def _handle_modal_param_key(self, key: int) -> bool:
        if self._cmd_mode != "deck" or self._cmd_kind != "dsp":
            return False
        if self._cmd_deck not in ("A", "B"):
            return False
        if self._cmd_lane is None:
            return False

        lane = int(self._cmd_lane)
        tag = None
        step = None

        if key == ord("g") or key == ord("G"):
            tag = f"gain_{lane}"
            step = 0.03
        elif key == ord("p") or key == ord("P"):
            tag = f"pan_{lane}"
            step = 0.01
        elif key == ord("h") or key == ord("H"):
            tag = f"hp_{lane}"
            step = 0.6
        elif key == ord("l") or key == ord("L"):
            tag = f"lp_{lane}"
            step = 0.6
        elif key == ord("r") or key == ord("R"):
            tag = f"rev_{lane}"
            step = 0.01
        elif key == ord("d") or key == ord("D"):
            tag = f"dly_{lane}"
            step = 0.01
        elif key == ord("u") or key == ord("U"):
            # mute toggle
            try:
                cur = bool(dpg.get_value(f"mute_{lane}"))
            except Exception:
                cur = False
            try:
                dpg.set_value(f"mute_{lane}", not cur)
                self.lane_param_callback(None, None, lane)
            except Exception:
                pass
            self._cmd_lane = None
            return True
        elif key == ord("o") or key == ord("O"):
            # solo toggle
            try:
                cur = bool(dpg.get_value(f"solo_{lane}"))
            except Exception:
                cur = False
            try:
                dpg.set_value(f"solo_{lane}", not cur)
                self.lane_param_callback(None, None, lane)
            except Exception:
                pass
            self._cmd_lane = None
            return True

        if tag is None:
            return False

        try:
            dpg.focus_item(tag)
        except Exception:
            pass
        try:
            self._start_drag(tag, step=float(step or 0.01))
        except Exception:
            pass
        self._cmd_lane = None
        return True

    def _digit_1_to_8(self, key: int):
        try:
            base = int(getattr(dpg, "mvKey_1", 0))
        except Exception:
            base = 0
        if base and base <= key <= (base + 7):
            return int(key - base)
        if ord("1") <= key <= ord("8"):
            return int(key - ord("1"))
        return None

    def _start_drag(self, tag: str, step: float = 0.01):
        if not dpg.does_item_exist(tag):
            return
        self._drag_target = str(tag)
        self._drag_step = float(step)
        self._drag_last_y = None

    def _mouse_move_callback(self, sender, app_data):
        if self._drag_target is None:
            return
        if not dpg.does_item_exist(self._drag_target):
            self._drag_target = None
            self._drag_last_y = None
            return

        try:
            if not dpg.is_mouse_button_down(dpg.mvMouseButton_Left):
                return
        except Exception:
            return

        try:
            x, y = dpg.get_mouse_pos(local=False)
        except Exception:
            return

        if self._drag_last_y is None:
            self._drag_last_y = float(y)
            return

        dy = float(self._drag_last_y) - float(y)
        self._drag_last_y = float(y)
        delta = dy * float(self._drag_step)

        try:
            cur = float(dpg.get_value(self._drag_target))
        except Exception:
            return

        try:
            cfg = dpg.get_item_configuration(self._drag_target)
            mn = float(cfg.get("min_value", 0.0))
            mx = float(cfg.get("max_value", 1.0))
        except Exception:
            mn, mx = (0.0, 1.0)

        new = cur + delta
        if new < mn:
            new = mn
        if new > mx:
            new = mx

        try:
            dpg.set_value(self._drag_target, float(new))
        except Exception:
            pass

        # Reuse existing callbacks for consistent behavior.
        try:
            if self._drag_target == "crossfade_slider":
                self.crossfade_callback(self._drag_target, float(new))
            elif self._drag_target == "stem_blend_slider":
                self.stem_blend_callback(self._drag_target, float(new))
            elif self._drag_target == "master_gain_slider":
                self.master_gain_callback(self._drag_target, float(new))
        except Exception:
            pass

    def _stem_eq_panel_changed(self, sender, app_data):
        val = str(app_data or "")
        self._stem_eq_panel = "B" if "B" in val else "A"

        deck = str(getattr(self, "_stem_eq_panel", "A") or "A").upper()
        lanes = getattr(self.mixer_state, "lanes_b", self.mixer_state.lanes) if deck == "B" else self.mixer_state.lanes

        for i in range(8):
            try:
                l = lanes[i]
                if dpg.does_item_exist(f"mute_{i}"):
                    dpg.set_value(f"mute_{i}", bool(l.mute))
                if dpg.does_item_exist(f"solo_{i}"):
                    dpg.set_value(f"solo_{i}", bool(l.solo))
                if dpg.does_item_exist(f"gain_{i}"):
                    g = 20.0
                    try:
                        g = 20.0 * float(__import__("math").log10(max(1e-8, float(l.gain))))
                    except Exception:
                        g = 0.0
                    dpg.set_value(f"gain_{i}", float(g))
                if dpg.does_item_exist(f"pan_{i}"):
                    dpg.set_value(f"pan_{i}", float(l.pan))
                if dpg.does_item_exist(f"hp_{i}"):
                    dpg.set_value(f"hp_{i}", float(l.hp_cutoff))
                if dpg.does_item_exist(f"lp_{i}"):
                    dpg.set_value(f"lp_{i}", float(l.lp_cutoff))
                if dpg.does_item_exist(f"rev_{i}"):
                    dpg.set_value(f"rev_{i}", float(l.send_reverb))
                if dpg.does_item_exist(f"dly_{i}"):
                    dpg.set_value(f"dly_{i}", float(l.send_delay))
            except Exception:
                pass

    def _clip_only_changed(self, sender, app_data, user_data):
        deck = str(user_data or "A").upper()
        val = bool(app_data)
        try:
            with self.mixer_state.lock:
                if deck == "B":
                    setattr(self.mixer_state, "clip_only_b", bool(val))
                else:
                    setattr(self.mixer_state, "clip_only_a", bool(val))
        except Exception:
            pass

        try:
            if self.audio is not None:
                self.audio.set_mixer_values(
                    clip_only_a=bool(getattr(self.mixer_state, "clip_only_a", False)),
                    clip_only_b=bool(getattr(self.mixer_state, "clip_only_b", False)),
                )
        except Exception:
            pass

        try:
            self._tutorial_record_action({"type": "clip_only", "deck": str(deck).upper(), "value": bool(val)})
        except Exception:
            pass

    def _handle_vim_tab_keys(self, key: int) -> bool:
        now = time.time()
        timeout_sec = 0.75

        if self._vim_pending is not None and (now - float(self._vim_pending_time)) > timeout_sec:
            self._vim_pending = None

        g_key = getattr(dpg, "mvKey_G", ord("G"))
        t_key = getattr(dpg, "mvKey_T", ord("T"))
        if key == g_key or key == ord("g") or key == ord("G"):
            self._vim_pending = "g"
            self._vim_pending_time = now
            return True

        if self._vim_pending == "g":
            self._vim_pending = None
            if key == t_key or key == ord("t") or key == ord("T"):
                shift_down = (hasattr(dpg, "mvKey_LShift") and dpg.is_key_down(dpg.mvKey_LShift)) or (
                    hasattr(dpg, "mvKey_RShift") and dpg.is_key_down(dpg.mvKey_RShift)
                )
                if shift_down or key == ord("T"):
                    self._select_prev_tab()
                else:
                    self._select_next_tab()
                return True
        return False

    def _select_next_tab(self):
        current = None
        try:
            current = dpg.get_value("main_tabs") if dpg.does_item_exist("main_tabs") else None
        except Exception:
            current = None

        # DPG tab_bar value can be the tab label ("Mixing") or the tab tag ("tab_mixing").
        if current in ("tab_mixing", "Mixing"):
            self._select_tab("tab_live_coding")
        else:
            self._select_tab("tab_mixing")

    def _select_prev_tab(self):
        self._select_next_tab()

    def _select_tab(self, tab_tag: str):
        if not dpg.does_item_exist("main_tabs"):
            return
        # Prefer setting by tag, but fall back to label if needed.
        ok = False
        try:
            dpg.set_value("main_tabs", tab_tag)
            ok = True
        except Exception:
            ok = False

        if not ok:
            try:
                label = "Live Coding" if tab_tag == "tab_live_coding" else "Mixing"
                dpg.set_value("main_tabs", label)
            except Exception:
                pass

        try:
            tab_name = "Live Coding" if tab_tag == "tab_live_coding" else "Mixing"
            self._tutorial_record_action({"type": "tab", "tab": tab_name})
        except Exception:
            pass

    def _is_cmd_down(self) -> bool:
        lcmd = getattr(dpg, "mvKey_LSuper", getattr(dpg, "mvKey_LWin", None))
        rcmd = getattr(dpg, "mvKey_RSuper", getattr(dpg, "mvKey_RWin", None))
        down = False
        if lcmd is not None:
            down = down or bool(dpg.is_key_down(lcmd))
        if rcmd is not None:
            down = down or bool(dpg.is_key_down(rcmd))
        return bool(down)

    def _is_help_combo(self, key: int) -> bool:
        if not self._is_cmd_down():
            return False
        shift_down = (hasattr(dpg, "mvKey_LShift") and dpg.is_key_down(dpg.mvKey_LShift)) or (
            hasattr(dpg, "mvKey_RShift") and dpg.is_key_down(dpg.mvKey_RShift)
        )
        if not shift_down:
            return False
        slash_key = getattr(dpg, "mvKey_Slash", ord("/"))
        qmark_key = getattr(dpg, "mvKey_Question", ord("?"))
        return key in (slash_key, qmark_key, ord("?"), ord("/"))

    def _toggle_help(self):
        if not dpg.does_item_exist("help_modal"):
            return
        show = bool(dpg.is_item_shown("help_modal"))
        dpg.configure_item("help_modal", show=(not show))

    def run(self):
        while dpg.is_dearpygui_running():
            self.update_loop()
            dpg.render_dearpygui_frame()
        dpg.destroy_context()

    def update_loop(self):
        try:
            st = self.audio.poll_status() if self.audio is not None else None
        except Exception:
            st = None

        try:
            ist = self.ingest.poll_status() if self.ingest is not None else None
        except Exception:
            ist = None

        if ist is not None:
            try:
                if dpg.does_item_exist("ingest_status"):
                    msg = f"Ingest: {getattr(ist, 'state', '')} - {getattr(ist, 'message', '')}"
                    dpg.set_value("ingest_status", msg)
            except Exception:
                pass

            try:
                state = str(getattr(ist, "state", ""))
                track_id = getattr(ist, "track_id", None)
                if state == "done" and track_id and track_id != self._ingest_last_track_id:
                    self._ingest_last_track_id = track_id
                    self.library.scan()
                    self.library_refresh_listbox()
            except Exception:
                pass

        if st is not None:
            try:
                self.transport_a.playing = bool(st.playing_a)
                self.transport_b.playing = bool(st.playing_b)
                self.transport_a.play_head_samples = int(st.playhead_a)
                self.transport_b.play_head_samples = int(st.playhead_b)
                self.transport_a.set_bpm(float(st.bpm))
                self.transport_b.set_bpm(float(st.bpm))
            except Exception:
                pass

            # Sync clip state from audio worker so UI playheads/active clips match audio.
            try:
                cm_a = self._get_clip_manager_for_deck("A")
                if cm_a is not None:
                    cm_a.active_clip_indices = list(getattr(st, "active_clips_a", cm_a.active_clip_indices))
                    cm_a.pending_clip_indices = list(getattr(st, "pending_clips_a", cm_a.pending_clip_indices))
                    cm_a.clip_playheads = list(getattr(st, "clip_playheads_a", cm_a.clip_playheads))
                    cm_a.current_page = int(getattr(st, "clip_page_a", getattr(cm_a, "current_page", 0)))
                    try:
                        mgr_a = self.stem_manager
                        if getattr(mgr_a, "full_mix", None) is not None:
                            cm_a.set_page(
                                int(getattr(cm_a, "current_page", 0)),
                                total_samples=int(mgr_a.full_mix.shape[0]),
                                sample_rate=int(getattr(self.transport_a, "sample_rate", 44100)),
                                bpm=float(getattr(self.transport_a, "bpm", 120.0)),
                                bars_per_slot=8,
                                slots_per_page=8,
                            )
                    except Exception:
                        pass
            except Exception:
                pass

            try:
                cm_b = self._get_clip_manager_for_deck("B")
                if cm_b is not None:
                    cm_b.active_clip_indices = list(getattr(st, "active_clips_b", cm_b.active_clip_indices))
                    cm_b.pending_clip_indices = list(getattr(st, "pending_clips_b", cm_b.pending_clip_indices))
                    cm_b.clip_playheads = list(getattr(st, "clip_playheads_b", cm_b.clip_playheads))
                    cm_b.current_page = int(getattr(st, "clip_page_b", getattr(cm_b, "current_page", 0)))
                    try:
                        mgr_b = self.deck_b
                        if getattr(mgr_b, "full_mix", None) is not None:
                            cm_b.set_page(
                                int(getattr(cm_b, "current_page", 0)),
                                total_samples=int(mgr_b.full_mix.shape[0]),
                                sample_rate=int(getattr(self.transport_b, "sample_rate", 44100)),
                                bpm=float(getattr(self.transport_b, "bpm", 120.0)),
                                bars_per_slot=8,
                                slots_per_page=8,
                            )
                    except Exception:
                        pass
            except Exception:
                pass

            # Keep Deck A page control reflecting current track length/bpm and worker page.
            try:
                max_p = int(self._deck_a_max_page())
                if dpg.does_item_exist("deck_a_clip_page"):
                    dpg.configure_item("deck_a_clip_page", max_value=int(max_p))
                p = int(getattr(st, "clip_page_a", getattr(self, "_deck_a_clip_page", 0)))
                if p < 0:
                    p = 0
                if p > max_p:
                    p = max_p
                self._deck_a_clip_page = int(p)
                if dpg.does_item_exist("deck_a_clip_page"):
                    dpg.set_value("deck_a_clip_page", int(p))
            except Exception:
                pass

        self._tutorial_tick()

        bar_a, beat_a, phase_a = self.transport_a.get_beat_info()
        bar_b, beat_b, phase_b = self.transport_b.get_beat_info()
        dpg.set_value("transport_text", f"Bar: {bar_a}.{beat_a}")

        now = time.time()
        if now - self._last_library_refresh >= 1.0:
            self._last_library_refresh = now
            self.library_refresh_listbox()

        if getattr(self.stem_manager, "waveform_ready", False):
            if (not self._waveform_plotted) or (now - self._last_deck_a_waveform_draw > 0.75):
                if self._render_deck_overview("A"):
                    self._waveform_plotted = True
                    self._last_deck_a_waveform_draw = now
            if now - self._last_deck_a_zoom_draw > 0.0625:
                if self._render_deck_zoom("A"):
                    self._last_deck_a_zoom_draw = now

        if getattr(self.deck_b, "waveform_ready", False):
            if (not self._deck_b_waveform_plotted) or (now - self._last_deck_b_waveform_draw > 0.769):
                if self._render_deck_overview("B"):
                    self._deck_b_waveform_plotted = True
                    self._last_deck_b_waveform_draw = now
            if now - self._last_deck_b_zoom_draw > 0.0625:
                if self._render_deck_zoom("B"):
                    self._last_deck_b_zoom_draw = now

        if self._debug_mode:
            self._render_waveform_debug()

        if dpg.does_item_exist("bpm_slider"):
            dpg.set_value("bpm_slider", float(self.transport_a.bpm))
        if dpg.does_item_exist("bpm_readout"):
            dpg.set_value("bpm_readout", f"{float(self.transport_a.bpm):.1f}")
        self._position_debug_window()

        # Keep playhead/cue overlays in sync
        if self.stem_manager.full_mix is not None:
            self._render_deck_overlay("A")
        if self.deck_b.full_mix is not None:
            self._render_deck_overlay("B")

        self._update_status_text(st)
        self._update_debug_status(st)

        self._refresh_clip_grid_colors()

        try:
            self._maybe_follow_deck_a_clip_page()
        except Exception:
            pass

        try:
            self._maybe_follow_deck_b_clip_page()
        except Exception:
            pass

    def _ingest_import_url_clicked(self, sender, app_data):
        if self.ingest is None:
            return
        if not dpg.does_item_exist("ingest_url"):
            return
        try:
            url = str(dpg.get_value("ingest_url") or "").strip()
        except Exception:
            url = ""
        if not url:
            return
        try:
            self.ingest.import_url(url)
            if dpg.does_item_exist("ingest_status"):
                dpg.set_value("ingest_status", "Ingest: queued")
        except Exception:
            pass

    def _update_debug_status(self, st):
        if not dpg.does_item_exist("debug_status"):
            return
        try:
            have_status = st is not None
            a_ready = bool(getattr(self.stem_manager, "waveform_ready", False))
            b_ready = bool(getattr(self.deck_b, "waveform_ready", False))
            a_play = bool(getattr(self.transport_a, "playing", False))
            b_play = bool(getattr(self.transport_b, "playing", False))
            a_ph = int(getattr(self.transport_a, "play_head_samples", 0))
            b_ph = int(getattr(self.transport_b, "play_head_samples", 0))
            msg = (
                f"dbg status={'Y' if have_status else 'N'}  "
                f"A play={'Y' if a_play else 'N'} ph={a_ph} wf={'Y' if a_ready else 'N'}  "
                f"B play={'Y' if b_play else 'N'} ph={b_ph} wf={'Y' if b_ready else 'N'}"
            )
            dpg.set_value("debug_status", msg)
        except Exception:
            pass

    def _spinner_char(self) -> str:
        seq = "|/-\\"
        try:
            i = int(time.time() * 8.0) % len(seq)
        except Exception:
            i = 0
        return seq[i]

    def _deck_status(self, deck: str) -> tuple[str, str]:
        mgr = self.stem_manager if deck == "A" else self.deck_b
        if getattr(mgr, "is_loading", False):
            return ("loading", "Loading")
        if getattr(mgr, "is_separating", False):
            return ("separating", "Separating")
        if getattr(mgr, "stems_ready", False):
            return ("ready", "Ready")
        if getattr(mgr, "full_mix", None) is not None:
            return ("loaded", "Loaded")
        return ("idle", "Idle")

    def _update_status_text(self, st):
        audio_ready = st is not None
        spin = self._spinner_char()

        a_state, a_label = self._deck_status("A")
        b_state, b_label = self._deck_status("B")

        if audio_ready:
            audio_label = "Audio: Ready"
        else:
            audio_label = f"Audio: Starting {spin}"

        a_txt = f"A: {a_label}"
        if a_state in ("loading", "separating"):
            a_txt = f"A: {a_label} {spin}"

        b_txt = f"B: {b_label}"
        if b_state in ("loading", "separating"):
            b_txt = f"B: {b_label} {spin}"

        msg = f"{audio_label}   {a_txt}   {b_txt}"
        if dpg.does_item_exist("status_text"):
            dpg.set_value("status_text", msg)

            color = (255, 210, 120, 255)
            if audio_ready and a_state in ("ready", "loaded", "idle") and b_state in ("ready", "loaded", "idle"):
                if a_state in ("ready", "loaded") or b_state in ("ready", "loaded"):
                    color = (120, 255, 160, 255)
            if not audio_ready:
                color = (255, 180, 90, 255)
            if a_state in ("loading", "separating") or b_state in ("loading", "separating"):
                color = (255, 210, 120, 255)
            try:
                dpg.configure_item("status_text", color=color)
            except Exception:
                pass

    def _clip_grid_deck_changed(self, sender, app_data):
        val = str(app_data or "")
        self._clip_grid_deck = "B" if "B" in val else "A"
        try:
            self._refresh_clip_grid_colors()
        except Exception:
            pass

    def _get_clip_manager_for_deck(self, deck: str):
        deck = str(deck or "A").upper()
        if deck == "B":
            return getattr(self.deck_b, "clip_manager", None)
        return getattr(self.stem_manager, "clip_manager", None)

    def _deck_a_slot_len_samples(self) -> int:
        sr = getattr(self.transport_a, "sample_rate", 44100)
        bpm = float(getattr(self.transport_a, "bpm", 120.0) or 120.0)
        if bpm <= 1e-3:
            bpm = 120.0
        bar_samples = int((60.0 / bpm) * 4.0 * float(sr))
        return max(1, int(bar_samples) * 8)

    def _deck_a_max_page(self) -> int:
        total = self._deck_total_samples("A")
        if total <= 0:
            return 0
        slot_len = self._deck_a_slot_len_samples()
        slots_per_page = 8
        page_len = slot_len * slots_per_page
        if page_len <= 0:
            return 0
        return max(0, int((total - 1) // page_len))

    def _apply_deck_a_clip_page(self, page: int, *, push_audio: bool = True):
        try:
            p = int(page)
        except Exception:
            p = 0
        if p < 0:
            p = 0
        max_p = self._deck_a_max_page()
        if p > max_p:
            p = max_p

        self._deck_a_clip_page = int(p)
        if dpg.does_item_exist("deck_a_clip_page"):
            try:
                dpg.configure_item("deck_a_clip_page", max_value=int(max_p))
                dpg.set_value("deck_a_clip_page", int(p))
            except Exception:
                pass

        cm = self._get_clip_manager_for_deck("A")
        mgr = self.stem_manager
        if cm is not None and getattr(mgr, "full_mix", None) is not None:
            try:
                cm.set_page(
                    int(p),
                    total_samples=int(mgr.full_mix.shape[0]),
                    sample_rate=int(getattr(self.transport_a, "sample_rate", 44100)),
                    bpm=float(getattr(self.transport_a, "bpm", 120.0)),
                    bars_per_slot=8,
                    slots_per_page=8,
                )
            except Exception:
                pass

        # Clear pad colors immediately on page switch (avoid stale active/pending from previous page)
        if cm is not None:
            try:
                cm.pending_clip_indices = [-2] * 8
                cm.active_clip_indices = [-1] * 8
                cm.scene_a = -1
                cm.scene_b = -1
            except Exception:
                pass

        try:
            for r in range(8):
                tag = f"scene_btn_{r}"
                if dpg.does_item_exist(tag) and self._scene_theme_default is not None:
                    dpg.bind_item_theme(tag, self._scene_theme_default)
            for lane in range(8):
                for slot in range(8):
                    tag = f"clip_btn_{lane}_{slot}"
                    if dpg.does_item_exist(tag) and self._clip_theme_default is not None:
                        dpg.bind_item_theme(tag, self._clip_theme_default)
                stop_tag = f"clip_btn_{lane}_-1"
                if dpg.does_item_exist(stop_tag) and self._clip_theme_default is not None:
                    dpg.bind_item_theme(stop_tag, self._clip_theme_default)
        except Exception:
            pass

        if push_audio and self.audio is not None:
            try:
                self.audio.set_clip_page("A", int(p))
            except Exception:
                pass

        try:
            self._refresh_clip_grid_colors()
        except Exception:
            pass
        try:
            self._waveform_plotted = False
        except Exception:
            pass

    def _deck_a_clip_page_changed(self, sender, app_data):
        try:
            self._deck_a_follow_page = False
            if dpg.does_item_exist("deck_a_clip_follow"):
                dpg.set_value("deck_a_clip_follow", False)
        except Exception:
            pass
        self._apply_deck_a_clip_page(int(app_data), push_audio=True)
        try:
            self._tutorial_record_action({"type": "clip_page", "deck": "A", "page": int(app_data)})
        except Exception:
            pass

    def _deck_a_clip_follow_changed(self, sender, app_data):
        self._deck_a_follow_page = bool(app_data)
        try:
            self._tutorial_record_action({"type": "clip_follow", "deck": "A", "value": bool(app_data)})
        except Exception:
            pass

    def _deck_b_slot_len_samples(self) -> int:
        sr = getattr(self.transport_b, "sample_rate", 44100)
        bpm = float(getattr(self.transport_b, "bpm", 120.0) or 120.0)
        if bpm <= 1e-3:
            bpm = 120.0
        bar_samples = int((60.0 / bpm) * 4.0 * float(sr))
        return max(1, int(bar_samples) * 8)

    def _deck_b_max_page(self) -> int:
        total = self._deck_total_samples("B")
        if total <= 0:
            return 0
        slot_len = self._deck_b_slot_len_samples()
        slots_per_page = 8
        page_len = slot_len * slots_per_page
        if page_len <= 0:
            return 0
        return max(0, int((total - 1) // page_len))

    def _apply_deck_b_clip_page(self, page: int, *, push_audio: bool = True):
        try:
            p = int(page)
        except Exception:
            p = 0
        if p < 0:
            p = 0
        max_p = self._deck_b_max_page()
        if p > max_p:
            p = max_p

        self._deck_b_clip_page = int(p)
        if dpg.does_item_exist("deck_b_clip_page"):
            try:
                dpg.configure_item("deck_b_clip_page", max_value=int(max_p))
                dpg.set_value("deck_b_clip_page", int(p))
            except Exception:
                pass

        cm = self._get_clip_manager_for_deck("B")
        mgr = self.deck_b
        if cm is not None and getattr(mgr, "full_mix", None) is not None:
            try:
                cm.set_page(
                    int(p),
                    total_samples=int(mgr.full_mix.shape[0]),
                    sample_rate=int(getattr(self.transport_b, "sample_rate", 44100)),
                    bpm=float(getattr(self.transport_b, "bpm", 120.0)),
                    bars_per_slot=8,
                    slots_per_page=8,
                )
            except Exception:
                pass

        if cm is not None:
            try:
                cm.pending_clip_indices = [-2] * 8
                cm.active_clip_indices = [-1] * 8
                cm.scene_a = -1
                cm.scene_b = -1
            except Exception:
                pass

        try:
            for r in range(8):
                tag = f"scene_btn_{r}"
                if dpg.does_item_exist(tag) and self._scene_theme_default is not None:
                    dpg.bind_item_theme(tag, self._scene_theme_default)
            for lane in range(8):
                for slot in range(8):
                    tag = f"clip_btn_{lane}_{slot}"
                    if dpg.does_item_exist(tag) and self._clip_theme_default is not None:
                        dpg.bind_item_theme(tag, self._clip_theme_default)
                stop_tag = f"clip_btn_{lane}_-1"
                if dpg.does_item_exist(stop_tag) and self._clip_theme_default is not None:
                    dpg.bind_item_theme(stop_tag, self._clip_theme_default)
        except Exception:
            pass

        if push_audio and self.audio is not None:
            try:
                self.audio.set_clip_page("B", int(p))
            except Exception:
                pass

        try:
            self._refresh_clip_grid_colors()
        except Exception:
            pass
        try:
            self._deck_b_waveform_plotted = False
        except Exception:
            pass

    def _deck_b_clip_page_changed(self, sender, app_data):
        try:
            self._deck_b_follow_page = False
            if dpg.does_item_exist("deck_b_clip_follow"):
                dpg.set_value("deck_b_clip_follow", False)
        except Exception:
            pass
        self._apply_deck_b_clip_page(int(app_data), push_audio=True)
        try:
            self._tutorial_record_action({"type": "clip_page", "deck": "B", "page": int(app_data)})
        except Exception:
            pass

    def _deck_b_clip_follow_changed(self, sender, app_data):
        self._deck_b_follow_page = bool(app_data)
        try:
            self._tutorial_record_action({"type": "clip_follow", "deck": "B", "value": bool(app_data)})
        except Exception:
            pass

    def _maybe_follow_deck_b_clip_page(self):
        if not bool(getattr(self, "_deck_b_follow_page", True)):
            return
        total = self._deck_total_samples("B")
        if total <= 0:
            return
        slot_len = self._deck_b_slot_len_samples()
        slots_per_page = 8
        page_len = slot_len * slots_per_page
        if page_len <= 0:
            return
        ph = int(getattr(self.transport_b, "play_head_samples", 0))
        new_page = int(max(0, ph) // page_len)
        if int(new_page) != int(getattr(self, "_deck_b_clip_page", 0)):
            self._apply_deck_b_clip_page(int(new_page), push_audio=True)

    def _maybe_follow_deck_a_clip_page(self):
        if not bool(getattr(self, "_deck_a_follow_page", True)):
            return
        total = self._deck_total_samples("A")
        if total <= 0:
            return
        slot_len = self._deck_a_slot_len_samples()
        slots_per_page = 8
        page_len = slot_len * slots_per_page
        if page_len <= 0:
            return
        ph = int(getattr(self.transport_a, "play_head_samples", 0))
        new_page = int(max(0, ph) // page_len)
        if int(new_page) != int(getattr(self, "_deck_a_clip_page", 0)):
            self._apply_deck_a_clip_page(int(new_page), push_audio=True)

    def _queue_clip(self, deck: str, lane: int, slot: int, *, record: bool = True):
        mgr = self.stem_manager if str(deck).upper() == "A" else self.deck_b
        tr = self.transport_a if str(deck).upper() == "A" else self.transport_b

        try:
            if (not bool(tr.playing)) and getattr(mgr, "full_mix", None) is not None:
                tr.start()
                if self.audio is not None:
                    self.audio.play(str(deck).upper(), True)
        except Exception:
            pass

        cm = self._get_clip_manager_for_deck(deck)
        if cm is not None:
            try:
                lane_i = int(lane)
                slot_i = int(slot)
                pending = int(cm.pending_clip_indices[lane_i])
                active = int(cm.active_clip_indices[lane_i])

                # Toggle off if user clicks the same queued target again.
                if pending == slot_i:
                    cm.pending_clip_indices[lane_i] = -2
                else:
                    # Optional: if clicking an already-active slot, treat it like "stop".
                    if slot_i == active:
                        cm.pending_clip_indices[lane_i] = -1
                    else:
                        cm.queue_clip(lane_i, slot_i)
            except Exception:
                try:
                    cm.queue_clip(int(lane), int(slot))
                except Exception:
                    pass

        try:
            if self.audio is not None:
                self.audio.queue_clip(str(deck).upper(), int(lane), int(slot))
        except Exception:
            pass

        if record:
            try:
                self._tutorial_record_action({"type": "queue_clip", "deck": str(deck).upper(), "lane": int(lane), "slot": int(slot)})
            except Exception:
                pass

        try:
            self._refresh_clip_grid_colors()
        except Exception:
            pass

    def _trigger_scene(self, deck: str, scene: int, *, record: bool = True):
        mgr = self.stem_manager if str(deck).upper() == "A" else self.deck_b
        tr = self.transport_a if str(deck).upper() == "A" else self.transport_b

        try:
            if (not bool(tr.playing)) and getattr(mgr, "full_mix", None) is not None:
                tr.start()
                if self.audio is not None:
                    self.audio.play(str(deck).upper(), True)
        except Exception:
            pass

        cm = self._get_clip_manager_for_deck(deck)
        if cm is not None:
            try:
                cm.trigger_scene(int(scene))
            except Exception:
                pass

        try:
            if self.audio is not None:
                self.audio.trigger_scene(str(deck).upper(), int(scene))
        except Exception:
            pass

        if record:
            try:
                self._tutorial_record_action({"type": "trigger_scene", "deck": str(deck).upper(), "scene": int(scene)})
            except Exception:
                pass

        try:
            self._refresh_clip_grid_colors()
        except Exception:
            pass

    def _refresh_clip_grid_colors(self):
        cm = self._get_clip_manager_for_deck(self._clip_grid_deck)
        if cm is None:
            return
        now = time.time()
        if now - self._last_clip_grid_refresh < 0.05:
            return
        self._last_clip_grid_refresh = now

        pending = list(getattr(cm, "pending_clip_indices", [-2] * 8))
        active = list(getattr(cm, "active_clip_indices", [-1] * 8))

        scene_a = int(getattr(cm, "scene_a", -1))
        scene_b = int(getattr(cm, "scene_b", -1))
        for r in range(8):
            tag = f"scene_btn_{r}"
            if not dpg.does_item_exist(tag):
                continue
            theme = self._scene_theme_default
            if r == scene_a and r == scene_b:
                theme = self._scene_theme_ab
            elif r == scene_a:
                theme = self._scene_theme_a
            elif r == scene_b:
                theme = self._scene_theme_b
            if theme is not None:
                try:
                    dpg.bind_item_theme(tag, theme)
                except Exception:
                    pass

        for lane in range(8):
            p = int(pending[lane]) if lane < len(pending) else -2
            a = int(active[lane]) if lane < len(active) else -1
            for slot in range(8):
                tag = f"clip_btn_{lane}_{slot}"
                if not dpg.does_item_exist(tag):
                    continue
                theme = self._clip_theme_default
                if a == slot:
                    theme = self._clip_theme_active
                elif p == slot:
                    theme = self._clip_theme_pending
                if theme is not None:
                    try:
                        dpg.bind_item_theme(tag, theme)
                    except Exception:
                        pass

            stop_tag = f"clip_btn_{lane}_-1"
            if dpg.does_item_exist(stop_tag):
                theme = self._clip_theme_default
                if p == -1:
                    theme = self._clip_theme_stop_pending
                if theme is not None:
                    try:
                        dpg.bind_item_theme(stop_tag, theme)
                    except Exception:
                        pass

    def tutorial_load_callback(self):
        if dpg.does_item_exist("tutorial_file_dialog"):
            dpg.configure_item("tutorial_file_dialog", show=True)

    def _tutorial_file_selected(self, sender, app_data):
        try:
            file_path = str(app_data.get("file_path_name") or "")
        except Exception:
            file_path = ""
        if not file_path:
            return
        try:
            data = json.loads(Path(file_path).read_text())
        except Exception:
            return

        self._tutorial_loaded_path = str(file_path)
        self._tutorial_name = str(data.get("name") or Path(file_path).stem)
        self._tutorial_actions = list(data.get("actions") or [])
        self._tutorial_next_idx = 0
        self._tutorial_running = False

        init = data.get("init") or {}
        try:
            self._tutorial_apply_init(init)
        except Exception:
            pass

        if dpg.does_item_exist("tutorial_status"):
            dpg.set_value("tutorial_status", f"Loaded: {self._tutorial_name} ({len(self._tutorial_actions)} actions)")
            try:
                dpg.configure_item("tutorial_status", color=(220, 220, 220))
            except Exception:
                pass

    def tutorial_start_callback(self):
        if not self._tutorial_actions:
            if dpg.does_item_exist("tutorial_status"):
                dpg.set_value("tutorial_status", "No tutorial loaded")
            return
        self._tutorial_running = True
        self._tutorial_start_time = time.monotonic()
        self._tutorial_next_idx = 0
        if dpg.does_item_exist("tutorial_status"):
            dpg.set_value("tutorial_status", f"Running: {self._tutorial_name}")

    def tutorial_stop_callback(self):
        self._tutorial_running = False
        if dpg.does_item_exist("tutorial_status"):
            dpg.set_value("tutorial_status", f"Stopped: {self._tutorial_name}")

    def tutorial_record_start_callback(self):
        self._tutorial_recording = True
        self._tutorial_record_start = time.monotonic()
        self._tutorial_recorded_actions = []
        if dpg.does_item_exist("tutorial_status"):
            dpg.set_value("tutorial_status", "Recording tutorial...")
            try:
                dpg.configure_item("tutorial_status", color=(180, 180, 255))
            except Exception:
                pass
        self._tutorial_refresh_record_output()

    def tutorial_record_stop_callback(self):
        self._tutorial_recording = False
        if dpg.does_item_exist("tutorial_status"):
            dpg.set_value("tutorial_status", f"Recorded {len(self._tutorial_recorded_actions)} actions")
            try:
                dpg.configure_item("tutorial_status", color=(220, 220, 220))
            except Exception:
                pass
        self._tutorial_refresh_record_output()

    def tutorial_record_clear_callback(self):
        self._tutorial_recorded_actions = []
        self._tutorial_record_start = time.monotonic()
        self._tutorial_refresh_record_output()

    def _tutorial_record_action(self, action: dict):
        if not self._tutorial_recording:
            return
        try:
            at = float(time.monotonic() - float(self._tutorial_record_start))
        except Exception:
            at = 0.0
        try:
            a = dict(action)
            a["at"] = round(at, 3)
        except Exception:
            return
        self._tutorial_recorded_actions.append(a)
        self._tutorial_refresh_record_output()

    def _tutorial_refresh_record_output(self):
        if not dpg.does_item_exist("tutorial_record_output"):
            return
        try:
            out = {
                "name": "Recorded Tutorial",
                "init": {},
                "actions": list(self._tutorial_recorded_actions),
            }
            dpg.set_value("tutorial_record_output", json.dumps(out, indent=2))
        except Exception:
            pass

    def _tutorial_tick(self):
        if not self._tutorial_running:
            return
        if not self._tutorial_actions:
            return

        elapsed = float(time.monotonic() - float(self._tutorial_start_time))
        if dpg.does_item_exist("tutorial_status"):
            try:
                if self._tutorial_next_idx < len(self._tutorial_actions):
                    nxt = self._tutorial_actions[self._tutorial_next_idx]
                    typ = str(nxt.get("type") or "")
                    dpg.set_value("tutorial_status", f"Running: {self._tutorial_name}  t={elapsed:.2f}s  next={self._tutorial_next_idx+1}/{len(self._tutorial_actions)} {typ}")
            except Exception:
                pass

        while self._tutorial_next_idx < len(self._tutorial_actions):
            action = self._tutorial_actions[self._tutorial_next_idx]
            try:
                at = float(action.get("at", 0.0))
            except Exception:
                at = 0.0
            if elapsed + 1e-6 < at:
                break
            try:
                did = bool(self._tutorial_execute_action(action))
            except Exception:
                did = True
            if not did:
                break
            self._tutorial_next_idx += 1

        if self._tutorial_next_idx >= len(self._tutorial_actions):
            self._tutorial_running = False
            if dpg.does_item_exist("tutorial_status"):
                dpg.set_value("tutorial_status", f"Done: {self._tutorial_name}")
                try:
                    dpg.configure_item("tutorial_status", color=(140, 220, 140))
                except Exception:
                    pass

    def _tutorial_fail(self, message: str):
        self._tutorial_running = False
        if dpg.does_item_exist("tutorial_status"):
            try:
                dpg.set_value("tutorial_status", f"FAIL: {message}")
            except Exception:
                pass
            try:
                dpg.configure_item("tutorial_status", color=(255, 120, 120))
            except Exception:
                pass

    def _tutorial_apply_init(self, init: dict):
        bpm = init.get("bpm")
        if bpm is not None:
            try:
                self._set_bpm_both(float(bpm))
            except Exception:
                pass

        xf = init.get("crossfade")
        if xf is not None:
            try:
                if dpg.does_item_exist("crossfade_slider"):
                    dpg.set_value("crossfade_slider", float(xf))
                self.crossfade_callback("crossfade_slider", float(xf))
            except Exception:
                pass

        stem = init.get("stem_blend")
        if stem is not None:
            try:
                if dpg.does_item_exist("stem_blend_slider"):
                    dpg.set_value("stem_blend_slider", float(stem))
                self.stem_blend_callback("stem_blend_slider", float(stem))
            except Exception:
                pass

        master = init.get("master_gain")
        if master is not None:
            try:
                if dpg.does_item_exist("master_gain_slider"):
                    dpg.set_value("master_gain_slider", float(master))
                self.master_gain_callback("master_gain_slider", float(master))
            except Exception:
                pass

        patterns = init.get("patterns") or {}
        if isinstance(patterns, dict):
            for k, v in patterns.items():
                try:
                    lane = int(k)
                    tag = f"pat_{lane}"
                    if dpg.does_item_exist(tag):
                        dpg.set_value(tag, str(v))
                except Exception:
                    continue
            try:
                self.patterns_apply_callback()
            except Exception:
                pass

        decks = init.get("decks") or {}
        if isinstance(decks, dict):
            for deck, ref in decks.items():
                try:
                    self._tutorial_load_deck(deck=str(deck).upper(), ref=ref)
                except Exception:
                    continue

    def _tutorial_execute_action(self, action: dict):
        t = (action.get("type") or "").strip()

        if t == "assert":
            cond = str(action.get("cond") or "")
            deck = str(action.get("deck", "A")).upper()

            if cond == "stems_ready":
                mgr = self.stem_manager if deck != "B" else self.deck_b
                ok = bool(getattr(mgr, "stems_ready", False))
                if not ok:
                    self._tutorial_fail(f"assert stems_ready failed deck={deck}")
                return True

            if cond == "audio_loaded":
                mgr = self.stem_manager if deck != "B" else self.deck_b
                ok = getattr(mgr, "full_mix", None) is not None
                if not ok:
                    self._tutorial_fail(f"assert audio_loaded failed deck={deck}")
                return True

            if cond == "waveform_ready":
                mgr = self.stem_manager if deck != "B" else self.deck_b
                ok = bool(getattr(mgr, "waveform_ready", False))
                if not ok:
                    self._tutorial_fail(f"assert waveform_ready failed deck={deck}")
                return True

            if cond == "playing":
                want = bool(action.get("value", True))
                tr = self.transport_a if deck != "B" else self.transport_b
                ok = bool(getattr(tr, "playing", False)) == want
                if not ok:
                    self._tutorial_fail(f"assert playing failed deck={deck} want={want}")
                return True

            if cond == "bpm":
                try:
                    want = float(action.get("value"))
                except Exception:
                    want = None
                try:
                    tol = float(action.get("tol", 0.2))
                except Exception:
                    tol = 0.2
                if want is None:
                    self._tutorial_fail("assert bpm missing value")
                    return True
                try:
                    got = float(self.transport_a.bpm)
                except Exception:
                    got = None
                ok = got is not None and abs(float(got) - float(want)) <= float(tol)
                if not ok:
                    self._tutorial_fail(f"assert bpm failed got={got} want={want} tol={tol}")
                return True

            if cond == "tab":
                want = str(action.get("value") or "")
                try:
                    cur = dpg.get_value("main_tabs") if dpg.does_item_exist("main_tabs") else None
                except Exception:
                    cur = None
                cur_name = "Live Coding" if cur == "tab_live_coding" else "Mixing"
                ok = cur_name.lower() == want.strip().lower()
                if not ok:
                    self._tutorial_fail(f"assert tab failed got={cur_name} want={want}")
                return True

            return True

        if t == "wait_for":
            cond = str(action.get("cond") or "")
            if cond == "audio_loaded":
                deck = str(action.get("deck", "A")).upper()
                mgr = self.stem_manager if deck != "B" else self.deck_b
                return getattr(mgr, "full_mix", None) is not None
            if cond == "waveform_ready":
                deck = str(action.get("deck", "A")).upper()
                mgr = self.stem_manager if deck != "B" else self.deck_b
                return bool(getattr(mgr, "waveform_ready", False))
            if cond == "stems_ready":
                deck = str(action.get("deck", "A")).upper()
                mgr = self.stem_manager if deck != "B" else self.deck_b
                return bool(getattr(mgr, "stems_ready", False))
            if cond == "bar_boundary":
                deck = str(action.get("deck", "A")).upper()
                tr = self.transport_a if deck != "B" else self.transport_b
                try:
                    _, _, phase = tr.get_beat_info()
                except Exception:
                    phase = 1.0
                try:
                    tol = float(action.get("tol", 0.06))
                except Exception:
                    tol = 0.06
                return float(phase) <= float(tol)
            return True

        if t == "load_deck":
            deck = str(action.get("deck", "A")).upper()
            ref = action.get("ref")
            self._tutorial_load_deck(deck=deck, ref=ref)
            return True

        if t == "play":
            deck = str(action.get("deck", "A")).upper()
            on = bool(action.get("on", True))
            try:
                if deck == "B":
                    self.transport_b.playing = on
                else:
                    self.transport_a.playing = on
            except Exception:
                pass
            try:
                if self.audio is not None:
                    self.audio.play(deck, on)
            except Exception:
                pass
            return True

        if t == "seek":
            deck = str(action.get("deck", "A")).upper()
            samples = int(action.get("samples", 0))
            try:
                if deck == "B":
                    self.transport_b.seek(max(0, samples))
                else:
                    self.transport_a.seek(max(0, samples))
            except Exception:
                pass
            try:
                if self.audio is not None:
                    self.audio.seek(deck, int(samples))
            except Exception:
                pass
            return True

        if t == "set":
            tag = str(action.get("tag") or "")
            if not tag:
                return True
            if not dpg.does_item_exist(tag):
                return True
            value = action.get("value")
            dpg.set_value(tag, value)
            return True

        if t == "set_lane":
            deck = str(action.get("deck", "A") or "A").upper()
            lane = int(action.get("lane", 0))
            gain = action.get("gain_db")
            pan = action.get("pan")
            hp = action.get("hp")
            lp = action.get("lp")
            rev = action.get("rev")
            dly = action.get("dly")
            mute = action.get("mute")
            solo = action.get("solo")

            try:
                if dpg.does_item_exist("stem_eq_panel"):
                    dpg.set_value("stem_eq_panel", "Deck B" if deck == "B" else "Deck A")
                self._stem_eq_panel = "B" if deck == "B" else "A"
            except Exception:
                pass

            if gain is not None and dpg.does_item_exist(f"gain_{lane}"):
                dpg.set_value(f"gain_{lane}", float(gain))
            if pan is not None and dpg.does_item_exist(f"pan_{lane}"):
                dpg.set_value(f"pan_{lane}", float(pan))
            if hp is not None and dpg.does_item_exist(f"hp_{lane}"):
                dpg.set_value(f"hp_{lane}", float(hp))
            if lp is not None and dpg.does_item_exist(f"lp_{lane}"):
                dpg.set_value(f"lp_{lane}", float(lp))
            if rev is not None and dpg.does_item_exist(f"rev_{lane}"):
                dpg.set_value(f"rev_{lane}", float(rev))
            if dly is not None and dpg.does_item_exist(f"dly_{lane}"):
                dpg.set_value(f"dly_{lane}", float(dly))
            if mute is not None and dpg.does_item_exist(f"mute_{lane}"):
                dpg.set_value(f"mute_{lane}", bool(mute))
            if solo is not None and dpg.does_item_exist(f"solo_{lane}"):
                dpg.set_value(f"solo_{lane}", bool(solo))

            try:
                self.lane_param_callback(None, None, lane)
            except Exception:
                pass
            return True

        if t == "clip_only":
            deck = str(action.get("deck", "A") or "A").upper()
            val = bool(action.get("value", False))
            tag = "clip_only_b" if deck == "B" else "clip_only_a"
            if dpg.does_item_exist(tag):
                dpg.set_value(tag, bool(val))
            try:
                self._clip_only_changed(None, bool(val), deck)
            except Exception:
                pass
            return True

        if t == "clip_page":
            deck = str(action.get("deck", "A") or "A").upper()
            page = int(action.get("page", 0))
            if deck == "A":
                if dpg.does_item_exist("deck_a_clip_page"):
                    dpg.set_value("deck_a_clip_page", int(page))
                self._deck_a_clip_page_changed(None, int(page))
            elif deck == "B":
                if dpg.does_item_exist("deck_b_clip_page"):
                    dpg.set_value("deck_b_clip_page", int(page))
                self._deck_b_clip_page_changed(None, int(page))
            return True

        if t == "clip_follow":
            deck = str(action.get("deck", "A") or "A").upper()
            val = bool(action.get("value", True))
            if deck == "A":
                if dpg.does_item_exist("deck_a_clip_follow"):
                    dpg.set_value("deck_a_clip_follow", bool(val))
                self._deck_a_clip_follow_changed(None, bool(val))
            elif deck == "B":
                if dpg.does_item_exist("deck_b_clip_follow"):
                    dpg.set_value("deck_b_clip_follow", bool(val))
                self._deck_b_clip_follow_changed(None, bool(val))
            return True

        if t == "beatmatch":
            src = str(action.get("src", "A") or "A").upper()
            dst = str(action.get("dst", "B") or "B").upper()
            try:
                if self.audio is not None:
                    self.audio.beatmatch(src=src, dst=dst)
            except Exception:
                pass
            return True

        if t == "nudge":
            deck = str(action.get("deck", "A") or "A").upper()
            samples = int(action.get("samples", 0))
            try:
                if self.audio is not None:
                    self.audio.nudge(deck=deck, samples=int(samples))
            except Exception:
                pass
            return True

        if t == "bend":
            deck = str(action.get("deck", "A") or "A").upper()
            speed = float(action.get("speed", 1.0))
            try:
                if self.audio is not None:
                    self.audio.bend_speed(deck=deck, speed=float(speed))
            except Exception:
                pass
            return True

        if t == "queue_clip":
            deck = str(action.get("deck", "A")).upper()
            lane = int(action.get("lane", 0))
            slot = int(action.get("slot", 0))
            self._queue_clip(deck, lane, slot, record=False)
            return True

        if t == "trigger_scene":
            deck = str(action.get("deck", "A")).upper()
            scene = int(action.get("scene", 0))
            self._trigger_scene(deck, scene, record=False)
            return True

        if t == "scene_a":
            scene = int(action.get("scene", 0))
            self.scene_a_callback(None, None, scene)
            return True

        if t == "scene_b":
            scene = int(action.get("scene", 0))
            self.scene_b_callback(None, None, scene)
            return True

        if t == "store_scene_a":
            self.scene_store_a_callback()
            return True

        if t == "store_scene_b":
            self.scene_store_b_callback()
            return True

        if t == "morph":
            v = float(action.get("value", 0.0))
            if dpg.does_item_exist("scene_morph_slider"):
                dpg.set_value("scene_morph_slider", v)
            self.scene_morph_callback("scene_morph_slider", v)
            return True

        if t == "pattern":
            lane = int(action.get("lane", 0))
            pat = str(action.get("value") or "")
            tag = f"pat_{lane}"
            if dpg.does_item_exist(tag):
                dpg.set_value(tag, pat)
            try:
                self.patterns_apply_callback()
            except Exception:
                pass
            return True

        if t == "tab":
            tab = str(action.get("tab") or "")
            if tab.lower().startswith("live"):
                self._select_tab("tab_live_coding")
            else:
                self._select_tab("tab_mixing")
            return True

        return True

    def _tutorial_load_deck(self, deck: str, ref):
        if not isinstance(ref, dict):
            return
        track_id = ref.get("track_id")
        query = ref.get("query")

        info = None
        if track_id:
            try:
                info = self.library._index_by_id.get(str(track_id))
            except Exception:
                info = None
        if info is None and query:
            info = self._tutorial_find_first_by_query(str(query))
        if info is None:
            return

        cache_dir = self.library.cache_dir(info.track_id)
        if deck == "B":
            try:
                self.deck_b.load_track(str(info.path))
            except Exception:
                pass
        else:
            try:
                self.stem_manager.load_track(str(info.path))
            except Exception:
                pass

        try:
            if self.audio is not None:
                self.audio.load_deck(deck, str(info.path), track_id=info.track_id, cache_dir=str(cache_dir), start_separation=True)
                self.audio.seek(deck, 0)
        except Exception:
            pass

    def _tutorial_find_first_by_query(self, query: str):
        q = (query or "").strip().lower()
        if not q:
            return None
        try:
            tracks = list(getattr(self.library, "_tracks", []))
        except Exception:
            tracks = []
        for t in tracks:
            hay = f"{t.name.lower()} {str(t.path).lower()}"
            if q in hay:
                return t
        return None

    def _wire_keybindings(self):
        self.keybindings.on(Actions.PLAY_TOGGLE, self.toggle_play_a)
        try:
            self.keybindings.on(Actions.PLAY_TOGGLE_B, self.toggle_play_b)
        except Exception:
            pass
        self.keybindings.on(Actions.BPM_DOWN, lambda: self._set_bpm_both(self.transport_a.bpm - 1.0))
        self.keybindings.on(Actions.BPM_UP, lambda: self._set_bpm_both(self.transport_a.bpm + 1.0))

        self.keybindings.on(Actions.JUMP_BACK_SMALL, lambda: self.jump_seconds(-1.0))
        self.keybindings.on(Actions.JUMP_BACK_MED, lambda: self.jump_seconds(-4.0))
        self.keybindings.on(Actions.JUMP_BACK_LARGE, lambda: self.jump_seconds(-16.0))

        for i in range(8):
            self.keybindings.on(Actions.mute_lane(i), lambda i=i: self._toggle_lane_mute(i))
            self.keybindings.on(Actions.solo_lane(i), lambda i=i: self._toggle_lane_solo(i))

        self.keybindings.on(Actions.LIBRARY_FOCUS_SEARCH, self.library_focus_search)
        self.keybindings.on(Actions.LIBRARY_NEXT, self.library_select_next)
        self.keybindings.on(Actions.LIBRARY_PREV, self.library_select_prev)
        self.keybindings.on(Actions.LIBRARY_LOAD_SELECTED, self.library_load_selected)
        try:
            self.keybindings.on(Actions.LIBRARY_LOAD_SELECTED_B, self.library_load_selected_to_b)
        except Exception:
            pass

    def jump_seconds(self, seconds: float):
        sr = getattr(self.transport_a, "sample_rate", 44100)
        delta = int(seconds * sr)
        new_pos = int(self.transport_a.play_head_samples) + delta
        self.transport_a.seek(max(0, new_pos))
        try:
            if self.audio is not None:
                self.audio.seek("A", int(self.transport_a.play_head_samples))
        except Exception:
            pass
        self._render_deck_overlay("A")
        try:
            self._tutorial_record_action({"type": "seek", "deck": "A", "samples": int(self.transport_a.play_head_samples)})
        except Exception:
            pass

    def position_slider_callback(self, sender, app_data):
        if self._updating_position_slider:
            return
        if self.stem_manager.full_mix is None:
            return
        total = self.stem_manager.full_mix.shape[0]
        pos = int(float(app_data) * total)
        self.transport_a.seek(max(0, pos))
        try:
            if self.audio is not None:
                self.audio.seek("A", int(self.transport_a.play_head_samples))
        except Exception:
            pass
        self._render_deck_overlay("A")
        try:
            self._tutorial_record_action({"type": "seek", "deck": "A", "samples": int(self.transport_a.play_head_samples)})
        except Exception:
            pass

    def waveform_rebuild(self):
        self.stem_manager.start_waveform_compute()

    def _item_rel_x01(self, item_tag: str) -> float | None:
        try:
            mx, my = dpg.get_mouse_pos(local=False)
            x0, y0 = dpg.get_item_rect_min(item_tag)
            x1, y1 = dpg.get_item_rect_max(item_tag)
        except Exception:
            return None
        w = float(x1 - x0)
        if w <= 1.0:
            return None
        t = (float(mx) - float(x0)) / w
        if t < 0.0:
            t = 0.0
        if t > 1.0:
            t = 1.0
        return t

    def _deck_total_samples(self, deck: str) -> int:
        mgr = self.stem_manager if deck == "A" else self.deck_b
        if mgr.full_mix is None:
            return 0
        return int(mgr.full_mix.shape[0])

    def _deck_center_samples(self, deck: str) -> int:
        if deck == "A":
            return int(self.transport_a.play_head_samples)
        return int(self.transport_b.play_head_samples)

    def deck_a_overview_clicked(self, sender, app_data):
        total = self._deck_total_samples("A")
        if total <= 0:
            return
        t = self._item_rel_x01("deck_a_overview")
        if t is None:
            return
        self.transport_a.seek(max(0, int(t * total)))
        try:
            if self.audio is not None:
                self.audio.seek("A", int(self.transport_a.play_head_samples))
        except Exception:
            pass
        self._render_deck_overlay("A")
        try:
            self._tutorial_record_action({"type": "seek", "deck": "A", "samples": int(self.transport_a.play_head_samples)})
        except Exception:
            pass

    def deck_a_zoom_clicked(self, sender, app_data):
        total = self._deck_total_samples("A")
        if total <= 0:
            return
        rel = self._item_rel_x01("deck_a_zoom")
        if rel is None:
            return
        sr = getattr(self.transport_a, "sample_rate", 44100)
        center = self._deck_center_samples("A")
        half = int((self._zoom_window_sec * sr) / 2)
        start = max(0, center - half)
        end = min(total, center + half)
        if end <= start:
            return
        self.transport_a.seek(max(0, int(start + rel * (end - start))))
        try:
            if self.audio is not None:
                self.audio.seek("A", int(self.transport_a.play_head_samples))
        except Exception:
            pass
        self._render_deck_overlay("A")
        try:
            self._tutorial_record_action({"type": "seek", "deck": "A", "samples": int(self.transport_a.play_head_samples)})
        except Exception:
            pass

    def deck_b_overview_clicked(self, sender, app_data):
        total = self._deck_total_samples("B")
        if total <= 0:
            return
        t = self._item_rel_x01("deck_b_overview")
        if t is None:
            return
        self._deck_b_cue_samples = max(0, int(t * total))
        self.transport_b.seek(int(self._deck_b_cue_samples))
        try:
            if self.audio is not None:
                self.audio.seek("B", int(self.transport_b.play_head_samples))
        except Exception:
            pass
        self._render_deck_overlay("B")
        try:
            self._tutorial_record_action({"type": "seek", "deck": "B", "samples": int(self.transport_b.play_head_samples)})
        except Exception:
            pass

    def deck_b_zoom_clicked(self, sender, app_data):
        total = self._deck_total_samples("B")
        if total <= 0:
            return
        rel = self._item_rel_x01("deck_b_zoom")
        if rel is None:
            return
        sr = getattr(self.transport_b, "sample_rate", 44100)
        center = self._deck_center_samples("B")
        half = int((self._zoom_window_sec * sr) / 2)
        start = max(0, center - half)
        end = min(total, center + half)
        if end <= start:
            return
        self._deck_b_cue_samples = max(0, int(start + rel * (end - start)))
        self.transport_b.seek(int(self._deck_b_cue_samples))
        try:
            if self.audio is not None:
                self.audio.seek("B", int(self.transport_b.play_head_samples))
        except Exception:
            pass
        self._render_deck_overlay("B")
        try:
            self._tutorial_record_action({"type": "seek", "deck": "B", "samples": int(self.transport_b.play_head_samples)})
        except Exception:
            pass

    def _render_deck_overview(self, deck: str) -> bool:
        try:
            mgr = self.stem_manager if deck == "A" else self.deck_b
            if not getattr(mgr, "waveform_ready", False):
                return False
            xs = getattr(mgr, "waveform_x", None)
            yl = getattr(mgr, "waveform_y_low", None)
            ym = getattr(mgr, "waveform_y_mid", None)
            yh = getattr(mgr, "waveform_y_high", None)
            if xs is None or yl is None or ym is None or yh is None:
                return False
            if not xs:
                return False

            tag = "deck_a_overview" if deck == "A" else "deck_b_overview"

            try:
                w, h = dpg.get_item_rect_size(tag)
            except Exception:
                w, h = (0, 0)
            if (w <= 0 or h <= 0) and dpg.does_item_exist(tag):
                try:
                    cfg = dpg.get_item_configuration(tag)
                    w = int(cfg.get("width", 0))
                    h = int(cfg.get("height", 0))
                except Exception:
                    pass
            w = int(w)
            h = int(h)
            if w <= 4 or h <= 4:
                return False

            try:
                cache_key = (w, h, id(xs), id(yl), id(ym), id(yh), len(xs))
            except Exception:
                cache_key = None
            if deck == "A":
                if cache_key is not None and cache_key == self._overview_cache_key_a:
                    return False
                self._overview_cache_key_a = cache_key
            else:
                if cache_key is not None and cache_key == self._overview_cache_key_b:
                    return False
                self._overview_cache_key_b = cache_key

            try:
                dpg.delete_item(tag, children_only=True)
            except Exception:
                pass

            mid_y = h * 0.5
            n = min(len(xs), len(yl), len(ym), len(yh))
            if n <= 0:
                return False

            def _finite(v: float) -> bool:
                return v == v and v != float("inf") and v != float("-inf")

            max_peak = 0.0
            for arr in (yl, ym, yh):
                for v in arr:
                    try:
                        fv = float(v)
                    except Exception:
                        continue
                    if not _finite(fv):
                        continue
                    if fv > max_peak:
                        max_peak = fv
            if max_peak <= 1e-9:
                max_peak = 1.0

            blue = (60, 140, 255, 220)
            orange = (255, 140, 40, 220)
            white = (245, 245, 245, 240)

            # Draw vertical lines per bin.
            step = max(1, int(n // max(1, w)))
            for i in range(0, n, step):
                x = int((i * (w - 1)) / max(1, n - 1))
                try:
                    a_l = float(yl[i]) / max_peak
                    a_m = float(ym[i]) / max_peak
                    a_h = float(yh[i]) / max_peak
                except Exception:
                    continue

                if not _finite(a_l):
                    a_l = 0.0
                if not _finite(a_m):
                    a_m = 0.0
                if not _finite(a_h):
                    a_h = 0.0

                if a_l < 0.0:
                    a_l = 0.0
                if a_m < 0.0:
                    a_m = 0.0
                if a_h < 0.0:
                    a_h = 0.0
                if a_l > 1.0:
                    a_l = 1.0
                if a_m > 1.0:
                    a_m = 1.0
                if a_h > 1.0:
                    a_h = 1.0

                # Non-additive overlay: each band drawn independently.
                r_l = a_l * (h * 0.48)
                r_m = a_m * (h * 0.48)
                r_h = a_h * (h * 0.48)

                # Draw order: blue (back), orange (middle), white (top).
                if r_l > 0.05:
                    dpg.draw_line((x, mid_y - r_l), (x, mid_y + r_l), color=blue, thickness=2.0, parent=tag)
                if r_m > 0.05:
                    dpg.draw_line((x, mid_y - r_m), (x, mid_y + r_m), color=orange, thickness=1.5, parent=tag)
                if r_h > 0.05:
                    dpg.draw_line((x, mid_y - r_h), (x, mid_y + r_h), color=white, thickness=2.0, parent=tag)
            self._draw_clip_overlays(deck, tag, w, h)

            self._render_deck_overlay(deck)
            return True
        except Exception as e:
            if dpg.does_item_exist("status_text"):
                dpg.set_value("status_text", f"Status: Deck {deck} render error: {e}")
            return False

    def _draw_clip_overlays(self, deck: str, parent_tag: str, w: int, h: int):
        cm = self._get_clip_manager_for_deck(deck)
        if cm is None:
            return
        mgr = self.stem_manager if deck == "A" else self.deck_b
        if mgr.full_mix is None:
            return

        try:
            sr = getattr(self.transport_a if deck == "A" else self.transport_b, "sample_rate", 44100)
            total_samples = int(mgr.full_mix.shape[0])
        except Exception:
            return
        if total_samples <= 0:
            return

        lane_h = max(1, int(h / 8))

        def _lane_color(lane: int, alpha: int):
            base = [
                (255, 120, 0),
                (255, 60, 60),
                (255, 200, 0),
                (120, 220, 60),
                (0, 190, 120),
                (0, 160, 255),
                (120, 120, 255),
                (200, 100, 255),
            ]
            r, g, b = base[int(lane) % len(base)]
            return (int(r), int(g), int(b), int(alpha))

        try:
            pending = list(getattr(cm, "pending_clip_indices", [-2] * 8))
            active = list(getattr(cm, "active_clip_indices", [-1] * 8))
        except Exception:
            return

        self._draw_clip_overlays_window(deck, parent_tag, w, h, 0, total_samples)

    def _draw_clip_overlays_window(self, deck: str, parent_tag: str, w: int, h: int, win_start: int, win_end: int):
        cm = self._get_clip_manager_for_deck(deck)
        if cm is None:
            return
        mgr = self.stem_manager if deck == "A" else self.deck_b
        if mgr.full_mix is None:
            return

        try:
            total_samples = int(mgr.full_mix.shape[0])
        except Exception:
            return
        if total_samples <= 0:
            return

        try:
            pending = list(getattr(cm, "pending_clip_indices", [-2] * 8))
            active = list(getattr(cm, "active_clip_indices", [-1] * 8))
        except Exception:
            return

        try:
            start = int(win_start)
            end = int(win_end)
        except Exception:
            start = 0
            end = total_samples
        start = max(0, min(total_samples, start))
        end = max(0, min(total_samples, end))
        if end <= start:
            return

        lane_h = max(1, int(h / 8))

        def _lane_color(lane: int, alpha: int):
            base = [
                (255, 120, 0),
                (255, 60, 60),
                (255, 200, 0),
                (120, 220, 60),
                (0, 190, 120),
                (0, 160, 255),
                (120, 120, 255),
                (200, 100, 255),
            ]
            r, g, b = base[int(lane) % len(base)]
            return (int(r), int(g), int(b), int(alpha))

        def _x_for_sample(smp: int) -> int:
            # Map absolute sample to window-relative x.
            p = max(start, min(end, int(smp)))
            return int((float(p - start) / float(max(1, end - start))) * float(w - 1))

        for lane in range(8):
            try:
                p = int(pending[lane])
            except Exception:
                p = -2
            try:
                a = int(active[lane])
            except Exception:
                a = -1

            y0 = lane * lane_h
            y1 = min(h, y0 + lane_h)
            if y1 <= y0:
                continue

            # Always show clip slot boxes (faint), so users can see the grid regions.
            for slot in range(8):
                try:
                    clip0 = cm.grid[lane][slot]
                except Exception:
                    clip0 = None
                if clip0 is None:
                    continue
                if int(getattr(clip0, "end_sample", 0)) < start or int(getattr(clip0, "start_sample", 0)) > end:
                    continue
                x0b = _x_for_sample(int(clip0.start_sample))
                x1b = _x_for_sample(int(clip0.end_sample))
                x0b = max(0, min(w - 1, x0b))
                x1b = max(0, min(w - 1, x1b))
                if x1b > x0b:
                    dpg.draw_rectangle((x0b, y0), (x1b, y1), color=(120, 120, 120, 55), fill=(0, 0, 0, 0), parent=parent_tag)

            # Active clip region
            if a >= 0:
                try:
                    clip = cm.grid[lane][a]
                except Exception:
                    clip = None
                if clip is not None:
                    if int(getattr(clip, "end_sample", 0)) < start or int(getattr(clip, "start_sample", 0)) > end:
                        clip = None
                if clip is not None:
                    x0 = _x_for_sample(int(clip.start_sample))
                    x1 = _x_for_sample(int(clip.end_sample))
                    x0 = max(0, min(w - 1, x0))
                    x1 = max(0, min(w - 1, x1))
                    if x1 > x0:
                        dpg.draw_rectangle((x0, y0), (x1, y1), color=_lane_color(lane, 200), fill=_lane_color(lane, 50), parent=parent_tag)

                        # Clip playhead marker (shows looping position inside the active clip).
                        try:
                            clip_len = int(clip.end_sample - clip.start_sample)
                        except Exception:
                            clip_len = 0
                        if clip_len > 0:
                            try:
                                off = float(cm.clip_playheads[lane])
                            except Exception:
                                off = 0.0
                            t = 0.0
                            try:
                                t = max(0.0, min(1.0, float(off) / float(clip_len)))
                            except Exception:
                                t = 0.0
                            xp = int(float(x0) + t * float(max(1, x1 - x0)))
                            xp = max(x0, min(x1, xp))
                            dpg.draw_line((xp, y0), (xp, y1), color=(245, 245, 245, 220), thickness=2.0, parent=parent_tag)

            # Pending clip region (queued)
            if p == -1:
                # stop queued for lane: show small red marker at the far right of lane band
                dpg.draw_rectangle((w - 6, y0), (w - 1, y1), color=(200, 40, 40, 220), fill=(200, 40, 40, 90), parent=parent_tag)
            elif p >= 0:
                try:
                    clip = cm.grid[lane][p]
                except Exception:
                    clip = None
                if clip is not None:
                    if int(getattr(clip, "end_sample", 0)) < start or int(getattr(clip, "start_sample", 0)) > end:
                        clip = None
                if clip is not None:
                    x0 = _x_for_sample(int(clip.start_sample))
                    x1 = _x_for_sample(int(clip.end_sample))
                    x0 = max(0, min(w - 1, x0))
                    x1 = max(0, min(w - 1, x1))
                    if x1 > x0:
                        dpg.draw_rectangle((x0, y0), (x1, y1), color=(230, 165, 0, 220), fill=(230, 165, 0, 55), parent=parent_tag)

    def _render_deck_zoom(self, deck: str) -> bool:
        try:
            mgr = self.stem_manager if deck == "A" else self.deck_b
            if not getattr(mgr, "waveform_ready", False):
                return False
            xs = getattr(mgr, "waveform_x", None)
            yl = getattr(mgr, "waveform_y_low", None)
            ym = getattr(mgr, "waveform_y_mid", None)
            yh = getattr(mgr, "waveform_y_high", None)
            if xs is None or yl is None or ym is None or yh is None:
                return False
            if not xs:
                return False

            try:
                xs0 = float(xs[0])
                xs1 = float(xs[-1])
            except Exception:
                return False

            tag = "deck_a_zoom" if deck == "A" else "deck_b_zoom"

            try:
                w, h = dpg.get_item_rect_size(tag)
            except Exception:
                w, h = (0, 0)
            if (w <= 0 or h <= 0) and dpg.does_item_exist(tag):
                try:
                    cfg = dpg.get_item_configuration(tag)
                    w = int(cfg.get("width", 0))
                    h = int(cfg.get("height", 0))
                except Exception:
                    pass
            w = int(w)
            h = int(h)
            if w <= 4 or h <= 4:
                return False

            try:
                cache_key = (w, h, id(xs), id(yl), id(ym), id(yh), len(xs))
            except Exception:
                cache_key = None
            if deck == "A":
                last = self._zoom_cache_key_a
            else:
                last = self._zoom_cache_key_b

            tr = self.transport_a if deck == "A" else self.transport_b
            sr = getattr(tr, "sample_rate", 44100)
            center_s = float(self._deck_center_samples(deck)) / float(sr)
            start_s = center_s - (self._zoom_window_sec / 2.0)
            end_s = center_s + (self._zoom_window_sec / 2.0)

            # Clamp window to waveform range so zoom still draws near edges.
            if end_s <= xs0:
                start_s = xs0
                end_s = min(xs1, xs0 + self._zoom_window_sec)
            elif start_s >= xs1:
                end_s = xs1
                start_s = max(xs0, xs1 - self._zoom_window_sec)
            else:
                start_s = max(xs0, start_s)
                end_s = min(xs1, end_s)

            try:
                pix_s = float(self._zoom_window_sec) / float(max(1, w))
            except Exception:
                pix_s = 0.0
            if last is not None and cache_key is not None:
                try:
                    last_w, last_h, last_xs_id, last_yl_id, last_ym_id, last_yh_id, last_len, last_start_s = last
                    if (
                        last_w == w
                        and last_h == h
                        and last_xs_id == id(xs)
                        and last_yl_id == id(yl)
                        and last_ym_id == id(ym)
                        and last_yh_id == id(yh)
                        and last_len == len(xs)
                        and pix_s > 0.0
                        and abs(float(start_s) - float(last_start_s)) < (pix_s * 0.9)
                    ):
                        return False
                except Exception:
                    pass

            if cache_key is not None:
                new_key = (w, h, id(xs), id(yl), id(ym), id(yh), len(xs), float(start_s))
                if deck == "A":
                    self._zoom_cache_key_a = new_key
                else:
                    self._zoom_cache_key_b = new_key

            dpg.delete_item(tag, children_only=True)

            # Match older implementation: scan indices in the cached envelope.
            idxs = []
            for i, t in enumerate(xs):
                try:
                    ft = float(t)
                except Exception:
                    continue
                if ft < start_s:
                    continue
                if ft > end_s:
                    break
                idxs.append(i)
            if len(idxs) < 2:
                return False

            mid_y = h * 0.5

            def _finite(v: float) -> bool:
                return v == v and v != float("inf") and v != float("-inf")

            max_peak = 0.0
            for i in idxs:
                for arr in (yl, ym, yh):
                    try:
                        fv = float(arr[i])
                    except Exception:
                        continue
                    if not _finite(fv):
                        continue
                    if fv > max_peak:
                        max_peak = fv
            if max_peak <= 1e-9:
                max_peak = 1.0

            blue = (60, 140, 255, 220)
            orange = (255, 140, 40, 220)
            white = (245, 245, 245, 240)

            m = len(idxs)
            step = max(1, int(m // max(1, w)))
            j = 0
            for k in range(0, m, step):
                i = idxs[k]
                x = int((j * (w - 1)) / max(1, int((m + step - 1) // step) - 1))
                try:
                    a_l = float(yl[i]) / max_peak
                    a_m = float(ym[i]) / max_peak
                    a_h = float(yh[i]) / max_peak
                except Exception:
                    continue
                if not _finite(a_l):
                    a_l = 0.0
                if not _finite(a_m):
                    a_m = 0.0
                if not _finite(a_h):
                    a_h = 0.0
                if a_l < 0.0:
                    a_l = 0.0
                if a_m < 0.0:
                    a_m = 0.0
                if a_h < 0.0:
                    a_h = 0.0
                if a_l > 1.0:
                    a_l = 1.0
                if a_m > 1.0:
                    a_m = 1.0
                if a_h > 1.0:
                    a_h = 1.0

                # Non-additive overlay: each band drawn independently.
                r_l = a_l * (h * 0.48)
                r_m = a_m * (h * 0.48)
                r_h = a_h * (h * 0.48)

                # Draw order: blue (back), orange (middle), white (top).
                if r_l > 0.05:
                    dpg.draw_line((x, mid_y - r_l), (x, mid_y + r_l), color=blue, thickness=2.0, parent=tag)
                if r_m > 0.05:
                    dpg.draw_line((x, mid_y - r_m), (x, mid_y + r_m), color=orange, thickness=1.5, parent=tag)
                if r_h > 0.05:
                    dpg.draw_line((x, mid_y - r_h), (x, mid_y + r_h), color=white, thickness=2.0, parent=tag)

                j += 1

            self._render_deck_overlay(deck)
            return True
        except Exception as e:
            if dpg.does_item_exist("status_text"):
                dpg.set_value("status_text", f"Status: Deck {deck} zoom render error: {e}")
            return False

    def _render_waveform_debug(self):
        try:
            if not self._debug_mode:
                return
            now = time.time()
            if now - self._last_waveform_debug_draw < 0.20:
                return
            self._last_waveform_debug_draw = now

            self._render_deck_debug("A")
            self._render_deck_debug("B")
        except Exception as e:
            if dpg.does_item_exist("status_text"):
                dpg.set_value("status_text", f"Status: Waveform debug error: {e}")

    def _render_deck_debug(self, deck: str):
        try:
            if not self._debug_mode:
                return
            mgr = self.stem_manager if deck == "A" else self.deck_b
            parent = "deck_a_zoom" if deck == "A" else "deck_b_zoom"
            txt_tag = f"dbg_text_{deck}"
            border_tag = f"dbg_border_{deck}"

            try:
                w, h = dpg.get_item_rect_size(parent)
            except Exception:
                w, h = (0, 0)
            if (w <= 0 or h <= 0) and dpg.does_item_exist(parent):
                try:
                    cfg = dpg.get_item_configuration(parent)
                    w = int(cfg.get("width", 0))
                    h = int(cfg.get("height", 0))
                except Exception:
                    pass
            w = int(w)
            h = int(h)
            if w <= 0 or h <= 0:
                return

            # Replace debug text/border each time.
            if dpg.does_item_exist(txt_tag):
                try:
                    dpg.delete_item(txt_tag)
                except Exception:
                    pass
            if dpg.does_item_exist(border_tag):
                try:
                    dpg.delete_item(border_tag)
                except Exception:
                    pass

            ready = bool(getattr(mgr, "waveform_ready", False))
            xs = getattr(mgr, "waveform_x", None)
            yl = getattr(mgr, "waveform_y_low", None)
            ym = getattr(mgr, "waveform_y_mid", None)
            yh = getattr(mgr, "waveform_y_high", None)
            full = getattr(mgr, "full_mix", None)
            full_n = int(full.shape[0]) if full is not None else 0

            nx = len(xs) if isinstance(xs, list) else (-1 if xs is None else 0)
            nl = len(yl) if isinstance(yl, list) else (-1 if yl is None else 0)
            nm = len(ym) if isinstance(ym, list) else (-1 if ym is None else 0)
            nh = len(yh) if isinstance(yh, list) else (-1 if yh is None else 0)

            dpg.draw_rectangle((1, 1), (w - 2, h - 2), color=(0, 255, 255, 255), thickness=1.0, parent=parent, tag=border_tag)
            msg = f"Deck {deck}  size={w}x{h}  ready={ready}  full={full_n}  x={nx}  L={nl}  M={nm}  H={nh}"
            dpg.draw_text((6, 6), msg, color=(255, 255, 0, 255), size=14, parent=parent, tag=txt_tag)
        except Exception as e:
            if dpg.does_item_exist("status_text"):
                dpg.set_value("status_text", f"Status: Deck {deck} debug error: {e}")

    def _update_waveform_debug_text(self):
        return

    def debug_mode_callback(self, sender, app_data):
        self._debug_mode = bool(app_data)

    def _position_debug_window(self):
        if not dpg.does_item_exist("debug_window"):
            return
        try:
            vw, vh = dpg.get_viewport_client_width(), dpg.get_viewport_client_height()
        except Exception:
            return
        x = max(0, int(vw - 230))
        y = max(0, int(vh - 70))
        try:
            dpg.set_item_pos("debug_window", (x, y))
        except Exception:
            pass

    def crossfade_callback(self, sender, app_data):
        try:
            with self.mixer_state.lock:
                v = float(app_data)
                if v < 0.0:
                    v = 0.0
                if v > 1.0:
                    v = 1.0
                self.mixer_state.deck_crossfade = v
        except Exception:
            pass
        try:
            if self.audio is not None:
                self.audio.set_mixer_values(deck_crossfade=v)
        except Exception:
            pass
        try:
            self._tutorial_record_action({"type": "set", "tag": "crossfade_slider", "value": float(v)})
        except Exception:
            pass

    def master_gain_callback(self, sender, app_data):
        try:
            with self.mixer_state.lock:
                self.mixer_state.master_gain = float(app_data)
        except Exception:
            pass
        try:
            if self.audio is not None:
                self.audio.set_mixer_values(master_gain=float(app_data))
        except Exception:
            pass
        try:
            self._tutorial_record_action({"type": "set", "tag": "master_gain_slider", "value": float(app_data)})
        except Exception:
            pass

    def _render_deck_overlay(self, deck: str):
        now = time.time()
        if deck == "A":
            if now - self._last_deck_a_playhead_draw < 0.03:
                return
            self._last_deck_a_playhead_draw = now
        else:
            if now - self._last_deck_b_playhead_draw < 0.03:
                return
            self._last_deck_b_playhead_draw = now

        mgr = self.stem_manager if deck == "A" else self.deck_b
        if mgr.full_mix is None:
            return
        total = int(mgr.full_mix.shape[0])
        if total <= 0:
            return

        parent_over = "deck_a_overview" if deck == "A" else "deck_b_overview"
        parent_zoom = "deck_a_zoom" if deck == "A" else "deck_b_zoom"

        tag_over = "deck_a_playhead_over" if deck == "A" else "deck_b_cue_over"
        tag_zoom = "deck_a_playhead_zoom" if deck == "A" else "deck_b_cue_zoom"

        for parent, tag in ((parent_over, tag_over), (parent_zoom, tag_zoom)):
            if dpg.does_item_exist(tag):
                try:
                    dpg.delete_item(tag)
                except Exception:
                    pass

            try:
                w, h = dpg.get_item_rect_size(parent)
            except Exception:
                w, h = (0, 0)
            if (w <= 0 or h <= 0) and dpg.does_item_exist(parent):
                try:
                    cfg = dpg.get_item_configuration(parent)
                    w = int(cfg.get("width", 0))
                    h = int(cfg.get("height", 0))
                except Exception:
                    pass
            w = int(w)
            h = int(h)
            if w <= 4 or h <= 4:
                continue

            if deck == "A":
                pos = int(self.transport_a.play_head_samples)
                color = (0, 255, 120, 255)
            else:
                pos = int(self.transport_b.play_head_samples)
                color = (255, 220, 0, 255)

            if parent == parent_over:
                x = int((float(pos) / float(total)) * float(w - 1))
            else:
                tr = self.transport_a if deck == "A" else self.transport_b
                sr = getattr(tr, "sample_rate", 44100)
                center = self._deck_center_samples(deck)
                half = int((self._zoom_window_sec * sr) / 2)
                start = max(0, center - half)
                end = min(total, center + half)
                if end <= start:
                    continue
                p = max(start, min(end, pos))
                x = int((float(p - start) / float(end - start)) * float(w - 1))

            dpg.draw_line((x, 0), (x, h), color=color, thickness=2.0, parent=parent, tag=tag)

            # Clip boxes + per-lane clip playheads should update continuously (overlay layer).
            overlay_tag = f"deck_{str(deck).lower()}_clip_overlay_{'over' if parent == parent_over else 'zoom'}"
            if not dpg.does_item_exist(overlay_tag):
                try:
                    with dpg.draw_layer(tag=overlay_tag, parent=parent):
                        pass
                except Exception:
                    overlay_tag = None

            if overlay_tag is not None and dpg.does_item_exist(overlay_tag):
                try:
                    dpg.delete_item(overlay_tag, children_only=True)
                except Exception:
                    pass

            if overlay_tag is not None and dpg.does_item_exist(overlay_tag):
                if parent == parent_over:
                    self._draw_beat_ticks_window(deck, overlay_tag, w, h, 0, total)
                    self._draw_clip_overlays_window(deck, overlay_tag, w, h, 0, total)
                else:
                    self._draw_beat_ticks_window(deck, overlay_tag, w, h, start, end)
                    self._draw_clip_overlays_window(deck, overlay_tag, w, h, start, end)

        # Update slider to reflect Deck A position
        if deck == "A" and dpg.does_item_exist("position_slider"):
            self._updating_position_slider = True
            try:
                dpg.set_value("position_slider", float(pos) / float(total))
            finally:
                self._updating_position_slider = False

    def _draw_beat_ticks_window(self, deck: str, parent: str, w: int, h: int, start: int, end: int):
        try:
            if end <= start:
                return
            tr = self.transport_a if deck == "A" else self.transport_b
            spb = float(getattr(tr, "samples_per_beat", 0.0) or 0.0)
            if spb <= 1e-6:
                return
            bpb = int(getattr(tr, "beats_per_bar", 4) or 4)
            if bpb <= 0:
                bpb = 4

            start_beat = float(start) / spb
            end_beat = float(end) / spb
            if end_beat <= start_beat:
                return

            # Keep drawing bounded for very long windows.
            beat_span = end_beat - start_beat
            max_ticks = max(8, int(w // 4))
            step = 1
            if beat_span > float(max_ticks):
                step = int(math.ceil(beat_span / float(max_ticks)))
            if step <= 0:
                step = 1

            first = int(math.floor(start_beat))
            last = int(math.ceil(end_beat))
            white = (245, 245, 245, 120)
            red = (255, 80, 80, 160)

            # Visual style: short ticks for beats, taller ticks for bars.
            beat_y0 = int(h * 0.78)
            beat_y1 = int(h * 1.00)
            bar_y0 = int(h * 0.45)
            bar_y1 = int(h * 1.00)

            for b in range(first, last + 1, step):
                bs = float(b) * spb
                if bs < float(start) - 1.0:
                    continue
                if bs > float(end) + 1.0:
                    break
                x = int(((bs - float(start)) / float(end - start)) * float(w - 1))
                is_bar = (bpb > 0) and (b % bpb == 0)
                color = red if is_bar else white
                thickness = 2.0 if is_bar else 1.0
                if is_bar:
                    dpg.draw_line((x, bar_y0), (x, bar_y1), color=color, thickness=thickness, parent=parent)
                else:
                    dpg.draw_line((x, beat_y0), (x, beat_y1), color=color, thickness=thickness, parent=parent)
        except Exception:
            return

    def _dj_beatmatch_a_to_b(self):
        try:
            if self.audio is not None:
                self.audio.beatmatch(src="A", dst="B")
        except Exception:
            pass
        try:
            self._tutorial_record_action({"type": "beatmatch", "src": "A", "dst": "B"})
        except Exception:
            pass

    def _dj_beatmatch_b_to_a(self):
        try:
            if self.audio is not None:
                self.audio.beatmatch(src="B", dst="A")
        except Exception:
            pass
        try:
            self._tutorial_record_action({"type": "beatmatch", "src": "B", "dst": "A"})
        except Exception:
            pass

    def _dj_nudge_ms(self, deck: str, ms: float):
        try:
            sr = int(getattr(self.transport_a if str(deck).upper() == "A" else self.transport_b, "sample_rate", 44100))
        except Exception:
            sr = 44100
        try:
            samples = int((float(ms) / 1000.0) * float(sr))
        except Exception:
            samples = 0
        try:
            if self.audio is not None:
                self.audio.nudge(deck=str(deck).upper(), samples=int(samples))
        except Exception:
            pass
        try:
            self._tutorial_record_action({"type": "nudge", "deck": str(deck).upper(), "samples": int(samples)})
        except Exception:
            pass

    def _dj_bend(self, deck: str, speed: float):
        try:
            if self.audio is not None:
                self.audio.bend_speed(deck=str(deck).upper(), speed=float(speed))
        except Exception:
            pass
        try:
            self._tutorial_record_action({"type": "bend", "deck": str(deck).upper(), "speed": float(speed)})
        except Exception:
            pass

    def _toggle_lane_mute(self, idx: int):
        new_mute = not self.mixer_state.lanes[idx].mute
        self.mixer_state.set_lane_mute(idx, new_mute)
        if dpg.does_item_exist(f"mute_{idx}"):
            dpg.set_value(f"mute_{idx}", new_mute)

    def _toggle_lane_solo(self, idx: int):
        new_solo = not self.mixer_state.lanes[idx].solo
        self.mixer_state.set_lane_solo(idx, new_solo)
        if dpg.does_item_exist(f"solo_{idx}"):
            dpg.set_value(f"solo_{idx}", new_solo)

    def library_add_folder_callback(self):
        p = Path(dpg.get_value("library_folder")).expanduser()
        if p.exists() and p.is_dir():
            self.library.add_folder(p)
            self.library.scan()
            self.library_refresh_listbox()

    def library_scan_callback(self):
        self.library.scan()
        self.library_refresh_listbox()

    def library_search_callback(self, sender, app_data):
        self.library.filter_text = app_data
        self.library.selected_index = 0
        self.library_refresh_listbox()

    def library_select_callback(self, sender, app_data):
        # app_data is the selected string
        items = self.library.filtered_tracks()
        if not items:
            return
        try:
            idx = dpg.get_value("library_list")
        except Exception:
            idx = None

        # DearPyGui listbox value is item string; map back by index
        labels = self._library_labels(items)
        if app_data in labels:
            self.library.selected_index = labels.index(app_data)
            self._update_library_key_display()

    def library_focus_search(self):
        if dpg.does_item_exist("library_search"):
            dpg.focus_item("library_search")

    def library_select_next(self):
        self.library.select_next()
        self.library_refresh_listbox(set_focus=True)
        self._update_library_key_display()

    def library_select_prev(self):
        self.library.select_prev()
        self.library_refresh_listbox(set_focus=True)
        self._update_library_key_display()

    def library_load_selected(self):
        sel = self.library.get_selected()
        if not sel:
            return
        cache_dir = self.library.stems_dir(sel.track_id)
        self._waveform_plotted = False
        self._deck_b_waveform_plotted = False
        self._last_zoom_update = 0.0
        self.stem_manager.load_track(str(sel.path), track_id=sel.track_id, cache_dir=cache_dir)
        try:
            self.transport_a.seek(0)
        except Exception:
            pass
        try:
            if self.audio is not None:
                self.audio.load_deck("A", str(sel.path), track_id=sel.track_id, cache_dir=str(cache_dir), start_separation=True)
                self.audio.seek("A", 0)
        except Exception:
            pass

    def library_load_selected_to_b(self):
        sel = self.library.get_selected()
        if not sel:
            return
        self._deck_b_waveform_plotted = False
        self._deck_b_cue_samples = 0
        # Deck B is waveform-only for now.
        self.deck_b.load_track(
            str(sel.path),
            track_id=sel.track_id,
            cache_dir=self.library.stems_dir(sel.track_id),
            start_separation=False,
        )
        try:
            self.transport_b.seek(0)
        except Exception:
            pass
        try:
            if self.audio is not None:
                self.audio.load_deck(
                    "B",
                    str(sel.path),
                    track_id=sel.track_id,
                    cache_dir=str(self.library.stems_dir(sel.track_id)),
                    start_separation=True,
                )
                self.audio.seek("B", 0)
        except Exception:
            pass

    def _library_labels(self, items):
        labels = []
        for t in items:
            meta = self.library.get_meta(t.track_id)
            status = "READY" if t.stems_ready else "RAW"
            bpm_val = meta.get("bpm", t.bpm)
            camelot = meta.get("camelot", None)
            bpm = f"{float(bpm_val):.1f}" if bpm_val is not None else "?"
            ck = camelot if camelot else "--"
            labels.append(f"[{status}] bpm:{bpm}  {ck}  {t.name}")
        return labels

    def _camelot_color_rgba(self, camelot: str):
        # Fixed 12-color wheel palette (stable). A/B uses brightness.
        try:
            c = camelot.strip().upper()
            num = int(c[:-1])
            ab = c[-1]
        except Exception:
            return (0, 0, 0, 255)

        num = max(1, min(12, num))

        # Standard wheel-like palette (12 evenly-spaced hues).
        base = {
            1: (255, 0, 102),
            2: (255, 0, 0),
            3: (255, 102, 0),
            4: (255, 204, 0),
            5: (204, 255, 0),
            6: (0, 204, 0),
            7: (0, 204, 153),
            8: (0, 153, 255),
            9: (0, 0, 255),
            10: (102, 0, 255),
            11: (204, 0, 255),
            12: (255, 0, 204),
        }

        r, g, b = base.get(num, (0, 0, 0))
        # A = darker, B = brighter
        scale = 1.0 if ab == "B" else 0.72
        return (int(r * scale), int(g * scale), int(b * scale), 255)

    def _update_library_key_display(self):
        sel = self.library.get_selected()
        if not sel:
            return
        meta = self.library.get_meta(sel.track_id)
        camelot = meta.get("camelot")
        key = meta.get("key")
        txt = "--"
        if camelot and key:
            txt = f"{camelot} ({key})"
        elif camelot:
            txt = f"{camelot}"
        elif key:
            txt = f"{key}"

        if dpg.does_item_exist("library_key_text"):
            dpg.set_value("library_key_text", txt)
        if dpg.does_item_exist("library_key_color"):
            rgba = self._camelot_color_rgba(camelot) if camelot else (0, 0, 0, 255)
            dpg.set_value("library_key_color", rgba)

    def library_refresh_listbox(self, set_focus: bool = False):
        items = self.library.filtered_tracks()
        labels = self._library_labels(items)

        if dpg.does_item_exist("library_list"):
            dpg.configure_item("library_list", items=labels)

        if labels:
            idx = max(0, min(self.library.selected_index, len(labels) - 1))
            self.library.selected_index = idx
            dpg.set_value("library_list", labels[idx])
            if set_focus:
                dpg.focus_item("library_list")
            self._update_library_key_display()

    def eval_callback(self):
        code = dpg.get_value("live_code_input")
        if not code.strip():
            return

        synth = SynthProxy(self.audio)
        dj = DJProxy(self.audio)
        context = {
            "mixer": self.mixer_state,
            "transport_a": self.transport_a,
            "transport_b": self.transport_b,
            "stems_a": self.stem_manager,
            "stems_b": self.deck_b,
            "synth": synth,
            "dj": dj,
            "print": print,
        }

        try:
            exec(code, {}, context)
            dpg.set_value("eval_status", "Executed successfully.")
            dpg.configure_item("eval_status", color=(100, 255, 100))
        except Exception as e:
            dpg.set_value("eval_status", f"Error: {e}")
            dpg.configure_item("eval_status", color=(255, 100, 100))

    def load_track_callback(self):
        if dpg.does_item_exist("audio_file_dialog"):
            dpg.configure_item("audio_file_dialog", show=True)

    def _audio_file_selected(self, sender, app_data):
        try:
            file_path = str(app_data.get("file_path_name") or "")
        except Exception:
            file_path = ""
        if not file_path:
            return
        try:
            self.stem_manager.load_track(file_path)
        except Exception:
            pass
        try:
            if self.audio is not None:
                self.audio.load_deck("A", str(file_path), track_id=None, cache_dir=None, start_separation=True)
                self.audio.seek("A", 0)
        except Exception:
            pass

    def separate_callback(self):
        pass

    def toggle_play_a(self):
        new_state = not bool(self.transport_a.playing)
        self.transport_a.playing = new_state
        try:
            if self.audio is not None:
                self.audio.play("A", new_state)
        except Exception:
            pass
        try:
            self._tutorial_record_action({"type": "play", "deck": "A", "on": bool(new_state)})
        except Exception:
            pass

    def toggle_play_b(self):
        new_state = not bool(self.transport_b.playing)
        self.transport_b.playing = new_state
        try:
            if self.audio is not None:
                self.audio.play("B", new_state)
        except Exception:
            pass
        try:
            self._tutorial_record_action({"type": "play", "deck": "B", "on": bool(new_state)})
        except Exception:
            pass

    def _set_bpm_both(self, bpm: float):
        try:
            bpm_f = float(bpm)
        except Exception:
            return
        self.transport_a.set_bpm(bpm_f)
        self.transport_b.set_bpm(bpm_f)
        try:
            if self.audio is not None:
                self.audio.set_bpm(bpm_f)
        except Exception:
            pass

    def bpm_callback(self, sender, app_data):
        try:
            bpm = float(app_data)
        except Exception:
            return
        self._set_bpm_both(bpm)
        try:
            self._tutorial_record_action({"type": "set", "tag": "bpm_slider", "value": float(bpm)})
        except Exception:
            pass

    def stem_blend_callback(self, sender, app_data):
        try:
            v = float(app_data)
        except Exception:
            return
        v = max(0.0, min(1.0, v))
        try:
            with self.mixer_state.lock:
                self.mixer_state.stem_blend = v
        except Exception:
            pass
        try:
            if self.audio is not None:
                self.audio.set_mixer_values(stem_blend=v)
        except Exception:
            pass
        try:
            self._tutorial_record_action({"type": "set", "tag": "stem_blend_slider", "value": float(v)})
        except Exception:
            pass

    def lane_param_callback(self, sender, app_data, user_data):
        lane_idx = user_data

        deck = str(getattr(self, "_stem_eq_panel", "A") or "A").upper()
        lane_state = getattr(self.mixer_state, "lanes_b", self.mixer_state.lanes) if deck == "B" else self.mixer_state.lanes

        gain_db = dpg.get_value(f"gain_{lane_idx}")
        pan = dpg.get_value(f"pan_{lane_idx}")
        mute = dpg.get_value(f"mute_{lane_idx}")
        solo = dpg.get_value(f"solo_{lane_idx}")
        hp = dpg.get_value(f"hp_{lane_idx}")
        lp = dpg.get_value(f"lp_{lane_idx}")
        rev = dpg.get_value(f"rev_{lane_idx}")
        dly = dpg.get_value(f"dly_{lane_idx}")

        try:
            with self.mixer_state.lock:
                lane_state[lane_idx].gain = 10.0 ** (float(gain_db) / 20.0)
                lane_state[lane_idx].pan = float(pan)
                lane_state[lane_idx].mute = bool(mute)
                lane_state[lane_idx].solo = bool(solo)
                lane_state[lane_idx].hp_cutoff = float(hp)
                lane_state[lane_idx].lp_cutoff = float(lp)
                lane_state[lane_idx].send_reverb = float(rev)
                lane_state[lane_idx].send_delay = float(dly)
        except Exception:
            pass

        try:
            if self.audio is not None:
                gain_lin = float(lane_state[lane_idx].gain)
                self.audio.set_lane_values(
                    lane_idx,
                    deck=deck,
                    gain=gain_lin,
                    pan=float(pan),
                    mute=bool(mute),
                    solo=bool(solo),
                    hp_cutoff=float(hp),
                    lp_cutoff=float(lp),
                    send_reverb=float(rev),
                    send_delay=float(dly),
                )
        except Exception:
            pass

        try:
            self._tutorial_record_action(
                {
                    "type": "set_lane",
                    "lane": int(lane_idx),
                    "gain_db": float(gain_db),
                    "pan": float(pan),
                    "hp": float(hp),
                    "lp": float(lp),
                    "rev": float(rev),
                    "dly": float(dly),
                    "mute": bool(mute),
                    "solo": bool(solo),
                }
            )
        except Exception:
            pass

    def clip_callback(self, sender, app_data, user_data):
        lane, slot = user_data
        self._queue_clip(self._clip_grid_deck, lane, slot, record=True)

    def scene_callback(self, sender, app_data, user_data):
        scene = user_data
        self._trigger_scene(self._clip_grid_deck, scene, record=True)

    def scene_a_callback(self, sender, app_data, user_data):
        scene = int(user_data)
        try:
            with self.mixer_state.lock:
                self.mixer_state.scene_a_idx = scene
        except Exception:
            pass
        if dpg.does_item_exist("scene_a_sel"):
            dpg.set_value("scene_a_sel", f"{scene+1}")
        try:
            if self.audio is not None:
                self.audio.set_mixer_values(scene_a_idx=int(scene))
        except Exception:
            pass

        for deck in ("A", "B"):
            cm = self._get_clip_manager_for_deck(deck)
            if cm is None:
                continue
            try:
                cm.select_scene_a(int(scene), launch=False)
            except Exception:
                try:
                    cm.scene_a = int(scene)
                except Exception:
                    pass
        try:
            self._tutorial_record_action({"type": "scene_a", "scene": int(scene)})
        except Exception:
            pass

        try:
            self._refresh_clip_grid_colors()
        except Exception:
            pass

    def scene_b_callback(self, sender, app_data, user_data):
        scene = int(user_data)
        try:
            with self.mixer_state.lock:
                self.mixer_state.scene_b_idx = scene
        except Exception:
            pass
        if dpg.does_item_exist("scene_b_sel"):
            dpg.set_value("scene_b_sel", f"{scene+1}")
        try:
            if self.audio is not None:
                self.audio.set_mixer_values(scene_b_idx=int(scene))
        except Exception:
            pass

        for deck in ("A", "B"):
            cm = self._get_clip_manager_for_deck(deck)
            if cm is None:
                continue
            try:
                cm.select_scene_b(int(scene), launch=False)
            except Exception:
                try:
                    cm.scene_b = int(scene)
                except Exception:
                    pass
        try:
            self._tutorial_record_action({"type": "scene_b", "scene": int(scene)})
        except Exception:
            pass

        try:
            self._refresh_clip_grid_colors()
        except Exception:
            pass

    def scene_store_a_callback(self):
        try:
            idx = int(getattr(self.mixer_state, "scene_a_idx", 0))
        except Exception:
            idx = 0
        try:
            self.mixer_state.store_scene(idx)
        except Exception:
            pass
        try:
            if self.audio is not None:
                self.audio.store_scene(int(idx))
        except Exception:
            pass
        try:
            self._tutorial_record_action({"type": "store_scene_a"})
        except Exception:
            pass

    def scene_store_b_callback(self):
        try:
            idx = int(getattr(self.mixer_state, "scene_b_idx", 1))
        except Exception:
            idx = 1
        try:
            self.mixer_state.store_scene(idx)
        except Exception:
            pass
        try:
            if self.audio is not None:
                self.audio.store_scene(int(idx))
        except Exception:
            pass

    def scene_morph_callback(self, sender, app_data):
        try:
            v = float(app_data)
        except Exception:
            return
        if v < 0.0:
            v = 0.0
        if v > 1.0:
            v = 1.0
        try:
            with self.mixer_state.lock:
                self.mixer_state.scene_xfade = v
        except Exception:
            pass
        try:
            if self.audio is not None:
                self.audio.set_mixer_values(scene_xfade=v)
        except Exception:
            pass

    def patterns_apply_callback(self):
        deck = str(getattr(self, "_clip_grid_deck", "A")).upper()
        cm = self._get_clip_manager_for_deck(deck)
        if not cm:
            return
        for i in range(8):
            tag = f"pat_{i}"
            if not dpg.does_item_exist(tag):
                continue
            pat = str(dpg.get_value(tag) or "")
            try:
                cm.set_pattern(i, pat)
            except Exception:
                pass
            try:
                if self.audio is not None:
                    self.audio.set_pattern(deck, i, pat)
            except Exception:
                pass

    def patterns_clear_callback(self):
        deck = str(getattr(self, "_clip_grid_deck", "A")).upper()
        cm = self._get_clip_manager_for_deck(deck)
        if not cm:
            return
        cm.clear_patterns()
        try:
            if self.audio is not None:
                self.audio.clear_patterns(deck)
        except Exception:
            pass
        for i in range(8):
            tag = f"pat_{i}"
            if dpg.does_item_exist(tag):
                dpg.set_value(tag, "")
