"""Tests for the pure functions and the storage layer of VNC-Menu.

No GUI, no Windows API, no network, no PsExec. Run with:

    python -m unittest discover -s tests -v
"""

import os
import json
import sys
import threading
import types
import unittest
from pathlib import Path

import vncmenu_loader


class VncMenuTestCase(unittest.TestCase):
    """Base class: one fresh sandboxed copy of the application per class."""

    @classmethod
    def setUpClass(cls):
        cls.app, cls.sandbox = vncmenu_loader.load_app()

    @classmethod
    def tearDownClass(cls):
        vncmenu_loader.release_sandbox(cls.sandbox)


# ---------------------------------------------------------------- versions


class TestVersions(VncMenuTestCase):
    def test_parse_version_orders_numerically(self):
        parse = self.app.parse_version
        self.assertEqual(parse("1.6.1"), (1, 6, 1))
        self.assertEqual(parse("v1.6.1"), (1, 6, 1))
        self.assertGreater(parse("1.10.0"), parse("1.9.9"))
        self.assertGreater(parse("2.0"), parse("1.99.99"))
        self.assertEqual(parse(""), (0,))
        self.assertEqual(parse(None), (0,))

    def test_current_version_is_not_seen_as_outdated(self):
        parse = self.app.parse_version
        self.assertFalse(parse(self.app.APP_VERSION) > parse(self.app.APP_VERSION))

    def test_normalize_release_version_strips_leading_v(self):
        self.assertEqual(self.app.normalize_release_version("v1.6.1"), "1.6.1")
        self.assertEqual(self.app.normalize_release_version("1.6.1"), "1.6.1")
        self.assertEqual(self.app.normalize_release_version("  V2.0 "), "2.0")


# ------------------------------------------------------------ normalizers


class TestNormalizers(VncMenuTestCase):
    def test_sanitize_viewer_falls_back_to_default(self):
        self.assertEqual(self.app.sanitize_viewer("realvnc"), self.app.VIEWER_REALVNC)
        self.assertEqual(self.app.sanitize_viewer("  RealVNC "), self.app.VIEWER_REALVNC)
        self.assertEqual(self.app.sanitize_viewer("nonsense"), self.app.DEFAULT_VIEWER)
        self.assertEqual(self.app.sanitize_viewer(None), self.app.DEFAULT_VIEWER)

    def test_viewer_display_name(self):
        self.assertEqual(self.app.viewer_display_name("realvnc"), "RealVNC")
        self.assertEqual(self.app.viewer_display_name("ultravnc"), "UltraVNC")
        self.assertEqual(self.app.viewer_display_name("garbage"), "UltraVNC")

    def test_normalize_login_mode(self):
        self.assertEqual(self.app.normalize_login_mode("manual"), self.app.LOGIN_MODE_MANUAL)
        self.assertEqual(self.app.normalize_login_mode("whatever"), self.app.LOGIN_MODE_AUTO)

    def test_hosts_source_round_trip(self):
        for source, label in (
            (self.app.HOSTS_SOURCE_SHARED, "Padrão"),
            (self.app.HOSTS_SOURCE_CUSTOM, "Personalizada"),
            (self.app.HOSTS_SOURCE_EMPTY, "Vazia"),
        ):
            self.assertEqual(self.app.normalize_hosts_source(source), source)
            self.assertEqual(self.app.hosts_source_display_name(source), label)
        # An unknown value means "not chosen yet", which triggers the first-run dialog.
        self.assertEqual(self.app.normalize_hosts_source("bogus"), "")

    def test_color_scheme(self):
        self.assertEqual(self.app.normalize_color_scheme("purple"), self.app.COLOR_SCHEME_PURPLE)
        self.assertEqual(self.app.normalize_color_scheme("bogus"), self.app.COLOR_SCHEME_BLUE)
        self.assertEqual(self.app.color_scheme_display_name("purple"), "Roxo")
        self.assertEqual(self.app.color_scheme_display_name("blue"), "Azul")

    def test_get_host_columns_is_clamped(self):
        self.assertEqual(self.app.get_host_columns({"host_columns": 0}), 1)
        self.assertEqual(self.app.get_host_columns({"host_columns": 99}), 6)
        self.assertEqual(self.app.get_host_columns({"host_columns": "abc"}), 3)
        self.assertEqual(self.app.get_host_columns({}), 3)


# --------------------------------------------------------------- filenames


class TestFilenames(VncMenuTestCase):
    def test_safe_filename_replaces_windows_reserved_characters(self):
        self.assertEqual(self.app.safe_filename('a<b>c:d"e/f\\g|h?i*j'), "a_b_c_d_e_f_g_h_i_j")
        self.assertEqual(self.app.safe_filename("   "), "host")
        self.assertEqual(self.app.safe_filename(""), "host")

    def test_realvnc_profile_name_never_doubles_the_extension(self):
        name = self.app.realvnc_profile_name
        self.assertEqual(name("Setor", "PC01"), "Setor_PC01.vnc")
        self.assertEqual(name("Setor", "PC01.vnc"), "Setor_PC01.vnc")
        self.assertEqual(name("Setor", "PC01.vnc.vnc"), "Setor_PC01.vnc")
        self.assertEqual(name(None, "PC01"), "PC01.vnc")
        self.assertEqual(name("", "PC01"), "PC01.vnc")


# ---------------------------------------------------------------- geometry


class TestGeometry(VncMenuTestCase):
    def test_is_valid_geometry(self):
        self.assertTrue(self.app.is_valid_geometry("980x610+100+50"))
        self.assertTrue(self.app.is_valid_geometry("980x610-10-20"))
        self.assertFalse(self.app.is_valid_geometry("980x610"))
        self.assertFalse(self.app.is_valid_geometry("garbage"))
        self.assertFalse(self.app.is_valid_geometry(""))
        self.assertFalse(self.app.is_valid_geometry(None))

    def test_get_geometry_size(self):
        self.assertEqual(self.app.get_geometry_size("980x610+100+50", 1, 2), (980, 610))
        self.assertEqual(self.app.get_geometry_size("980x610-10-20", 1, 2), (980, 610))
        self.assertEqual(self.app.get_geometry_size("garbage", 800, 600), (800, 600))


# ------------------------------------------------------------- hosts model


class _FakeWindow:
    """Just enough of a Tk window for save_window_geometry()."""

    def __init__(self, geometry="900x700+10+20"):
        self._geometry = geometry

    def state(self):
        return "normal"

    def update_idletasks(self):
        pass

    def geometry(self):
        return self._geometry


class TestGeometryPolicy(VncMenuTestCase):
    def setUp(self):
        self.app.bootstrap_directories()

    def test_only_resizable_windows_persist_geometry(self):
        for key in ("main", "window_hosts_config", "window_list_editor_Editar Unidades"):
            self.assertTrue(self.app.is_persisted_geometry_key(key), key)

        # Every fixed-size dialog that used to persist, including the bumped keys.
        for key in (
            "window_settings", "window_settings_v4",
            "window_about", "window_about_v3",
            "window_viewer_paths_v3", "window_psexec_path", "window_credentials",
            "dialog_text_input_v2", "dialog_host_details_v2", "dialog_custom_connection_v2",
            "", None,
        ):
            self.assertFalse(self.app.is_persisted_geometry_key(key), key)

    def test_prune_removes_orphans_and_keeps_the_real_ones(self):
        settings = self.app.load_settings()
        settings["window_geometries"] = {
            "main": "980x610+0+0",
            "window_hosts_config": "1060x660+5+5",
            "window_list_editor_Editar Setores": "520x520+7+7",
            "window_settings_v4": "540x720+1+1",
            "window_settings_v3": "540x700+1+1",
            "window_about_v3": "610x430+2+2",
            "dialog_text_input_v2": "460x235+3+3",
        }
        self.app.save_settings(settings)

        removed = self.app.prune_window_geometries(settings)
        self.assertEqual(removed, 4)
        self.assertEqual(
            set(settings["window_geometries"]),
            {"main", "window_hosts_config", "window_list_editor_Editar Setores"},
        )
        # The cleanup must be persisted, not only applied in memory.
        self.assertEqual(
            set(self.app.load_settings()["window_geometries"]),
            {"main", "window_hosts_config", "window_list_editor_Editar Setores"},
        )

    def test_prune_is_a_no_op_on_a_clean_profile(self):
        settings = self.app.load_settings()
        settings["window_geometries"] = {"main": "980x610+0+0"}
        self.app.save_settings(settings)
        self.assertEqual(self.app.prune_window_geometries(settings), 0)

    def test_save_window_geometry_refuses_a_non_persisted_key(self):
        settings = self.app.load_settings()
        settings["window_geometries"] = {}
        self.app.save_settings(settings)

        self.app.save_window_geometry(_FakeWindow(), "window_settings_v4")
        self.assertEqual(self.app.load_settings()["window_geometries"], {})

        self.app.save_window_geometry(_FakeWindow("1000x800+30+40"), "main")
        stored = self.app.load_settings()["window_geometries"]
        self.assertEqual(stored, {"main": "1000x800+30+40"})

    def test_save_window_geometry_ignores_an_invalid_geometry_string(self):
        settings = self.app.load_settings()
        settings["window_geometries"] = {}
        self.app.save_settings(settings)
        self.app.save_window_geometry(_FakeWindow("zoomed"), "main")
        self.assertEqual(self.app.load_settings()["window_geometries"], {})


class TestTemplateSeeding(VncMenuTestCase):
    """data/template.vnc.example ships in the repo; template.vnc never does."""

    def setUp(self):
        self.app.bootstrap_directories()
        self.example = self.app.TEMPLATE_VNC_EXAMPLE
        self.example.parent.mkdir(parents=True, exist_ok=True)
        self.example.write_text("[connection]\nhost=\nport=5900\n", encoding="utf-8")
        self.app.TEMPLATE_VNC.unlink(missing_ok=True)

    def test_bootstrap_seeds_template_from_the_example(self):
        problems = self.app.bootstrap_directories()
        self.assertEqual(problems, [])
        self.assertTrue(self.app.TEMPLATE_VNC.is_file())
        self.assertEqual(
            self.app.TEMPLATE_VNC.read_text(encoding="utf-8"),
            self.example.read_text(encoding="utf-8"),
        )

    def test_an_existing_template_is_never_overwritten(self):
        self.app.TEMPLATE_VNC.write_text("[connection]\nhost=meu-ajuste\n", encoding="utf-8")
        self.app.bootstrap_directories()
        self.assertIn("meu-ajuste", self.app.TEMPLATE_VNC.read_text(encoding="utf-8"))

    def test_a_missing_example_is_not_an_error(self):
        self.example.unlink(missing_ok=True)
        self.assertEqual(self.app.bootstrap_directories(), [])
        self.assertFalse(self.app.TEMPLATE_VNC.exists())


class TestShippedTemplateExample(unittest.TestCase):
    """Guards the actual file that goes into the repository."""

    @classmethod
    def setUpClass(cls):
        cls.path = vncmenu_loader.REPO_ROOT / "data" / "template.vnc.example"

    def setUp(self):
        if not self.path.is_file():
            self.skipTest("data/template.vnc.example not present in this checkout")
        self.values = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("["):
                key, _, value = line.partition("=")
                self.values[key.strip()] = value.strip()

    def test_carries_no_credentials(self):
        """UltraVNC stores a saved password as passwd / passwd2."""
        for key in ("passwd", "passwd2", "password", "user", "username"):
            self.assertNotIn(key, self.values)

    def test_carries_no_real_host_or_proxy(self):
        self.assertEqual(self.values.get("host", ""), "")
        self.assertEqual(self.values.get("proxyhost", ""), "")
        self.assertEqual(self.values.get("proxyport", "0"), "0")

    def test_dsm_plugin_settings_are_internally_consistent(self):
        """SecureVNC is required in this deployment, so the pair must agree.

        UseDSMPlugin=1 with an empty DSMPlugin silently disables encryption;
        a plugin name with UseDSMPlugin=0 is dead configuration. Either the two
        are both on or both off - never half.
        """
        enabled = self.values.get("UseDSMPlugin") == "1"
        plugin = self.values.get("DSMPlugin", "").strip()
        self.assertEqual(
            enabled,
            bool(plugin),
            f"UseDSMPlugin={self.values.get('UseDSMPlugin')!r} "
            f"but DSMPlugin={plugin!r}",
        )
        if enabled:
            self.assertTrue(plugin.lower().endswith(".dsm"), plugin)

    def test_port_matches_the_application_constant(self):
        app, sandbox = vncmenu_loader.load_app()
        try:
            self.assertEqual(self.values.get("port"), str(app.PORT))
        finally:
            vncmenu_loader.release_sandbox(sandbox)


class _RecordedButton:
    """Captures the CTkButton constructor and pack() arguments."""

    made = []

    def __init__(self, master, **kwargs):
        self.master = master
        self.kwargs = kwargs
        self.pack_kwargs = None
        _RecordedButton.made.append(self)

    def pack(self, **kwargs):
        self.pack_kwargs = kwargs

    def configure(self, **kwargs):
        self.kwargs.update(kwargs)


