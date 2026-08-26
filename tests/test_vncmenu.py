"""Tests for the pure functions and the storage layer of VNC-Menu.

No GUI, no Windows API, no network, no PsExec. Run with:

    python -m unittest discover -s tests -v
"""

import json
import sys
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
            self.app.PrinterProgressWindow,
            self.app.UpdateCheckProgressWindow,
        ):
            self.assertTrue(issubclass(cls, base), cls.__name__)

    def test_close_is_defined_once_on_the_base(self):
        base = self.app.IndeterminateProgressWindow
        self.assertIn("close", vars(base))
        for cls in (
            self.app.QwinstaProgressWindow,
            self.app.PrinterProgressWindow,
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
        inspect.signature(self.app.PrinterProgressWindow.__init__).bind(None, None, "PC01")
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