class TestModalDialogShell(VncMenuTestCase):
    """The shared dialog chrome introduced to remove ~8 copies of the same block."""

    def _build(self, specs, **dialog_kwargs):
        _RecordedButton.made = []
        original = self.app.ctk.CTkButton
        self.app.ctk.CTkButton = _RecordedButton
        try:
            dialog = self.app.ModalDialog(None, "Titulo", **dialog_kwargs)
            dialog.add_buttons(specs)
        finally:
            self.app.ctk.CTkButton = original
        return dialog, list(_RecordedButton.made)

    def test_every_button_style_maps_to_real_theme_keys(self):
        for style, keys in self.app.DIALOG_BUTTON_STYLES.items():
            for key in keys:
                self.assertIn(key, self.app.THEME, f"{style} -> {key}")

    def test_button_row_is_created_lazily(self):
        """It must pack after the dialog's own widgets, not before them."""
        dialog = self.app.ModalDialog(None, "Titulo", heading="h", message="m")
        self.assertIsNone(dialog._buttons)
        self.assertIsNotNone(dialog.buttons)
        self.assertIs(dialog.buttons, dialog._buttons)  # created once

    def test_only_the_leftmost_button_has_no_left_gap(self):
        """Buttons pack right to left; the original layout gapped all but the last."""
        _dialog, made = self._build([
            {"text": "Cancelar", "command": lambda: None},
            {"text": "Meio", "command": lambda: None},
            {"text": "Confirmar", "command": lambda: None, "style": "primary"},
        ])
        self.assertEqual([b.pack_kwargs["side"] for b in made], ["right"] * 3)
        self.assertEqual(made[0].pack_kwargs["padx"], (8, 0))
        self.assertEqual(made[1].pack_kwargs["padx"], (8, 0))
        self.assertEqual(made[2].pack_kwargs["padx"], 0)

    def test_single_button_has_no_gap(self):
        _dialog, made = self._build([{"text": "Fechar", "command": lambda: None}])
        self.assertEqual(made[0].pack_kwargs["padx"], 0)

    def test_style_resolves_to_theme_colours(self):
        _dialog, made = self._build([
            {"text": "A", "command": lambda: None, "style": "danger"},
            {"text": "B", "command": lambda: None, "style": "primary"},
        ])
        self.assertEqual(made[0].kwargs["fg_color"], self.app.THEME["danger"])
        self.assertEqual(made[0].kwargs["hover_color"], self.app.THEME["danger_hover"])
        self.assertEqual(made[1].kwargs["fg_color"], self.app.THEME["accent"])

    def test_style_defaults_to_secondary(self):
        _dialog, made = self._build([{"text": "A", "command": lambda: None}])
        self.assertEqual(made[0].kwargs["fg_color"], self.app.THEME["surface_3"])

    def test_width_and_height_are_omitted_when_not_given(self):
        """ask_text relied on CustomTkinter's default button size."""
        _dialog, made = self._build([
            {"text": "A", "command": lambda: None},
            {"text": "B", "command": lambda: None, "width": 125, "height": 38},
        ])
        self.assertNotIn("width", made[0].kwargs)
        self.assertNotIn("height", made[0].kwargs)
        self.assertEqual(made[1].kwargs["width"], 125)
        self.assertEqual(made[1].kwargs["height"], 38)

    def test_close_sets_the_result(self):
        dialog = self.app.ModalDialog(None, "Titulo")
        self.assertIsNone(dialog.result)
        dialog.close("valor")
        self.assertEqual(dialog.result, "valor")

    def test_close_without_a_result_keeps_the_preset_one(self):
        """shared_hosts_edit_warning presets 'cancel' before showing."""
        dialog = self.app.ModalDialog(None, "Titulo")
        dialog.result = "cancel"
        dialog.close()
        self.assertEqual(dialog.result, "cancel")


class TestDialogConsistency(unittest.TestCase):
    """Source-level guard: closing a dialog with the X must always work.

    Before the shared chrome existed, four dialogs never set
    WM_DELETE_WINDOW, so the window's X button silently did nothing.
    """

    DIALOGS = (
        "confirm_action",
        "confirm_empty_list_overwrite",
        "ask_text",
        "show_psexec_required_dialog",
        "ask_host_details",
        "ask_custom_connection",
        "show_realvnc_profile_dialog",
        "shared_hosts_edit_warning",
        "choose_hosts_source_dialog",
        "show_psexec_error_dialog",
    )

    @classmethod
    def setUpClass(cls):
        import ast

        cls.functions = {}
        for module_path in vncmenu_loader.UI_MODULES:
            source = module_path.read_text(encoding="utf-8")
            for node in ast.parse(source).body:
                if isinstance(node, ast.FunctionDef):
                    cls.functions[node.name] = node

    def test_every_dialog_handles_the_window_close_button(self):
        import ast

        missing = []
        for name in self.DIALOGS:
            node = self.functions.get(name)
            self.assertIsNotNone(node, f"{name} not found")
            direct = any(
                isinstance(c, ast.Constant) and c.value == "WM_DELETE_WINDOW"
                for c in ast.walk(node)
            )
            # ModalDialog.show() wires the protocol for its callers.
            via_shell = any(
                isinstance(c, ast.Call)
                and isinstance(c.func, ast.Attribute)
                and c.func.attr == "show"
                for c in ast.walk(node)
            )
            if not (direct or via_shell):
                missing.append(name)
        self.assertEqual(missing, [], f"dialogs ignoring the X button: {missing}")

    def test_every_dialog_binds_escape(self):
        import ast

        missing = []
        for name in self.DIALOGS:
            node = self.functions[name]
            direct = any(
                isinstance(c, ast.Constant) and c.value == "<Escape>"
                for c in ast.walk(node)
            )
            via_shell = any(
                isinstance(c, ast.Call)
                and isinstance(c.func, ast.Attribute)
                and c.func.attr == "show"
                for c in ast.walk(node)
            )
            if not (direct or via_shell):
                missing.append(name)
        self.assertEqual(missing, [], f"dialogs without Escape: {missing}")


class TestProgressWindows(VncMenuTestCase):
    """The three dialogs now share one implementation; guard the call shapes."""

    def test_all_three_share_the_base_class(self):
        base = self.app.IndeterminateProgressWindow
        for cls in (
            self.app.QwinstaProgressWindow,
            self.app.UpdateCheckProgressWindow,
        ):
            self.assertTrue(issubclass(cls, base), cls.__name__)

    def test_close_is_defined_once_on_the_base(self):
        base = self.app.IndeterminateProgressWindow
        self.assertIn("close", vars(base))
        for cls in (
            self.app.QwinstaProgressWindow,
            self.app.UpdateCheckProgressWindow,
        ):
            self.assertNotIn("close", vars(cls))
            self.assertIs(cls.close, base.close)

    def test_signatures_still_match_the_call_sites(self):
        import inspect

        # (self, parent, ...) - matches QwinstaProgressWindow(self, label, len(hosts))
        inspect.signature(self.app.QwinstaProgressWindow.__init__).bind(
            None, None, "Unidade > Setor", 3
        )
        inspect.signature(self.app.UpdateCheckProgressWindow.__init__).bind(None, None)
        inspect.signature(self.app.IndeterminateProgressWindow.__init__).bind(
            None, None, title="t", heading="h", description="d"
        )

    def test_base_requires_its_text_arguments(self):
        import inspect

        with self.assertRaises(TypeError):
            inspect.signature(self.app.IndeterminateProgressWindow.__init__).bind(None, None)


class TestHostsModel(VncMenuTestCase):
    def test_sanitize_host_list_drops_entries_without_a_host(self):
        rows = self.app.sanitize_host_list(
            [
                {"name": "PC01", "host": "10.0.0.1", "viewer": "realvnc"},
                {"name": "No host", "host": ""},
                {"name": "Legacy key", "ip": "10.0.0.2"},
                "not a dict",
            ]
        )
        self.assertEqual(
            rows,
            [
                {"name": "PC01", "host": "10.0.0.1", "viewer": "realvnc"},
                {"name": "Legacy key", "host": "10.0.0.2", "viewer": self.app.DEFAULT_VIEWER},
            ],
        )

    def test_sanitize_sector_list_keeps_empty_sectors(self):
        sectors = self.app.sanitize_sector_list([{"name": "Vazio", "hosts": []}])
        self.assertEqual(sectors, [{"name": "Vazio", "hosts": []}])

    def test_normalize_hosts_data_rejects_junk(self):
        for junk in (None, [], "text", 42, {}, {"units": []}):
            data = self.app.normalize_hosts_data(junk)
            self.assertEqual(self.app.get_unit_names(data), ["Geral"])

    def test_normalize_hosts_data_returns_a_deep_copy_of_the_defaults(self):
        """Regression: dict.copy() shared the units list with DEFAULT_HOSTS."""
        baseline = len(self.app.DEFAULT_HOSTS["units"][0]["sectors"][0]["hosts"])

        first = self.app.normalize_hosts_data(None)
        first["units"][0]["sectors"][0]["hosts"].append({"name": "X", "host": "h", "viewer": "ultravnc"})
        first["units"].append({"name": "Injetada", "sectors": []})

        # The module-level defaults must be untouched by the mutation above.
        self.assertEqual(
            len(self.app.DEFAULT_HOSTS["units"][0]["sectors"][0]["hosts"]), baseline
        )
        self.assertEqual(len(self.app.DEFAULT_HOSTS["units"]), 1)

        second = self.app.normalize_hosts_data(None)
        self.assertEqual(len(second["units"][0]["sectors"][0]["hosts"]), baseline)
        self.assertEqual(self.app.get_unit_names(second), ["Geral"])

    def test_empty_hosts_survives_normalization_with_zero_hosts(self):
        """Regression: the 'Vazia' option used to write DEFAULT_HOSTS."""
        data = self.app.normalize_hosts_data(self.app.EMPTY_HOSTS)
        self.assertEqual(self.app.get_unit_names(data), ["Geral"])
        self.assertEqual(self.app.get_sector_names(data, "Geral"), ["Geral"])
        self.assertEqual(self.app.get_sector_hosts(data, "Geral", "Geral"), [])

    def test_lookup_helpers_return_none_for_missing_entries(self):
        data = self.app.normalize_hosts_data(None)
        self.assertIsNone(self.app.get_unit_by_name(data, "Inexistente"))
        self.assertIsNone(self.app.get_sector_by_name(data, "Geral", "Inexistente"))
        self.assertEqual(self.app.get_sector_hosts(data, "Geral", "Inexistente"), [])


# --------------------------------------------------------------- formatting


class TestFormatting(VncMenuTestCase):
    def test_format_printers_output_aligns_and_handles_empty(self):
        self.assertEqual(self.app.format_printers_output([]), "Nenhuma impressora encontrada.")
        text = self.app.format_printers_output([("HP LaserJet", "10.0.0.5"), ("PDF", "USB")])
        lines = text.splitlines()
        self.assertTrue(lines[0].startswith("NOME"))
        self.assertIn("HP LaserJet", lines[2])
        self.assertIn("10.0.0.5", lines[2])

    def test_format_users_output_handles_empty(self):
        self.assertEqual(self.app.format_users_output([]), "Nenhum host encontrado.")
        text = self.app.format_users_output([("PC01", "joao")])
        self.assertIn("USUÁRIO", text.splitlines()[0])
        self.assertIn("joao", text)

    def test_format_release_notes_strips_markdown(self):
        notes = self.app.format_release_notes_for_display(
            "# VNC-Menu v1.6.1\n"
            "## Correções\n"
            "- Corrige [algo](https://example.com)\n"
            "- Ajusta `código`\n"
            "```\nignorado\n```\n"
        )
        self.assertNotIn("#", notes)
        self.assertNotIn("```", notes)
        self.assertNotIn("https://example.com", notes)
        self.assertIn("CORREÇÕES", notes)
        self.assertIn("• Corrige algo", notes)
        self.assertIn("• Ajusta código", notes)

    def test_format_release_notes_handles_empty_body(self):
        self.assertEqual(
            self.app.format_release_notes_for_display(""),
            "Nenhuma nota de versão informada.",
        )

    def test_decode_process_output_survives_non_utf8_bytes(self):
        # cp850 "ç" - must not raise, whatever the fallback picks.
        self.assertIsInstance(self.app._decode_process_output(b"\x87"), str)
        self.assertEqual(self.app._decode_process_output(""), "")
        self.assertEqual(self.app._decode_process_output(None), "")
        self.assertEqual(self.app._decode_process_output("já texto"), "já texto")


# ------------------------------------------------------------ psexec errors


class TestPsExecDiagnosis(VncMenuTestCase):
    def test_known_categories_are_recognised(self):
        cases = {
            "Access is denied.": "access_denied",
            "Acesso negado": "access_denied",
            "Logon failure: unknown user name or password": "logon_failure",
            "The network path was not found": "network_path",
            "The RPC server is unavailable": "rpc_unavailable",
            "Could not start PSEXESVC service": "psexesvc",
        }
        for output, expected in cases.items():
            _summary, _hint, category = self.app._diagnose_psexec_failure(output)
            self.assertEqual(category, expected, output)

    def test_connect_timeout_is_recognised_from_the_real_psexec_wording(self):
        """Observed in the field: exit code 1460 with this exact stderr."""
        stderr = "\nConnecting to 10.104.137.66...Timeout accessing 10.104.137.66."
        summary, hint, category = self.app._diagnose_psexec_failure(stderr, returncode=1460)
        self.assertEqual(category, "connect_timeout")
        self.assertNotIn("1460", summary)  # not the generic exit-code message
        self.assertIn("445", hint)

    def test_known_error_codes_are_diagnosed_without_any_message_text(self):
        """Covers output localised into wording the string table does not carry."""
        expected = {
            53: "network_path",
            67: "admin_share",
            1326: "logon_failure",
            1460: "connect_timeout",
            1722: "rpc_unavailable",
        }
        for code, category in expected.items():
            _summary, _hint, actual = self.app._diagnose_psexec_failure("", returncode=code)
            self.assertEqual(actual, category, code)

    def test_return_code_table_never_swallows_an_ordinary_exit_code(self):
        """PsExec forwards the remote program's exit code, so small ones stay generic."""
        for code in (1, 2, 3, 4, 5, 9, 255):
            _summary, _hint, category = self.app._diagnose_psexec_failure("", returncode=code)
            self.assertEqual(category, "exit_code", code)

    def test_message_text_wins_over_the_return_code(self):
        summary, _hint, category = self.app._diagnose_psexec_failure(
            "Access is denied.", returncode=1460
        )
        self.assertEqual(category, "access_denied")

    def test_unknown_output_with_exit_code(self):
        _summary, _hint, category = self.app._diagnose_psexec_failure("blah", returncode=3)
        self.assertEqual(category, "exit_code")

    def test_unknown_output_without_exit_code(self):
        _summary, _hint, category = self.app._diagnose_psexec_failure("blah", returncode=0)
        self.assertEqual(category, "invalid_output")


# ------------------------------------------------------------ release assets


class TestReleaseAssets(VncMenuTestCase):
    def test_zip_asset_preference_order(self):
        release = {
            "tag_name": "v1.7.0",
            "assets": [
                {"name": "outro.zip"},
                {"name": "VNC-Menu-v1.7.0.zip"},
            ],
        }
        self.assertEqual(self.app.find_release_zip_asset(release)["name"], "VNC-Menu-v1.7.0.zip")

    def test_zip_asset_requires_a_zip(self):
        with self.assertRaises(RuntimeError):
            self.app.find_release_zip_asset({"tag_name": "v1.7.0", "assets": [{"name": "notes.txt"}]})

    def test_checksum_taken_from_asset_digest(self):
        digest = "a" * 64
        checksum = self.app.get_release_asset_checksum(
            {"assets": []}, {"name": "x.zip", "digest": f"sha256:{digest}"}
        )
        self.assertEqual(checksum, digest)

    def test_missing_checksum_blocks_the_update(self):
        """Security: an update without a verifiable digest must not proceed."""
        with self.assertRaises(RuntimeError):
            self.app.get_release_asset_checksum({"assets": []}, {"name": "x.zip"})


# ------------------------------------------------------------------ storage


class TestInstallRootAnchor(VncMenuTestCase):
    """SCRIPT_DIR decides where data/ and logs/ live.

    It must follow the entry script, not whichever module the line happens to
    sit in. If it ever anchors on __file__ again, moving the code into a
    package silently relocates data/ and the real host list is orphaned with
    no error at all - so this test is the guard that makes that refactor safe.
    """

    def _entry(self):
        return self.sandbox / "app" / vncmenu_loader.MAIN_SCRIPT.name

    def test_script_dir_is_the_entry_point_folder(self):
        self.assertEqual(self.app.SCRIPT_DIR, self._entry().parent)

    def test_data_and_logs_sit_beside_the_entry_point(self):
        root = self._entry().parent
        self.assertEqual(self.app.DATA_DIR, root / "data")
        self.assertEqual(self.app.LOGS_DIR, root / "logs")
        self.assertEqual(self.app.SHARED_HOSTS_JSON.parent, root / "data")
        self.assertEqual(self.app.TEMPLATE_VNC.parent, root / "data")
        self.assertEqual(self.app.GLOBAL_PATHS_JSON.parent, root / "data")

    def test_data_dir_is_not_nested_inside_a_package_folder(self):
        """The exact failure mode: data/ one level deeper than the entry point."""
        root = self._entry().parent
        self.assertEqual(self.app.DATA_DIR.parent, root)
        self.assertNotIn("vncmenu", self.app.DATA_DIR.relative_to(root).parts)

    def test_detect_install_root_prefers_the_main_module(self):
        import types

        entry = self.sandbox / "outra-pasta" / "VNC-Menu.pyw"
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text("", encoding="utf-8")

        fake_main = types.ModuleType("__main__")
        fake_main.__file__ = str(entry)
        real_main = sys.modules.get("__main__")
        sys.modules["__main__"] = fake_main
        try:
            self.assertEqual(self.app._detect_install_root(), entry.parent)
        finally:
            if real_main is not None:
                sys.modules["__main__"] = real_main

    def test_detect_install_root_uses_the_executable_when_frozen(self):
        original = getattr(sys, "frozen", None)
        sys.frozen = True
        try:
            self.assertEqual(
                self.app._detect_install_root(),
                Path(sys.executable).resolve().parent,
            )
        finally:
            if original is None:
                del sys.frozen
            else:
                sys.frozen = original


class TestStorage(VncMenuTestCase):
    def setUp(self):
        self.problems = self.app.bootstrap_directories()

    def test_import_creates_nothing_and_bootstrap_creates_everything(self):
        self.assertEqual(self.problems, [])
        self.assertTrue(self.app.USER_DATA_DIR.is_dir())
        self.assertTrue(self.app.LOGS_DIR.is_dir())
        self.assertTrue(self.app.DATA_DIR.is_dir())
        self.assertTrue(self.app.REALVNC_DIR.is_dir())
        self.assertTrue(self.app.SHARED_HOSTS_JSON.is_file())

    def test_bootstrap_reports_problems_instead_of_raising(self):
        """Regression: an import-time failure made the .pyw fail to open silently."""
        clash = self.app.DATA_DIR / "not-a-directory"
        clash.write_text("x", encoding="utf-8")
        with vncmenu_loader.patched_global(self.app, "LOGS_DIR", clash / "logs"):
            problems = self.app.bootstrap_directories()
        self.assertEqual(len(problems), 1)
        self.assertIn("Logs", problems[0])

    def test_save_json_round_trip_with_accents(self):
        target = self.app.DATA_DIR / "round-trip.json"
        payload = {"acentuação": "ção", "list": [1, 2, 3]}
        self.assertTrue(self.app.save_json(payload, target))
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), payload)

    def test_failed_save_keeps_the_previous_file_and_leaves_no_temp(self):
        """Regression: write_text() truncated the destination before writing."""
        target = self.app.DATA_DIR / "keep.json"
        self.app.save_json({"version": 1}, target)

        class Unserializable:
            pass

        with self.assertRaises(TypeError):
            self.app.save_json({"bad": Unserializable()}, target)

        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"version": 1})
        self.assertEqual(list(self.app.DATA_DIR.glob(".*.tmp")), [])

    def test_create_empty_user_hosts_writes_an_empty_list(self):
        self.app.create_empty_user_hosts(overwrite=True)
        data = self.app.normalize_hosts_data(
            json.loads(self.app.USER_HOSTS_JSON.read_text(encoding="utf-8"))
        )
        self.assertEqual(self.app.get_sector_hosts(data, "Geral", "Geral"), [])

    def test_copy_shared_hosts_never_overwrites_an_existing_personal_list(self):
        self.app.save_json(
            {"units": [{"name": "Minha", "sectors": [{"name": "S", "hosts": []}]}]},
            self.app.USER_HOSTS_JSON,
        )
        self.assertEqual(self.app.copy_shared_hosts_to_user(overwrite=False), "existing")
        data = json.loads(self.app.USER_HOSTS_JSON.read_text(encoding="utf-8"))
        self.assertEqual(data["units"][0]["name"], "Minha")

    def test_settings_round_trip_and_defaults_merge(self):
        settings = self.app.load_settings()
        settings["host_columns"] = 5
        self.assertTrue(self.app.save_settings(settings))
        self.assertEqual(self.app.load_settings()["host_columns"], 5)

    def test_settings_reader_ignores_unknown_keys_and_keeps_defaults(self):
        self.app.SETTINGS_JSON.write_text(
            json.dumps({"host_columns": 4, "unknown_key": "x"}), encoding="utf-8"
        )
        settings = self.app.load_settings()
        self.assertEqual(settings["host_columns"], 4)
        self.assertNotIn("unknown_key", settings)
        self.assertIn("dark_mode", settings)

    def test_legacy_viewer_keys_are_still_migrated_into_paths_json(self):
        """The pre-1.5.6 migration path must keep working."""
        self.app.GLOBAL_PATHS_JSON.unlink(missing_ok=True)
        legacy = {"ultravnc_exe": r"C:\legacy\uvnc.exe", "realvnc_exe": r"C:\legacy\real.exe"}
        paths = self.app.load_global_paths(legacy)
        self.assertEqual(paths["ultravnc_exe"], r"C:\legacy\uvnc.exe")
        self.assertEqual(paths["realvnc_exe"], r"C:\legacy\real.exe")

    def test_unreadable_paths_json_is_not_overwritten(self):
        """Regression: a transient read error erased the machine-wide paths."""
        self.app.save_json(
            {"ultravnc_exe": r"C:\real\uvnc.exe", "realvnc_exe": r"C:\real\real.exe", "psexec_exe": ""},
            self.app.GLOBAL_PATHS_JSON,
        )
        corrupt = "{ this is not json"
        self.app.GLOBAL_PATHS_JSON.write_text(corrupt, encoding="utf-8")

        paths = self.app.load_global_paths()
        self.assertEqual(paths["ultravnc_exe"], self.app.ULTRAVNC_EXE)  # in-memory default
        self.assertEqual(
            self.app.GLOBAL_PATHS_JSON.read_text(encoding="utf-8"), corrupt
        )  # file untouched
        backup = self.app.GLOBAL_PATHS_JSON.with_name(self.app.GLOBAL_PATHS_JSON.name + ".bak")
        self.assertTrue(backup.is_file())

    def test_explicit_empty_psexec_path_means_use_path(self):
        normalized = self.app._normalize_global_paths({"psexec_exe": ""})
        self.assertEqual(normalized["psexec_exe"], "")


# --------------------------------------------------------------------- logs


class TestLogging(VncMenuTestCase):
    def setUp(self):
        self.app.bootstrap_directories()
        self.app.ERROR_LOG.unlink(missing_ok=True)
        self.app.ERROR_LOG.with_name(self.app.ERROR_LOG.name + ".1").unlink(missing_ok=True)

    def test_log_exception_appends_instead_of_overwriting(self):
        """Regression: write_text() erased the PsExec failure history."""
        self.app.ERROR_LOG.write_text("PSEXEC PRINTER QUERY ERROR\n", encoding="utf-8")
        try:
            raise ValueError("primeira")
        except ValueError as exc:
            self.app.log_exception(exc)
        try:
            raise KeyError("segunda")
        except KeyError as exc:
            self.app.log_exception(exc)

        text = self.app.ERROR_LOG.read_text(encoding="utf-8")
        self.assertIn("PSEXEC PRINTER QUERY ERROR", text)
        self.assertIn("primeira", text)
        self.assertIn("segunda", text)

    def test_log_exception_outside_an_except_block_uses_the_argument(self):
        self.app.log_exception(RuntimeError("sem except ativo"))
        text = self.app.ERROR_LOG.read_text(encoding="utf-8")
        self.assertIn("RuntimeError: sem except ativo", text)
        self.assertNotIn("NoneType: None", text)

    def test_error_log_rotates_and_keeps_one_generation(self):
        self.app.ERROR_LOG.write_text("x" * (self.app.ERROR_LOG_MAX_BYTES + 1), encoding="utf-8")
        try:
            raise ValueError("depois da rotacao")
        except ValueError as exc:
            self.app.log_exception(exc)

        self.assertTrue(self.app.ERROR_LOG.with_name(self.app.ERROR_LOG.name + ".1").is_file())
        self.assertLess(self.app.ERROR_LOG.stat().st_size, 8192)
        self.assertIn("depois da rotacao", self.app.ERROR_LOG.read_text(encoding="utf-8"))

    def test_audit_log_writes_one_line_per_call(self):
        self.app.AUDIT_LOG.unlink(missing_ok=True)
        self.app.audit_log("TEST_ACTION", "detalhe=1")
        self.app.audit_log("OUTRA_ACAO")
        lines = [ln for ln in self.app.AUDIT_LOG.read_text(encoding="utf-8").splitlines() if ln]
        self.assertEqual(len(lines), 2)
        self.assertIn("action=TEST_ACTION", lines[0])
        self.assertIn("details=detalhe=1", lines[0])

    def test_audit_log_flattens_newlines(self):
        self.app.AUDIT_LOG.unlink(missing_ok=True)
        self.app.audit_log("MULTI", "linha1\nlinha2")
        lines = [ln for ln in self.app.AUDIT_LOG.read_text(encoding="utf-8").splitlines() if ln]
        self.assertEqual(len(lines), 1)


# ------------------------------------------------------------- auto-login


class _FakeDialog:
    """Stands in for a pywinauto WindowSpecification wrapping a real HWND."""

    def __init__(self, handle):
        self.handle = handle

    def wrapper_object(self):
        return self


class TestAutoLoginGuard(VncMenuTestCase):
    """dialog_owns_foreground() gates typing the UltraVNC password.

    It must deny on anything unexpected, because the caller falls through to
    send_keys(), which types into whatever window holds the foreground.
    """

    def test_denies_a_handle_that_is_not_the_foreground_window(self):
        # Runs everywhere: off Windows user32 is None and the answer is False;
        # on Windows these handles are never the foreground window.
        for handle in (0, 1, -1, 0x7FFFFFFF):
            self.assertFalse(self.app.dialog_owns_foreground(_FakeDialog(handle)), handle)

    def test_denies_a_broken_dialog_object(self):
        class Broken:
            @property
            def handle(self):
                raise RuntimeError("gone")

            def wrapper_object(self):
                raise RuntimeError("gone")

        self.assertFalse(self.app.dialog_owns_foreground(Broken()))

    def test_denies_when_the_handle_is_missing_entirely(self):
        self.assertFalse(self.app.dialog_owns_foreground(object()))
        self.assertFalse(self.app.dialog_owns_foreground(None))

    def test_denies_when_user32_is_unavailable(self):
        if self.app.user32 is not None:
            self.skipTest("user32 is available; covered by the handle tests above")
        self.assertFalse(self.app.dialog_owns_foreground(_FakeDialog(12345)))

    def test_allows_the_real_foreground_window(self):
        """The positive case - only reachable on Windows with a live desktop."""
        if self.app.user32 is None:
            self.skipTest("user32 unavailable outside Windows")

        foreground = self.app.user32.GetForegroundWindow()
        if not foreground:
            self.skipTest("no foreground window in this session")

        self.assertTrue(self.app.dialog_owns_foreground(_FakeDialog(int(foreground))))


if __name__ == "__main__":
    unittest.main()


# -------------------------------------------------------------- porta (F3)


class TestHostPort(VncMenuTestCase):
    """Porta por host: 5900 quando em branco, personalizada quando informada."""

    def test_split_host_port_defaults_to_5900(self):
        self.assertEqual(self.app.split_host_port("10.0.0.5"), ("10.0.0.5", 5900))
        self.assertEqual(self.app.split_host_port("PC01"), ("PC01", 5900))
        self.assertEqual(self.app.split_host_port(""), ("", 5900))
        self.assertEqual(self.app.split_host_port(None), ("", 5900))

    def test_split_host_port_reads_the_double_colon_form(self):
        """Regressão: 'host::5901' virava 'host::5901::5900' na linha de comando."""
        self.assertEqual(self.app.split_host_port("10.0.0.5::5901"), ("10.0.0.5", 5901))
        self.assertEqual(self.app.split_host_port("PC01::5999"), ("PC01", 5999))

    def test_split_host_port_reads_the_display_form(self):
        # vncviewer trata host:N com N < 100 como número de display.
        self.assertEqual(self.app.split_host_port("10.0.0.5:1"), ("10.0.0.5", 5901))
        self.assertEqual(self.app.split_host_port("10.0.0.5:0"), ("10.0.0.5", 5900))
        self.assertEqual(self.app.split_host_port("10.0.0.5:5901"), ("10.0.0.5", 5901))

    def test_split_host_port_ignores_junk(self):
        self.assertEqual(self.app.split_host_port("10.0.0.5::abc"), ("10.0.0.5::abc", 5900))
        self.assertEqual(self.app.split_host_port("10.0.0.5::99999"), ("10.0.0.5", 5900))

    def test_sanitize_port_clamps_and_falls_back(self):
        self.assertEqual(self.app.sanitize_port(5901), 5901)
        self.assertEqual(self.app.sanitize_port("5901"), 5901)
        self.assertEqual(self.app.sanitize_port(0), 5900)
        self.assertEqual(self.app.sanitize_port(70000), 5900)
        self.assertEqual(self.app.sanitize_port("abc"), 5900)
        self.assertEqual(self.app.sanitize_port(None), 5900)

    def test_format_host_port_hides_the_default(self):
        self.assertEqual(self.app.format_host_port("PC01", 5900), "PC01")
        self.assertEqual(self.app.format_host_port("PC01", 5901), "PC01::5901")
        self.assertEqual(self.app.format_host_port("PC01", None), "PC01")

    def test_existing_lists_are_untouched(self):
        """Compatibilidade: hosts sem 'port' continuam sem 'port'."""
        rows = self.app.sanitize_host_list(
            [{"name": "PC01", "host": "10.0.0.5", "viewer": "ultravnc"}]
        )
        self.assertEqual(rows, [{"name": "PC01", "host": "10.0.0.5", "viewer": "ultravnc"}])
        self.assertNotIn("port", rows[0])

    def test_explicit_port_is_kept(self):
        rows = self.app.sanitize_host_list(
            [{"name": "PC01", "host": "10.0.0.5", "viewer": "ultravnc", "port": 5901}]
        )
        self.assertEqual(rows[0]["port"], 5901)

    def test_port_written_into_the_host_is_normalised(self):
        rows = self.app.sanitize_host_list([{"name": "PC01", "host": "10.0.0.5::5901"}])
        self.assertEqual(rows[0]["host"], "10.0.0.5")
        self.assertEqual(rows[0]["port"], 5901)

    def test_default_port_is_never_written_back(self):
        rows = self.app.sanitize_host_list([{"name": "PC01", "host": "10.0.0.5", "port": 5900}])
        self.assertNotIn("port", rows[0])

    def test_invalid_port_falls_back_to_the_default(self):
        rows = self.app.sanitize_host_list([{"name": "PC01", "host": "10.0.0.5", "port": "abc"}])
        self.assertNotIn("port", rows[0])

    def test_round_trip_through_normalize_hosts_data(self):
        data = self.app.normalize_hosts_data({
            "units": [{"name": "U", "sectors": [{"name": "S", "hosts": [
                {"name": "Padrao", "host": "10.0.0.1"},
                {"name": "Custom", "host": "10.0.0.2", "port": 5901},
            ]}]}]
        })
        hosts = self.app.get_sector_hosts(data, "U", "S")
        self.assertNotIn("port", hosts[0])
        self.assertEqual(hosts[1]["port"], 5901)


class TestLoggedUsersQuery(VncMenuTestCase):
    """I2: a consulta era serial e podia levar minutos num setor grande."""

    def setUp(self):
        self.remote = self.app.__modules__["vncmenu.remote"]
        self.original = self.remote._query_logged_user

    def tearDown(self):
        self.remote._query_logged_user = self.original

    def test_order_follows_the_sector_not_completion(self):
        import time

        def fake(item):
            # O primeiro host demora mais: se a ordem viesse da conclusão,
            # ele apareceria por último.
            if item["name"] == "A":
                time.sleep(0.05)
            return (item["name"], "VAZIO")

        self.remote._query_logged_user = fake
        hosts = [{"name": n, "host": f"10.0.0.{i}"} for i, n in enumerate("ABCDE", start=1)]
        output = self.remote.query_all_logged_users(hosts)
        positions = [output.index(n) for n in "ABCDE"]
        self.assertEqual(positions, sorted(positions))

    def test_hosts_are_queried_concurrently(self):
        import time

        def slow(item):
            time.sleep(0.05)
            return (item["name"], "VAZIO")

        self.remote._query_logged_user = slow
        hosts = [{"name": f"PC{i}", "host": f"10.0.0.{i}"} for i in range(8)]

        started = time.monotonic()
        self.remote.query_all_logged_users(hosts)
        elapsed = time.monotonic() - started

        # Serial seriam ~0.40s; em paralelo fica perto de 0.05s.
        self.assertLess(elapsed, 0.25, f"parece serial: {elapsed:.2f}s")

    def test_one_failing_host_does_not_stop_the_others(self):
        def flaky(item):
            if item["name"] == "RUIM":
                raise RuntimeError("boom")
            return (item["name"], "VAZIO")

        self.remote._query_logged_user = flaky
        hosts = [{"name": "BOM1", "host": "1"}, {"name": "RUIM", "host": "2"}, {"name": "BOM2", "host": "3"}]
        with self.assertRaises(RuntimeError):
            self.remote.query_all_logged_users(hosts)

    def test_empty_sector_is_handled(self):
        self.assertEqual(self.remote.query_all_logged_users([]), "Nenhum host encontrado.")

    def test_worker_count_never_exceeds_the_host_count(self):
        seen = []
        real_pool = self.remote.ThreadPoolExecutor

        def spy(max_workers=None, **kw):
            seen.append(max_workers)
            return real_pool(max_workers=max_workers, **kw)

        self.remote.ThreadPoolExecutor = spy
        try:
            self.remote._query_logged_user = lambda item: (item["name"], "VAZIO")
            self.remote.query_all_logged_users([{"name": "X", "host": "1"}])
        finally:
            self.remote.ThreadPoolExecutor = real_pool
        self.assertEqual(seen, [1])

    def test_missing_host_is_reported_without_touching_the_network(self):
        name, result = self.original({"name": "SemHost", "host": ""})
        self.assertEqual((name, result), ("SemHost", "SEM HOST"))


# ---------------------------------------------------------------- busca


def _search_fixture():
    """Two units, so unit scoping can actually be proved."""
    return {
        "units": [
            {
                "name": "Matriz",
                "sectors": [
                    {
                        "name": "Recepção",
                        "hosts": [
                            {"name": "PC-RECEP-01", "host": "192.0.2.11", "viewer": "ultravnc"},
                            {"name": "PC-RECEP-02", "host": "192.0.2.12", "viewer": "ultravnc"},
                        ],
                    },
                    {
                        "name": "Financeiro",
                        "hosts": [
                            {"name": "PC-FIN-01", "host": "192.0.2.41", "viewer": "realvnc"},
                            {"name": "NB-DIRETORIA", "host": "192.0.2.44", "viewer": "ultravnc"},
                        ],
                    },
                ],
            },
            {
                "name": "Filial",
                "sectors": [
                    {
                        "name": "Recepção",
                        "hosts": [
                            {"name": "PC-RECEP-99", "host": "198.51.100.9", "viewer": "ultravnc"},
                        ],
                    }
                ],
            },
        ]
    }


class TestSearchNormalization(VncMenuTestCase):
    def test_accents_and_case_are_ignored(self):
        normalize = self.app.normalize_search_text
        self.assertEqual(normalize("Recepção"), "recepcao")
        self.assertEqual(normalize("MANUTENÇÃO"), "manutencao")
        self.assertEqual(normalize("  Almoxarifado  "), "almoxarifado")

    def test_empty_values_normalize_to_empty_string(self):
        normalize = self.app.normalize_search_text
        self.assertEqual(normalize(None), "")
        self.assertEqual(normalize(""), "")
        self.assertEqual(normalize("   "), "")


class TestSearchFiltering(VncMenuTestCase):
    def setUp(self):
        self.data = _search_fixture()
        self.filter = self.app.filter_unit_hosts

    def names(self, query, unit="Matriz"):
        return [item["name"] for _sector, item in self.filter(self.data, unit, query)]

    def test_matches_the_host_name(self):
        self.assertEqual(self.names("recep"), ["PC-RECEP-01", "PC-RECEP-02"])

    def test_matches_the_ip(self):
        self.assertEqual(self.names("192.0.2.41"), ["PC-FIN-01"])

    def test_matching_is_case_insensitive(self):
        self.assertEqual(self.names("pc-fin"), ["PC-FIN-01"])
        self.assertEqual(self.names("PC-FIN"), ["PC-FIN-01"])

    def test_search_is_scoped_to_the_selected_unit(self):
        # PC-RECEP-99 lives in Filial and must not leak into a Matriz search.
        self.assertNotIn("PC-RECEP-99", self.names("recep"))
        self.assertEqual(self.names("recep", unit="Filial"), ["PC-RECEP-99"])

    def test_results_carry_their_own_sector(self):
        # This pairing is what keeps RealVNC opening the right profile.
        results = self.filter(self.data, "Matriz", "pc-")
        self.assertEqual(
            [(sector, item["name"]) for sector, item in results],
            [
                ("Recepção", "PC-RECEP-01"),
                ("Recepção", "PC-RECEP-02"),
                ("Financeiro", "PC-FIN-01"),
            ],
        )

    def test_query_cannot_straddle_name_and_host(self):
        # "01 192" only matches if the two fields are joined before matching.
        self.assertEqual(self.names("01 192"), [])

    def test_empty_query_returns_nothing(self):
        self.assertEqual(self.filter(self.data, "Matriz", ""), [])
        self.assertEqual(self.filter(self.data, "Matriz", "   "), [])
        self.assertEqual(self.filter(self.data, "Matriz", None), [])

    def test_unknown_unit_returns_nothing(self):
        self.assertEqual(self.filter(self.data, "Inexistente", "pc"), [])

    def test_order_is_stable_across_identical_searches(self):
        self.assertEqual(self.names("pc-"), self.names("pc-"))

    def test_malformed_entries_are_skipped(self):
        data = _search_fixture()
        data["units"][0]["sectors"][0]["hosts"].append("nao e um dict")
        data["units"][0]["sectors"].append("nao e um setor")
        self.assertEqual(
            [item["name"] for _s, item in self.filter(data, "Matriz", "pc-")],
            ["PC-RECEP-01", "PC-RECEP-02", "PC-FIN-01"],
        )


class TestSearchActionSector(VncMenuTestCase):
    def test_run_host_action_accepts_an_explicit_sector(self):
        # Without this parameter a RealVNC result found outside the selected
        # sector would open <SetorSelecionado>_<Nome>.vnc, the wrong profile.
        import inspect

        signature = inspect.signature(self.app.App.run_host_action)
        self.assertIn("sector", signature.parameters)
        self.assertIsNone(signature.parameters["sector"].default)


# ------------------------------------------------------------- changelog


class TestChangelogWindow(VncMenuTestCase):
    def test_window_exists_and_is_wired_to_the_about_button(self):
        janela = getattr(self.app, "ChangelogWindow", None)
        self.assertIsNotNone(janela, "ChangelogWindow sumiu de ui/windows.py")
        for metodo in ("load_async", "show_release", "show_error_state", "set_notes"):
            self.assertTrue(hasattr(janela, metodo), f"faltou {metodo}")
        self.assertTrue(hasattr(self.app.AboutWindow, "open_changelog"))

    def test_notes_formatter_supplies_its_own_empty_body_message(self):
        # A janela NAO trata corpo vazio: quem trata e o formatador. Se este
        # comportamento mudar, a caixa passaria a abrir em branco.
        for vazio in ("", None, "   ", "\n\n"):
            with self.subTest(corpo=vazio):
                texto = self.app.format_release_notes_for_display(vazio).strip()
                self.assertTrue(texto, "o formatador devolveu texto vazio")
                self.assertIn("Nenhuma nota", texto)

    def test_changelog_takes_over_the_modal_grab_from_about(self):
        # O Sobre e modal. Sem essa troca de grab a janela do changelog abre
        # atras dele e nao recebe clique nenhum.
        import inspect

        assinatura = inspect.signature(self.app.ChangelogWindow.__init__)
        self.assertIn("on_close", assinatura.parameters)
        self.assertIsNone(assinatura.parameters["on_close"].default)
        self.assertTrue(hasattr(self.app.AboutWindow, "retake_grab"))
        # destroy sobrescrito e o que devolve o grab tambem quando fecha no X
        self.assertIn("destroy", vars(self.app.ChangelogWindow))

    def test_notes_formatter_strips_the_leading_version_heading(self):
        # A janela ja mostra a versao no topo, entao repetir o titulo dentro da
        # caixa seria redundante.
        texto = self.app.format_release_notes_for_display(
            "## VNC-Menu v2.2.0\n\n### Novidades\n\n- Item de teste\n"
        )
        self.assertNotIn("VNC-Menu v2.2.0", texto)
        self.assertIn("Item de teste", texto)


class TestCredentialsMerge(VncMenuTestCase):
    """creds.json e gravado por mesclagem, nao por substituicao.

    Hoje so ha a credencial do UltraVNC, mas o arquivo continua sendo mesclado
    de proposito: reescrever o dict inteiro faria um gravador apagar qualquer
    outra chave guardada ali, e o usuario so descobriria ao precisar dela.

    DPAPI so existe no Windows, entao aqui o par encrypt/decrypt vira um
    reversivel simples. O que se testa e a MESCLAGEM, nao a criptografia.
    """

    def mesclagem_testavel(self):
        return (
            vncmenu_loader.patched_global(self.app, "dpapi_encrypt", lambda v: f"enc:{v}"),
            vncmenu_loader.patched_global(
                self.app, "dpapi_decrypt", lambda v: str(v)[4:] if str(v).startswith("enc:") else ""
            ),
        )

    def test_saving_does_not_erase_other_keys_in_the_file(self):
        cifrar, decifrar = self.mesclagem_testavel()
        with cifrar, decifrar:
            # Chave de outro gravador (ou de uma versao anterior do app).
            self.app._write_creds_file({"chave_de_terceiro": "valor"})
            self.app.save_creds("usuario-vnc", "senha-vnc")

            self.assertEqual(self.app.load_creds(), ("usuario-vnc", "senha-vnc"))
            self.assertEqual(
                self.app._read_creds_file().get("chave_de_terceiro"), "valor")

    def test_rewriting_the_credential_keeps_the_rest(self):
        cifrar, decifrar = self.mesclagem_testavel()
        with cifrar, decifrar:
            self.app._write_creds_file({"chave_de_terceiro": "valor"})
            self.app.save_creds("usuario-vnc", "senha-vnc")
            self.app.save_creds("outro-vnc", "outra-senha")

            self.assertEqual(self.app.load_creds(), ("outro-vnc", "outra-senha"))
            self.assertEqual(
                self.app._read_creds_file().get("chave_de_terceiro"), "valor")

    def test_a_missing_file_reads_as_empty_credentials(self):
        self.assertIsInstance(self.app.load_creds(), tuple)


class TestSingleHostSessionCheck(VncMenuTestCase):
    """Consulta de sessoes de UMA maquina, pelo menu de contexto.

    O botao Usuarios so roda no setor inteiro, entao sem este caminho nao ha
    como ver o motivo real de uma maquina especifica falhar.
    """

    def _pieces(self):
        """Progresso e janela de texto falsos, mais um App de mentira."""

        class FakeProgress:
            def __init__(self, *args, **kwargs):
                self.closed = False

            def winfo_exists(self):
                return True

            def close(self):
                self.closed = True

        registro = {"textos": [], "erros": [], "progressos": []}

        def fake_progress(*args, **kwargs):
            p = FakeProgress()
            registro["progressos"].append(p)
            return p

        def fake_text_window(parent, title, content, **kwargs):
            registro["textos"].append((title, content))

        def fake_error(parent, title, message):
            registro["erros"].append((title, message))

        class FakeApp:
            """Faz o papel do laco do Tk: guarda os callbacks e os executa.

            Conta com semaforo em vez de Event porque uma consulta pode estar
            no ar enquanto outra ja terminou; com Event, drenar() correria
            antes do segundo after() e o teste passaria por acidente.
            """

            def __init__(self):
                self.pendentes = []
                self._lock = threading.Lock()
                self._chegou = threading.Semaphore(0)

            def after(self, _ms, fn):
                with self._lock:
                    self.pendentes.append(fn)
                self._chegou.release()

            def drenar(self, esperados=1):
                for _ in range(esperados):
                    assert self._chegou.acquire(timeout=10), "o worker nunca chamou after()"
                while True:
                    with self._lock:
                        if not self.pendentes:
                            return
                        proximo = self.pendentes.pop(0)
                    proximo()

        return FakeApp(), registro, fake_progress, fake_text_window, fake_error

    def _run(self, consulta, host="10.104.111.6", nome="ANALISTA-01", app=None):
        fake, registro, fake_progress, fake_text, fake_error = self._pieces()
        if app is not None:
            fake = app
        with vncmenu_loader.patched_global(self.app, "query_logged_users_raw", consulta), \
             vncmenu_loader.patched_global(self.app, "QwinstaProgressWindow", fake_progress), \
             vncmenu_loader.patched_global(self.app, "show_text_window", fake_text), \
             vncmenu_loader.patched_global(self.app, "show_error", fake_error):
            self.app.App.show_host_sessions(fake, host, nome)
            fake.drenar()
        return fake, registro

    def test_the_raw_qwinsta_text_reaches_the_user(self):
        # O ponto da tela: "ERRO: Acesso negado" e o que permite agir, e a
        # a lista de setor nunca teria espaco para isso.
        _fake, registro = self._run(
            lambda alvos: [(alvos[0]["name"], "ERRO: Acesso negado (5)")]
        )
        self.assertEqual(len(registro["textos"]), 1)
        titulo, conteudo = registro["textos"][0]
        self.assertIn("ANALISTA-01", titulo)
        self.assertIn("ERRO: Acesso negado (5)", conteudo)
        self.assertEqual(registro["erros"], [])

    def test_the_host_actually_queried_is_the_one_that_was_clicked(self):
        vistos = []

        def consulta(alvos):
            vistos.append(list(alvos))
            return [(alvos[0]["name"], "VAZIO")]

        self._run(consulta, host="\\\\10.104.111.6  ", nome="ANALISTA-01")
        self.assertEqual(vistos, [[{"name": "ANALISTA-01", "host": "10.104.111.6"}]])

    def test_a_host_without_a_name_still_gets_a_usable_title(self):
        _fake, registro = self._run(
            lambda alvos: [(alvos[0]["name"], "VAZIO")],
            nome="",
        )
        titulo, _conteudo = registro["textos"][0]
        self.assertIn("10.104.111.6", titulo)

    def test_a_failure_is_shown_instead_of_an_empty_report(self):
        def explode(_alvos):
            raise OSError("qwinsta nao encontrado")

        _fake, registro = self._run(explode)
        self.assertEqual(registro["textos"], [])
        self.assertEqual(len(registro["erros"]), 1)
        self.assertIn("qwinsta nao encontrado", registro["erros"][0][1])

    def test_the_progress_window_closes_on_both_paths(self):
        _fake, ok = self._run(lambda alvos: [(alvos[0]["name"], "VAZIO")])
        self.assertTrue(all(p.closed for p in ok["progressos"]))

        def explode(_alvos):
            raise OSError("falhou")

        _fake, ruim = self._run(explode)
        self.assertTrue(all(p.closed for p in ruim["progressos"]))

    def test_two_clicks_on_the_same_host_do_not_open_two_windows(self):
        # Sem a trava, o segundo clique abre uma segunda janela de progresso e
        # uma segunda de resultado, e a de cima esconde a de baixo.
        liberar = threading.Event()

        def consulta(alvos):
            liberar.wait(10)
            return [(alvos[0]["name"], "VAZIO")]

        fake, registro, fake_progress, fake_text, fake_error = self._pieces()
        with vncmenu_loader.patched_global(self.app, "query_logged_users_raw", consulta), \
             vncmenu_loader.patched_global(self.app, "QwinstaProgressWindow", fake_progress), \
             vncmenu_loader.patched_global(self.app, "show_text_window", fake_text), \
             vncmenu_loader.patched_global(self.app, "show_error", fake_error):
            self.app.App.show_host_sessions(fake, "10.104.111.6", "ANALISTA-01")
            self.app.App.show_host_sessions(fake, "10.104.111.6", "ANALISTA-01")
            self.assertEqual(len(registro["progressos"]), 1)
            liberar.set()
            fake.drenar(1)

        self.assertEqual(len(registro["textos"]), 1)

        # E, terminada a consulta, o host volta a poder ser consultado.
        with vncmenu_loader.patched_global(self.app, "query_logged_users_raw",
                                           lambda alvos: [(alvos[0]["name"], "VAZIO")]), \
             vncmenu_loader.patched_global(self.app, "QwinstaProgressWindow", fake_progress), \
             vncmenu_loader.patched_global(self.app, "show_text_window", fake_text), \
             vncmenu_loader.patched_global(self.app, "show_error", fake_error):
            self.app.App.show_host_sessions(fake, "10.104.111.6", "ANALISTA-01")
            fake.drenar(1)
        self.assertEqual(len(registro["textos"]), 2)

    def test_another_host_is_not_blocked_by_the_first(self):
        liberar = threading.Event()

        def consulta(alvos):
            liberar.wait(10)
            return [(alvos[0]["name"], "VAZIO")]

        fake, registro, fake_progress, fake_text, fake_error = self._pieces()
        with vncmenu_loader.patched_global(self.app, "query_logged_users_raw", consulta), \
             vncmenu_loader.patched_global(self.app, "QwinstaProgressWindow", fake_progress), \
             vncmenu_loader.patched_global(self.app, "show_text_window", fake_text), \
             vncmenu_loader.patched_global(self.app, "show_error", fake_error):
            self.app.App.show_host_sessions(fake, "10.104.111.6", "ANALISTA-01")
            self.app.App.show_host_sessions(fake, "10.104.111.7", "ANALISTA-02")
            self.assertEqual(len(registro["progressos"]), 2)
            liberar.set()
            fake.drenar(2)
        self.assertEqual(len(registro["textos"]), 2)

    def test_an_empty_host_does_nothing_at_all(self):
        fake, registro, fake_progress, fake_text, fake_error = self._pieces()
        with vncmenu_loader.patched_global(self.app, "QwinstaProgressWindow", fake_progress), \
             vncmenu_loader.patched_global(self.app, "show_text_window", fake_text):
            self.app.App.show_host_sessions(fake, "   ", "Sem host")
        self.assertEqual(registro["progressos"], [])
        self.assertEqual(registro["textos"], [])

    def test_the_context_menu_offers_it(self):
        # Sem a entrada no menu o metodo existe e ninguem alcanca.
        import ast

        origem = (vncmenu_loader.PACKAGE_DIR / "ui" / "app.py").read_text(encoding="utf-8")
        arvore = ast.parse(origem)
        alvo = None
        for node in ast.walk(arvore):
            if isinstance(node, ast.FunctionDef) and node.name == "show_host_context_menu":
                alvo = node
        self.assertIsNotNone(alvo, "show_host_context_menu sumiu")
        rotulos = [
            c.value for c in ast.walk(alvo)
            if isinstance(c, ast.Constant) and isinstance(c.value, str)
        ]
        self.assertIn("Sessões", rotulos)
        chamadas = [
            n.func.attr for n in ast.walk(alvo)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        ]
        self.assertIn("show_host_sessions", chamadas)


class TestModeSystemRemoved(VncMenuTestCase):
    """Conectar/Reiniciar deixaram de ser modos.

    O modo antigo armava um estado global e o clique no host fazia o que o
    modo dissesse. Deixar em Reiniciar e voltar depois reiniciava a máquina
    num clique de conexão. Estes testes fixam o novo contrato: clicar conecta,
    reiniciar é ação por host.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import ast

        cls.origem = (vncmenu_loader.PACKAGE_DIR / "ui" / "app.py").read_text(encoding="utf-8")
        cls.arvore = ast.parse(cls.origem)
        cls.classe = next(
            n for n in ast.walk(cls.arvore)
            if isinstance(n, ast.ClassDef) and n.name == "App"
        )
        cls.metodos = {
            n.name: n for n in cls.classe.body if isinstance(n, ast.FunctionDef)
        }

    def _chamadas(self, metodo):
        import ast

        node = self.metodos.get(metodo)
        self.assertIsNotNone(node, f"App.{metodo} sumiu")
        return {
            n.func.attr for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        } | {
            n.func.id for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }

    def test_the_mode_machinery_is_gone_entirely(self):
        # Não basta esconder os botões: o estado e o alternador têm de sumir,
        # senão o clique no host ainda poderia cair no ramo de reinício.
        # "self.mode." e "self.mode " pegam o StringVar antigo sem esbarrar em
        # self.mode_label, que é a legenda de busca e continua viva.
        for morto in ("def set_mode", "self.mode.", "self.mode ",
                      'value="connect"', 'value="restart"',
                      "self.btn_connect", "self.btn_restart"):
            self.assertNotIn(morto, self.origem, f"resquício do sistema de modos: {morto!r}")

    def test_clicking_a_host_always_connects(self):
        chamadas = self._chamadas("run_host_action")
        self.assertIn("launch_vnc", chamadas)
        # Nunca mais confirmar/reiniciar a partir de um clique de host.
        self.assertNotIn("restart_host_async", chamadas)
        self.assertNotIn("confirm_action", chamadas)

    def test_restart_is_reachable_from_the_host_context_menu(self):
        import ast

        node = self.metodos["show_host_context_menu"]
        rotulos = [
            c.value for c in ast.walk(node)
            if isinstance(c, ast.Constant) and isinstance(c.value, str)
        ]
        self.assertIn("Reiniciar", rotulos)
        self.assertIn("restart_host_from_menu", self._chamadas("show_host_context_menu"))

    def test_the_manual_host_button_opens_the_actions_window(self):
        self.assertIn("HostActionsWindow", self._chamadas("open_manual_host"))
        # E o botão da tela principal chama open_manual_host, senão a janela
        # existe e ninguém a alcança.
        self.assertIn("command=self.open_manual_host", self.origem)

    def test_the_old_custom_host_dialog_is_no_longer_wired(self):
        # ask_custom_connection continua existindo em dialogs.py, mas a tela
        # principal não o usa mais: quem faz host manual agora é a janela.
        self.assertNotIn("ask_custom_connection", self.origem)


class TestManualHostActions(VncMenuTestCase):
    """connect_manual_host / restart_manual_host / restart_host_from_menu."""

    def _fake_app(self, auto=True):
        app = types.SimpleNamespace()
        app.automatic_login_enabled = lambda: auto
        app.restart_calls = []
        app.restart_host_async = lambda *a, **k: app.restart_calls.append((a, k))
        return app

    def test_connect_passes_the_host_through_to_the_viewer(self):
        registro = []

        def fake_launch(host, viewer, name=None, sector=None, parent=None, **kw):
            registro.append((host, viewer, kw.get("automatic_login"), kw.get("port")))

        app = self._fake_app(auto=True)
        with vncmenu_loader.patched_global(self.app, "launch_vnc", fake_launch):
            self.app.App.connect_manual_host(app, "10.0.0.5", "realvnc", 5901)
        self.assertEqual(registro, [("10.0.0.5", "realvnc", True, 5901)])

    def test_connect_ignores_an_empty_host(self):
        registro = []
        with vncmenu_loader.patched_global(
            self.app, "launch_vnc", lambda *a, **k: registro.append(a)
        ):
            self.app.App.connect_manual_host(self._fake_app(), "   ")
        self.assertEqual(registro, [])

    def test_connect_strips_leading_backslashes(self):
        registro = []

        def fake_launch(host, *a, **k):
            registro.append(host)

        with vncmenu_loader.patched_global(self.app, "launch_vnc", fake_launch):
            self.app.App.connect_manual_host(self._fake_app(), "\\\\10.0.0.5", "ultravnc", None)
        self.assertEqual(registro, ["10.0.0.5"])

    def test_restart_only_fires_after_a_yes(self):
        app = self._fake_app()
        with vncmenu_loader.patched_global(self.app, "confirm_action", lambda *a, **k: True):
            self.app.App.restart_manual_host(app, "10.0.0.5")
        self.assertEqual(len(app.restart_calls), 1)
        self.assertEqual(app.restart_calls[0][0][0], "10.0.0.5")

    def test_restart_does_nothing_on_a_no(self):
        app = self._fake_app()
        with vncmenu_loader.patched_global(self.app, "confirm_action", lambda *a, **k: False):
            self.app.App.restart_manual_host(app, "10.0.0.5")
        self.assertEqual(app.restart_calls, [])

    def test_restart_ignores_an_empty_host_without_even_asking(self):
        app = self._fake_app()
        pediu = []
        with vncmenu_loader.patched_global(
            self.app, "confirm_action", lambda *a, **k: pediu.append(True) or True
        ):
            self.app.App.restart_manual_host(app, "   ")
        self.assertEqual(app.restart_calls, [])
        self.assertEqual(pediu, [], "não deveria nem perguntar sem host")

    def test_context_menu_restart_keeps_the_display_name(self):
        app = self._fake_app()
        with vncmenu_loader.patched_global(self.app, "confirm_action", lambda *a, **k: True):
            self.app.App.restart_host_from_menu(app, "10.0.0.5", "ANALISTA-01")
        self.assertEqual(app.restart_calls[0][0], ("10.0.0.5", "ANALISTA-01"))

    def test_the_window_splits_host_and_port_before_acting(self):
        # O campo aceita host::porta; a janela tem de separar antes de mandar.
        janela = types.SimpleNamespace()
        janela.current_host = lambda: "10.0.0.5::5901"
        janela.viewer_var = types.SimpleNamespace(get=lambda: "ultravnc")
        capturado = []
        janela.parent = types.SimpleNamespace(
            connect_manual_host=lambda host, viewer, port: capturado.append((host, viewer, port))
        )
        self.app.HostActionsWindow.do_connect(janela)
        self.assertEqual(capturado, [("10.0.0.5", "ultravnc", 5901)])

    def test_the_window_offers_every_action(self):
        for metodo in ("do_connect", "do_restart", "do_sessions", "do_printers",
                       "update_buttons_state"):
            self.assertTrue(hasattr(self.app.HostActionsWindow, metodo),
                            f"HostActionsWindow.{metodo} sumiu")


# ------------------------------------------- executar script de inicializacao


class TestScriptNameValidation(VncMenuTestCase):
    def test_accepts_a_plain_file_name(self):
        self.assertEqual(self.app.validate_script_name("  IMPRESSORAS.vbs  "),
                         "IMPRESSORAS.vbs")

    def test_strips_surrounding_quotes(self):
        self.assertEqual(self.app.validate_script_name('"IMPRESSORAS.vbs"'),
                         "IMPRESSORAS.vbs")

    def test_rejects_an_empty_name(self):
        with self.assertRaises(ValueError):
            self.app.validate_script_name("   ")

    def test_rejects_anything_that_carries_a_path(self):
        # O campo e um nome; aceitar caminho viraria execucao remota de
        # qualquer arquivo da maquina a partir de uma caixa de texto.
        for nome in (r"..\..\Windows\System32\algo.vbs",
                     r"C:\Windows\Temp\algo.vbs",
                     "sub/algo.vbs",
                     r"\\servidor\share\algo.vbs"):
            with self.assertRaises(ValueError, msg=nome):
                self.app.validate_script_name(nome)

    def test_rejects_extensions_that_are_not_scripts(self):
        for nome in ("IMPRESSORAS.exe", "IMPRESSORAS", "config.ini"):
            with self.assertRaises(ValueError, msg=nome):
                self.app.validate_script_name(nome)

    def test_accepts_the_three_script_extensions_in_any_case(self):
        for nome in ("a.vbs", "a.VBS", "a.cmd", "a.Bat"):
            self.assertEqual(self.app.validate_script_name(nome), nome)


class TestRunScriptPayload(VncMenuTestCase):
    def _payload(self, nome="IMPRESSORAS.vbs"):
        return self.app._build_run_script_payload(nome)

    def test_runs_through_a_scheduled_task_with_the_interactive_token(self):
        # E o unico jeito sem senha de usar a sessao do usuario logado.
        # AddWindowsPrinterConnection grava no HKCU de quem chama, entao
        # rodar direto como SYSTEM mapearia no perfil errado.
        payload = self._payload()
        self.assertIn("New-ScheduledTaskPrincipal", payload)
        self.assertIn("-LogonType Interactive", payload)

    def test_never_runs_the_script_directly_as_system(self):
        payload = self._payload()
        # O host do script so pode aparecer como acao da tarefa, nunca solto.
        self.assertIn("New-ScheduledTaskAction -Execute 'wscript.exe'", payload)
        self.assertEqual(payload.count("wscript.exe"), 1)

    def test_a_vbs_runs_with_no_window_on_the_user_screen(self):
        # cscript abria console na tela do usuario; fechar aquela janela
        # matava o script, possivelmente com as impressoras ja apagadas.
        payload = self._payload()
        self.assertNotIn("cscript.exe", payload)
        self.assertIn("//B", payload)
        self.assertTrue(self.app.script_runs_hidden("IMPRESSORAS.vbs"))

    def test_the_task_still_runs_on_battery(self):
        # Padrao do New-ScheduledTaskSettingsSet e NAO iniciar na bateria: num
        # notebook a tarefa era criada, disparada e nunca rodava.
        self.assertIn("-AllowStartIfOnBatteries", self._payload())
        self.assertIn("-DontStopIfGoingOnBatteries", self._payload())

    def test_windows_kills_a_stuck_task_by_itself(self):
        # O app remove a tarefa e vai embora; sem limite proprio, um script
        # travado ficaria rodando na maquina do usuario para sempre.
        self.assertIn("-ExecutionTimeLimit", self._payload())

    def test_stops_before_creating_the_task_when_nobody_is_logged_on(self):
        payload = self._payload()
        self.assertIn("Send 'no_user' ''", payload)
        antes = payload.index("Send 'no_user' ''")
        depois = payload.index("Register-ScheduledTask")
        self.assertLess(antes, depois, "a guarda tem de vir antes de registrar")

    def test_always_removes_the_temporary_task(self):
        payload = self._payload()
        # Uma antes (sobra de execucao anterior), uma no start_failed, uma no
        # fim. Sem isso a maquina acumula tarefas orfas.
        self.assertGreaterEqual(payload.count("Unregister-ScheduledTask"), 3)

    def test_the_file_name_is_quoted_as_a_powershell_literal(self):
        payload = self._payload("nome'esquisito.vbs")
        self.assertIn("$name='nome''esquisito.vbs'", payload)

    def test_lists_the_folder_so_a_wrong_name_shows_the_real_ones(self):
        payload = self._payload()
        self.assertIn("$o.Available", payload)
        self.assertIn("Send 'no_script' ''", payload)


class TestRunScriptParsing(VncMenuTestCase):
    def _wrap(self, data):
        import base64 as b64
        import json as js
        blob = b64.b64encode(js.dumps(data).encode("utf-8")).decode("ascii")
        return f"ruido\n__VNC_MENU_RUNVBS_BEGIN__{blob}__VNC_MENU_RUNVBS_END__\nmais ruido"

    def test_reads_the_marked_payload(self):
        data = self.app.parse_run_script_payload(
            self._wrap({"Status": "ok", "User": "DOM\\fulano"})
        )
        self.assertEqual(data["Status"], "ok")
        self.assertEqual(data["User"], "DOM\\fulano")

    def test_missing_or_corrupt_payload_is_empty(self):
        self.assertEqual(self.app.parse_run_script_payload(""), {})
        self.assertEqual(self.app.parse_run_script_payload("sem marcador"), {})
        self.assertEqual(
            self.app.parse_run_script_payload(
                "__VNC_MENU_RUNVBS_BEGIN__QQQ==__VNC_MENU_RUNVBS_END__"
            ),
            {},
        )

    def test_a_json_list_is_not_accepted_as_a_result(self):
        self.assertEqual(self.app.parse_run_script_payload(self._wrap([1, 2])), {})


class TestRunScriptReport(VncMenuTestCase):
    def test_success_says_the_exit_code_does_not_prove_anything(self):
        # O script da empresa nunca desliga o ON ERROR RESUME NEXT, entao ele
        # sai 0 mesmo falhando. O relatorio nao pode dar a entender sucesso.
        texto = self.app.format_script_run_report(
            "PC-01", {"Status": "ok", "User": "DOM\\fulano", "LastResult": 0}
        )
        self.assertIn("Impressoras", texto)
        self.assertIn("não informa sucesso", texto)

    def test_missing_script_lists_what_is_in_the_folder(self):
        texto = self.app.format_script_run_report(
            "PC-01",
            {"Status": "no_script", "Available": ["IMPRESSORA.vbs", "outro.vbs"]},
        )
        self.assertIn("IMPRESSORA.vbs", texto)
        self.assertIn("outro.vbs", texto)

    def test_empty_folder_says_so_instead_of_listing_nothing(self):
        texto = self.app.format_script_run_report(
            "PC-01", {"Status": "no_script", "Available": []}
        )
        self.assertIn("vazia", texto)

    def test_no_user_explains_why_nothing_ran(self):
        texto = self.app.format_script_run_report("PC-01", {"Status": "no_user"})
        self.assertIn("Nenhum usuário logado", texto)
        self.assertIn("SYSTEM", texto)

    def test_windows_message_is_shown_when_the_task_could_not_be_created(self):
        texto = self.app.format_script_run_report(
            "PC-01", {"Status": "register_failed", "Detail": "Acesso negado"}
        )
        self.assertIn("Acesso negado", texto)

    def test_an_unknown_status_is_not_reported_as_success(self):
        texto = self.app.format_script_run_report("PC-01", {"Status": "vaitesaber"})
        self.assertIn("não reconhecido", texto)
        self.assertNotIn("não informa sucesso", texto)

    def test_every_status_the_script_can_send_has_a_message(self):
        payload = self.app._build_run_script_payload("a.vbs")
        import re as _re
        enviados = set(_re.findall(r"Send '([a-z_]+)'", payload))
        self.assertTrue(enviados)
        faltando = enviados - set(self.app.SCRIPT_RUN_STATUS)
        self.assertEqual(faltando, set(), f"status sem texto: {faltando}")


class TestPrintersWindowWiring(VncMenuTestCase):
    def test_the_window_offers_every_action(self):
        for metodo in ("open_folder", "do_query", "do_run"):
            self.assertTrue(hasattr(self.app.PrintersWindow, metodo),
                            f"PrintersWindow.{metodo} sumiu")

    def test_opening_the_folder_reuses_the_host_menu_path(self):
        # Um caminho so para a pasta: se o menu de contexto e a janela
        # montassem o UNC cada um do seu jeito, um dia divergiriam.
        abertos = []
        janela = types.SimpleNamespace(
            _host=lambda: "PC-01",
            parent=types.SimpleNamespace(
                open_host_startup_folder=lambda host: abertos.append(host)
            ),
        )
        self.app.PrintersWindow.open_folder(janela)
        self.assertEqual(abertos, ["PC-01"])

    def test_opening_the_folder_without_a_host_warns_instead_of_opening(self):
        abertos = []
        avisos = []
        janela = types.SimpleNamespace(
            _host=lambda: "",
            host_entry=types.SimpleNamespace(focus_set=lambda: None),
            parent=types.SimpleNamespace(
                open_host_startup_folder=lambda host: abertos.append(host)
            ),
        )
        with vncmenu_loader.patched_global(
            self.app, "show_warning", lambda *a, **k: avisos.append(a)
        ):
            self.app.PrintersWindow.open_folder(janela)
        self.assertEqual(abertos, [])
        self.assertEqual(len(avisos), 1)

    def test_the_app_can_open_the_window_and_reuses_the_open_one(self):
        # Sem guardar a referencia, o coletor pode destruir a janela com a
        # thread trabalhadora ainda rodando.
        criadas = []

        class Fake:
            def __init__(self, parent, host="", display_name=""):
                criadas.append((host, display_name))
                self.parent = parent

            def winfo_exists(self):
                return True

            def lift(self):
                pass

            def focus(self):
                pass

        app = types.SimpleNamespace(_printers_window=None)
        with vncmenu_loader.patched_global(self.app, "PrintersWindow", Fake):
            primeira = self.app.App.open_printers_window(app, "PC-01", "RECEPCAO")
            segunda = self.app.App.open_printers_window(app, "PC-02", "OUTRO")
        self.assertEqual(criadas, [("PC-01", "RECEPCAO")])
        self.assertIs(primeira, segunda)
        self.assertIs(app._printers_window, primeira)


# ------------------------------------------------- instalacao de drivers


class TestPrinterPathParsing(VncMenuTestCase):
    def test_reads_the_paths_the_company_script_maps(self):
        vbs = (
            'strPrinterPath = "\\\\SRV1315\\HSLN_FATURAMENTO_CENTRAL"\n'
            'WshNetwork.AddWindowsPrinterConnection strPrinterPath\n'
            'strPrinterPath = "\\\\SRV1315\\HSLN_FAT01"\n'
            'WshNetwork.SetDefaultPrinter "\\\\SRV1315\\HSLN_FATURAMENTO_CENTRAL"\n'
        )
        self.assertEqual(
            self.app.parse_printer_paths(vbs),
            ["\\\\SRV1315\\HSLN_FATURAMENTO_CENTRAL", "\\\\SRV1315\\HSLN_FAT01"],
        )

    def test_keeps_the_order_of_the_script(self):
        vbs = '"\\\\S\\B"\n"\\\\S\\A"\n'
        self.assertEqual(self.app.parse_printer_paths(vbs), ["\\\\S\\B", "\\\\S\\A"])

    def test_ignores_strings_that_are_not_a_queue(self):
        # "." e o strComputer do WMI; \\SRV sozinho nao tem fila para instalar.
        vbs = 'strComputer = "."\nx = "\\\\SRV1315"\ny = "winmgmts:"\n'
        self.assertEqual(self.app.parse_printer_paths(vbs), [])

    def test_empty_or_broken_input_is_an_empty_list(self):
        for entrada in ("", None, 12345):
            self.assertEqual(self.app.parse_printer_paths(entrada), [])
class TestDriverInstallReport(VncMenuTestCase):
    def test_lists_each_queue_with_its_error(self):
        texto = self.app.format_driver_install_report("PC-01", {
            "Status": "ok",
            "Results": [
                {"Path": "\\\\SRV1315\\FILA_A", "Ok": True, "Error": ""},
                {"Path": "\\\\SRV1315\\FILA_B", "Ok": False, "Error": "Acesso negado"},
            ],
        })
        self.assertIn("OK    \\\\SRV1315\\FILA_A", texto)
        self.assertIn("FALHA \\\\SRV1315\\FILA_B", texto)
        self.assertIn("Acesso negado", texto)

    def test_failures_are_reported_even_when_the_phase_says_ok(self):
        # "ok" e o script ter rodado ate o fim, nao toda fila ter instalado.
        data = {"Status": "ok", "Results": [
            {"Path": "\\\\S\\A", "Ok": False, "Error": "erro"}]}
        self.assertEqual(self.app.driver_install_failures(data), [("\\\\S\\A", "erro")])
        self.assertIn("falharam", self.app.format_driver_install_report("PC", data))

    def test_a_clean_run_does_not_invent_failures(self):
        data = {"Status": "ok", "Results": [{"Path": "\\\\S\\A", "Ok": True}]}
        self.assertEqual(self.app.driver_install_failures(data), [])
        self.assertNotIn("falharam", self.app.format_driver_install_report("PC", data))

    def test_a_script_with_no_queues_explains_why(self):
        texto = self.app.format_driver_install_report("PC", {"Status": "no_queues"})
        self.assertIn("Nenhum caminho", texto)
        self.assertIn("variável", texto)

    def test_an_unknown_status_is_not_reported_as_success(self):
        texto = self.app.format_driver_install_report("PC", {"Status": "vaitesaber"})
        self.assertIn("não reconhecido", texto)

    def test_every_status_the_payload_can_send_has_a_message(self):
        import re as _re
        payload = self.app._build_driver_install_payload("a.vbs")
        enviados = set(_re.findall(r"Send '([a-z_]+)'", payload))
        self.assertTrue(enviados)
        self.assertEqual(enviados - set(self.app.DRIVER_INSTALL_STATUS), set())
class TestScriptHostChoice(VncMenuTestCase):
    def test_vbs_uses_the_windowless_host(self):
        self.assertEqual(self.app.script_host_command("A.VBS"),
                         ("wscript.exe", "//nologo //B"))

    def test_batch_files_use_cmd_and_are_not_hidden(self):
        for nome in ("x.cmd", "x.bat"):
            self.assertEqual(self.app.script_host_command(nome)[0], "cmd.exe")
            self.assertFalse(self.app.script_runs_hidden(nome), nome)

    def test_an_unsupported_extension_raises(self):
        with self.assertRaises(ValueError):
            self.app.script_host_command("x.exe")

    def test_the_accepted_extensions_are_exactly_the_ones_with_a_host(self):
        # Aceitar no campo uma extensao sem host definido daria erro so na
        # hora de montar a tarefa, no meio do atendimento.
        for extensao in self.app.SCRIPT_HOSTS:
            self.assertEqual(self.app.validate_script_name("a" + extensao),
                             "a" + extensao)
        with self.assertRaises(ValueError):
            self.app.validate_script_name("a.ps1")

class TestDriverInstallRunsAsSystem(VncMenuTestCase):
    def _command(self):
        capturado = {}

        def fake_run(command, host, psexec_path, timeout):
            capturado["command"] = list(command)
            raise self.app.PsExecQueryError("parou aqui", "hint")

        with vncmenu_loader.patched_global(self.app, "_run_psexec", fake_run):
            with self.assertRaises(self.app.PsExecQueryError):
                self.app.install_printer_drivers(
                    "10.0.0.5", "IMPRESSORAS.vbs", "psexec.exe")
        return capturado["command"]

    def test_it_runs_as_system_and_never_sends_a_password(self):
        # -u/-p foi tentado em producao e nao serve: o PsExec faz logon
        # interativo no alvo e a conta nao tem esse direito nas estacoes
        # (1385). SYSTEM nao faz logon nenhum e o servidor de impressao
        # libera o driver para a conta de maquina.
        command = self._command()
        self.assertIn("-s", command)
        self.assertNotIn("-u", command)
        self.assertNotIn("-p", command)

    def test_the_elevated_token_is_still_requested(self):
        # Escrever no driver store precisa do token elevado.
        self.assertIn("-h", self._command())

    def test_install_takes_no_credential_argument(self):
        import inspect
        parametros = list(
            inspect.signature(self.app.install_printer_drivers).parameters)
        self.assertEqual(parametros, ["host", "script_name", "psexec_path"])

    def test_the_account_never_appears_in_the_technical_details(self):
        # Sem -u nao ha conta a reportar; a linha existia so para aquele caso.
        detalhes = self.app._build_psexec_details("10.0.0.5", "psexec.exe", 2)
        self.assertNotIn("Conta:", detalhes)


class TestDriverInstallIsNotOptional(VncMenuTestCase):
    def _source(self):
        import inspect
        return inspect.getsource(self.app.PrintersWindow.do_run)

    def test_the_window_has_no_driver_checkbox_left(self):
        self.assertFalse(hasattr(self.app.PrintersWindow, "install_drivers"))
        fonte = self._source()
        self.assertNotIn("install_drivers", fonte)

    def test_the_install_is_not_behind_a_condition(self):
        # Era "if com_drivers:". Se voltar a ser condicional, as maquinas que
        # precisam do driver falham de novo e o operador nao tem como saber
        # antes de rodar.
        fonte = self._source()
        self.assertIn("install_printer_drivers(host, script_name, psexec_path)", fonte)
        self.assertNotIn("com_drivers", fonte)

    def test_a_failed_install_still_blocks_the_script(self):
        fonte = self._source()
        self.assertIn('drivers.get("Status") != "ok"', fonte)
        self.assertIn("abortado = True", fonte)
        # O run so acontece depois da guarda.
        self.assertLess(fonte.index("abortado = True"),
                        fonte.index("run_startup_script("))


class TestCredentialTypingCannotLeak(VncMenuTestCase):
    """A credencial nunca pode sair da janela de autenticacao.

    O bug real: com send_keys(), fechar o viewer ou clicar na barra de busca
    enquanto o dialogo abria fazia usuario e senha serem digitados na janela
    que estivesse em primeiro plano. A garantia agora e estrutural, nao uma
    checagem a mais antes de digitar.
    """

    def test_the_module_does_not_import_the_global_keyboard(self):
        # Se send_keys voltar ao modulo, volta o caminho que vaza.
        import inspect
        fonte = inspect.getsource(self.app.__modules__["vncmenu.remote"])
        self.assertNotIn("from pywinauto.keyboard import", fonte)

    def test_the_autofill_never_calls_send_keys(self):
        import ast as _ast, inspect
        arvore = _ast.parse(inspect.getsource(self.app.auto_enter_uvnc_credentials))
        chamadas = {
            n.func.id for n in _ast.walk(arvore)
            if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name)
        }
        self.assertNotIn("send_keys", chamadas)

    def test_the_blind_fallback_is_gone(self):
        # Era o pior caminho: digitava a senha sem controle nenhum amarrado.
        import inspect
        fonte = inspect.getsource(self.app.auto_enter_uvnc_credentials)
        self.assertIn("no_edit_controls", fonte)
        self.assertNotIn("with_spaces", fonte)

    def test_submitting_only_uses_handle_bound_calls(self):
        import ast as _ast, inspect
        arvore = _ast.parse(inspect.getsource(self.app._submit_auth_dialog))
        # Pelo texto nao serve: o docstring cita send_keys para explicar por
        # que ele nao e usado. O que importa e o que a funcao CHAMA.
        nomes = {
            n.func.id for n in _ast.walk(arvore)
            if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name)
        }
        self.assertNotIn("send_keys", nomes)
        metodos = {
            n.func.attr for n in _ast.walk(arvore)
            if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute)
        }
        self.assertIn("click", metodos)
        self.assertIn("post_message", metodos)


class TestCredentialAutofillCancellation(VncMenuTestCase):
    class _Edit:
        def __init__(self, escritos):
            self.escritos = escritos

        def set_text(self, valor):
            self.escritos.append(valor)

    class _Dialog:
        def __init__(self, edits, fecha_apos_achar=False, cancela_ao_esperar=None):
            self._edits = edits
            self._achado = False
            self._fecha_apos_achar = fecha_apos_achar
            self._cancela_ao_esperar = cancela_ao_esperar
            self.enviado = False

        def wait(self, *_a, **_k):
            # O operador fechando o viewer no exato instante entre achar o
            # dialogo e preencher: e a janela em que o bug antigo digitava.
            if self._cancela_ao_esperar is not None:
                self._cancela_ao_esperar.set()
            return self

        def exists(self, *_a, **_k):
            # True na busca (senao o dialogo nem seria achado) e False depois,
            # que e o caso de a janela sumir antes de digitarmos.
            if not self._achado:
                self._achado = True
                return True
            return not self._fecha_apos_achar

        def descendants(self, **_k):
            return self._edits

        def wrapper_object(self):
            return self

        def handle(self):
            return 1

    def _run(self, cancel, dialogo):
        escritos = []
        with vncmenu_loader.patched_global(
            self.app, "load_creds", lambda: ("usuario", "senha")
        ), vncmenu_loader.patched_global(
            self.app, "_auth_dialog_candidates", lambda _pid: [({}, "process")]
        ), vncmenu_loader.patched_global(
            self.app, "Desktop", lambda **_k: types.SimpleNamespace(
                window=lambda **_kk: dialogo)
        ), vncmenu_loader.patched_global(
            self.app, "_submit_auth_dialog",
            lambda d: setattr(d, "enviado", True)
        ):
            ok = self.app.auto_enter_uvnc_credentials(
                timeout=0.5, process_id=123, cancel=cancel)
        return ok, escritos

    def test_a_cancelled_connection_types_nothing(self):
        escritos = []
        dialogo = self._Dialog([self._Edit(escritos), self._Edit(escritos)])
        cancel = threading.Event()
        cancel.set()
        ok, _ = self._run(cancel, dialogo)
        self.assertFalse(ok)
        self.assertEqual(escritos, [])
        self.assertFalse(dialogo.enviado)

    def test_a_dialog_that_closes_after_being_found_types_nothing(self):
        # Achado, depois fechado: sem a checagem de exists() antes de escrever,
        # a senha ia para um dialogo que o operador ja abandonou.
        escritos = []
        dialogo = self._Dialog(
            [self._Edit(escritos), self._Edit(escritos)], fecha_apos_achar=True)
        ok, _ = self._run(threading.Event(), dialogo)
        self.assertFalse(ok)
        self.assertEqual(escritos, [])
        self.assertFalse(dialogo.enviado)

    def test_cancelling_after_the_dialog_is_found_types_nothing(self):
        # O cancelamento chega DEPOIS do match, que e o caso real de fechar a
        # janela do VNC enquanto o dialogo de credenciais ja apareceu.
        escritos = []
        cancel = threading.Event()
        dialogo = self._Dialog(
            [self._Edit(escritos), self._Edit(escritos)], cancela_ao_esperar=cancel)
        ok, _ = self._run(cancel, dialogo)
        self.assertFalse(ok)
        self.assertEqual(escritos, [])
        self.assertFalse(dialogo.enviado)

    def test_no_edit_controls_means_give_up_not_type_blindly(self):
        dialogo = self._Dialog([])
        ok, _ = self._run(threading.Event(), dialogo)
        self.assertFalse(ok)
        self.assertFalse(dialogo.enviado)

    def test_a_normal_run_fills_both_fields_and_submits(self):
        escritos = []
        dialogo = self._Dialog([self._Edit(escritos), self._Edit(escritos)])
        ok, _ = self._run(threading.Event(), dialogo)
        self.assertTrue(ok)
        self.assertEqual(escritos, ["usuario", "senha"])
        self.assertTrue(dialogo.enviado)

    def test_the_starter_hands_back_a_cancel_handle(self):
        import inspect
        assinatura = inspect.signature(self.app.start_uvnc_credential_autofill)
        self.assertIn("process", assinatura.parameters)
        # Sem devolver o Event, quem chama nao tem como cancelar.
        self.assertIn("return cancel",
                      inspect.getsource(self.app.start_uvnc_credential_autofill))

    def test_a_viewer_that_exits_cancels_the_fill(self):
        """O comportamento, nao o texto: viewer fechado para o preenchimento.

        O preenchimento falso espera no Event. Com o vigia, o processo morto
        libera essa espera em milissegundos; sem ele, a espera estoura e a
        credencial continuaria sendo digitada ate o timeout.
        """
        class ViewerMorto:
            pid = 1

            def poll(self):
                return 0

        cancelado = []
        # Esperar so no Event de cancelamento nao basta: ele e acionado pelo
        # vigia, e a thread do preenchimento ainda pode nao ter registrado
        # nada. A espera tem de ser no FIM do preenchimento.
        terminou = threading.Event()

        def falso_preenchimento(process_id=None, cancel=None):
            cancelado.append(bool(cancel is not None and cancel.wait(3)))
            terminou.set()
            return False

        with vncmenu_loader.patched_global(
            self.app, "auto_enter_uvnc_credentials", falso_preenchimento
        ):
            cancel = self.app.start_uvnc_credential_autofill(1, ViewerMorto())
            self.assertTrue(terminou.wait(5), "o preenchimento nao terminou")
            self.assertTrue(cancel.is_set(), "o Event nunca foi acionado")

        self.assertEqual(cancelado, [True],
                         "o preenchimento nao viu o cancelamento a tempo")

    def test_without_a_process_the_fill_still_runs(self):
        # Sem processo nao ha o que vigiar; o preenchimento normal continua.
        chamadas = []
        terminou = threading.Event()

        def falso_preenchimento(process_id=None, cancel=None):
            chamadas.append(process_id)
            terminou.set()
            return False

        with vncmenu_loader.patched_global(
            self.app, "auto_enter_uvnc_credentials", falso_preenchimento
        ):
            self.app.start_uvnc_credential_autofill(7)
            self.assertTrue(terminou.wait(5), "o preenchimento nao rodou")

        self.assertEqual(chamadas, [7])

    def test_the_viewer_launch_passes_the_process_for_cancellation(self):
        import inspect
        fonte = inspect.getsource(self.app.launch_vnc)
        self.assertIn("start_uvnc_credential_autofill(viewer_process.pid, viewer_process)",
                      fonte)


class TestPrintersWindowNeverActsOnItsOwn(VncMenuTestCase):
    def test_opening_the_window_does_not_query(self):
        # Abrir pelo menu de contexto mandava PsExec para a maquina antes de
        # qualquer clique; um menu aberto por engano virava trafego no alvo.
        import ast as _ast, inspect
        import textwrap
        fonte = inspect.getsource(self.app.PrintersWindow.__init__)
        self.assertNotIn("auto_query", fonte)
        arvore = _ast.parse(textwrap.dedent(fonte))
        agendados = [
            n.args[1].attr for n in _ast.walk(arvore)
            if isinstance(n, _ast.Call)
            and isinstance(n.func, _ast.Attribute)
            and n.func.attr == "after"
            and len(n.args) > 1
            and isinstance(n.args[1], _ast.Attribute)
        ]
        self.assertNotIn("do_query", agendados)

    def test_the_window_takes_no_auto_query_argument(self):
        import inspect
        parametros = list(
            inspect.signature(self.app.PrintersWindow.__init__).parameters)
        self.assertEqual(parametros, ["self", "parent", "host", "display_name"])


class TestManualHostActions(VncMenuTestCase):
    def test_copy_ip_is_gone(self):
        # O IP foi digitado ali mesmo; copiar dali nao serve para nada. No
        # menu de contexto continua, que e onde o IP vem da lista.
        self.assertFalse(hasattr(self.app.HostActionsWindow, "do_copy_ip"))

    def test_the_remaining_actions_match_the_context_menu(self):
        for metodo in ("do_connect", "do_restart", "do_sessions", "do_printers",
                       "do_admin_share", "do_startup_folder"):
            self.assertTrue(hasattr(self.app.HostActionsWindow, metodo),
                            f"HostActionsWindow.{metodo} sumiu")


class TestSidebarFitsSectorNames(VncMenuTestCase):
    """A lateral e a largura da janela andam juntas.

    Alargar a lateral sem subir a minima da janela tira o espaco da grade de
    hosts, cujos nomes ja truncam. Estes testes fixam a relacao, que e o que
    se esquece ao mexer em uma das duas.
    """

    def _source(self, metodo):
        import inspect, textwrap
        return textwrap.dedent(inspect.getsource(metodo))

    def _numero(self, fonte, prefixo):
        import re as _re
        achado = _re.search(prefixo + r"\s*=\s*(\d+)", fonte)
        self.assertIsNotNone(achado, f"nao achei {prefixo}")
        return int(achado.group(1))

    def test_the_sidebar_is_wide_enough_for_the_longest_sector(self):
        # Descontando padding do frame (20x2), do botao (8x2), a barra de
        # rolagem (~20) e o respiro do texto (~12), sobra o texto util. Em
        # Segoe UI 13 normal, ~7px por caractere.
        largura = self._numero(
            self._source(self.app.App.build_sidebar), r"CTkFrame\(self, width")
        util = largura - 40 - 16 - 20 - 12
        self.assertGreaterEqual(util // 7, 33,
                                "nao cabe o maior nome de setor da lista real")

    def test_the_minimum_window_grew_with_the_sidebar(self):
        fonte = self._source(self.app.App.__init__)
        import re as _re
        achado = _re.search(r"self\.minsize\((\d+), (\d+)\)", fonte)
        self.assertIsNotNone(achado)
        minima = int(achado.group(1))
        largura = self._numero(
            self._source(self.app.App.build_sidebar), r"CTkFrame\(self, width")
        # Referencia: o 2.5.0 publicado (janela minima 940, lateral 300), que
        # deixava 640px para a grade de hosts. Alargar a lateral sem subir a
        # minima junto tira desses 640. Contra o 2.4.0 (lateral 260) a grade e
        # 80px mais estreita na largura minima, o que foi uma escolha, nao um
        # descuido: o nome de setor comprido valia mais.
        self.assertGreaterEqual(minima - largura, 940 - 300)

    def test_only_the_selected_sector_is_bold(self):
        # Negrito e ~8% mais largo; usa-lo em todos custava caracteres sem
        # marcar nada, porque a selecao e dada pela cor de fundo.
        fonte = self._source(self.app.App.refresh_sectors)
        self.assertIn("FONT_BOLD if selected else FONT_NORMAL", fonte)


class TestSidebarWidthIsActuallyApplied(VncMenuTestCase):
    """A largura declarada da lateral precisa chegar na tela.

    Bug real: a barra era criada com width=, mas segurada com
    grid_propagate(False) enquanto todos os filhos usam pack(). Como
    grid_propagate so vale para filhos geridos por grid, ele nao segurava
    nada: os filhos ditavam a largura e o width= era ignorado. Tres ajustes
    seguidos de largura (260, 300, 340) nao mudaram um pixel.
    """

    def _source(self):
        import inspect, textwrap
        return textwrap.dedent(inspect.getsource(self.app.App.build_sidebar))

    def test_the_frame_is_held_by_pack_propagate(self):
        fonte = self._source()
        self.assertIn("self.sidebar.pack_propagate(False)", fonte)
        self.assertNotIn("self.sidebar.grid_propagate(", fonte)

    def test_every_child_of_the_sidebar_is_packed(self):
        # A escolha entre pack_propagate e grid_propagate depende disto. Se um
        # filho passar a usar grid, a trava tem de mudar junto.
        fonte = self._source()
        # self.sidebar.grid(...) e a propria barra se colocando na raiz, nao
        # um filho; o que importa e como os FILHOS sao geridos.
        filhos = [
            linha for linha in fonte.splitlines()
            if ".grid(" in linha and "self.sidebar.grid(" not in linha
        ]
        self.assertEqual(filhos, [],
                         "algum filho da lateral passou a usar grid")
        self.assertIn(".pack(", fonte)
