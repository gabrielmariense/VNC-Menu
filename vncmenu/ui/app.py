"""Janela principal e main().

A classe App monta a barra lateral, a grade de hosts e as acoes.
main() chama bootstrap_directories() antes de criar a janela.
"""

import customtkinter as ctk
import ctypes
import json
import os
import shutil
import ssl
import subprocess
import threading
import tkinter as tk
import urllib.error
import urllib.request
import zipfile

from ..config import APP_AUTHOR, APP_NAME, APP_VERSION, COLOR_SCHEME_BLUE, DEFAULT_VIEWER, ERROR_LOG, HOSTS_SOURCE_CUSTOM, HOSTS_SOURCE_SHARED, LOGIN_MODE_AUTO, LOGIN_MODE_MANUAL, SCRIPT_DIR, SEARCH_DEBOUNCE_MS, SEARCH_HOST_COLUMN_WIDTH, SEARCH_SECTOR_COLUMN_WIDTH, UPDATE_DOWNLOAD_DIR, UPDATE_RESULT_JSON
from ..applog import audit_log, log_exception
from ..storage import format_host_port, sanitize_port, bootstrap_directories, filter_unit_hosts, find_psexec, get_host_columns, get_hosts_path_for_source, get_sector_hosts, get_sector_names, get_unit_names, hosts_source_display_name, load_global_paths, load_hosts_data, load_settings, normalize_hosts_source, normalize_login_mode, save_settings, set_hosts_source
from ..theme import FONT_BOLD, FONT_NORMAL, FONT_SMALL, FONT_SMALL_BOLD, FONT_TITLE, THEME, apply_color_theme, normalize_color_scheme
from ..helpers import bind_clickable_row, get_geometry_size, get_window_geometries, is_valid_geometry, prune_window_geometries, reset_scrollable_frame_position, restore_window_geometry, safe_filename, save_window_geometry, show_error, show_info, show_warning
from ..updates import HTTPS_CONTEXT, calculate_sha256, current_main_entry_name, fetch_latest_release, find_release_zip_asset, get_release_asset_checksum, get_updater_launch_command, normalize_release_version, parse_version
from .dialogs import ask_text, choose_hosts_source_dialog, confirm_action, ensure_hosts_source_selected, shared_hosts_edit_warning, show_psexec_required_dialog
from ..remote import PsExecQueryError, format_users_output, host_responds_to_ping, launch_vnc, log_psexec_failure, query_all_logged_users, query_logged_users_raw, query_remote_printers, restart_host
from .windows import AboutWindow, CredsWindow, HostActionsWindow, OcsConfigWindow, OcsSearchWindow, HostUnitsConfigWindow, PrinterProgressWindow, PsExecPathWindow, QwinstaProgressWindow, SettingsWindow, UpdateAvailableWindow, UpdateCheckProgressWindow, UpdateDownloadWindow, ViewerPathsWindow, show_psexec_error_dialog, show_text_window

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("VNC-Menu")
        # 940 e nao 900: a linha de acoes tem 5 botoes (582px) e a 900 o
        # ultimo saia cortado. Se algum botao entrar ou sair daqui, refazer
        # a conta: largura = 582 + 36 (janela) + 260 (lateral) + 12 + 44.
        self.minsize(940, 560)

        self.settings = load_settings()

        # One-time cleanup of the geometry entries left behind by the old
        # _v2/_v3/_v4 dialog keys, which are never read again.
        removed_geometries = prune_window_geometries(self.settings)
        if removed_geometries:
            audit_log("WINDOW_GEOMETRIES_PRUNED", f"removed={removed_geometries}")

        load_global_paths(self.settings)
        initial_width, initial_height = self.get_saved_main_window_size()
        self.geometry(f"{initial_width}x{initial_height}")
        self._main_geometry_save_after = None
        self._update_check_running = False
        self._restart_running = False

        self.dark_mode = bool(self.settings.get("dark_mode", True))
        self.color_scheme = normalize_color_scheme(
            self.settings.get("color_scheme", COLOR_SCHEME_BLUE)
        )
        self.settings["color_scheme"] = self.color_scheme
        save_settings(self.settings)
        apply_color_theme(self.dark_mode, self.color_scheme)
        self.configure(fg_color=THEME["bg"])

        self.hosts_source = ensure_hosts_source_selected(self, self.settings)
        self.hosts_path = get_hosts_path_for_source(self.hosts_source)
        self.hosts_data = load_hosts_data(self.hosts_path)
        self.unit_names = get_unit_names(self.hosts_data) or ["Geral"]
        audit_log("APP_START", f"hosts_source={hosts_source_display_name(self.hosts_source)}; hosts_file={self.hosts_path}")

        saved_unit = self.settings.get("selected_unit", self.unit_names[0])
        if saved_unit not in self.unit_names:
            saved_unit = self.unit_names[0]
        self.selected_unit = tk.StringVar(value=saved_unit)

        sector_names = get_sector_names(self.hosts_data, saved_unit) or ["Geral"]
        saved_sector = self.settings.get("selected_sector", sector_names[0])
        if saved_sector not in sector_names:
            saved_sector = sector_names[0]
        self.selected_sector = tk.StringVar(value=saved_sector)
        self.host_columns = get_host_columns(self.settings)

        # Search state. The query is deliberately NOT persisted in settings.json:
        # a filter that survives a restart looks exactly like a host list that
        # lost its hosts.
        self.search_var = tk.StringVar(value="")
        self.search_query = ""
        self._search_after_id = None
        self._suppress_search_trace = False
        # Registered once, here, and NOT in build_search_row(): changing the
        # theme destroys and rebuilds the whole main panel, so registering it
        # there would stack one extra callback per theme change.
        self.search_var.trace_add("write", self.on_search_changed)

        self.login_mode = tk.StringVar(
            value=normalize_login_mode(
                self.settings.get("login_mode", LOGIN_MODE_AUTO)
            )
        )

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.build_sidebar()
        self.build_main_panel()
        self.update_window_title()
        self.refresh_all()
        self.update_search_state_label()
        restore_window_geometry(self, "main", initial_width, initial_height)

        self.bind("<Configure>", self.schedule_main_window_size_save)
        self.protocol("WM_DELETE_WINDOW", self.on_main_close)
        self.after(1200, self.show_pending_update_result)
        self.after(2500, self.maybe_check_for_updates_on_startup)

    def get_saved_main_window_size(self):
        geometry = get_window_geometries(self.settings).get("main")
        if geometry and is_valid_geometry(str(geometry)):
            width, height = get_geometry_size(str(geometry), 980, 610)
            return max(940, width), max(560, height)

        raw = str(self.settings.get("main_window_size") or "980x610").lower().strip()
        try:
            width_text, height_text = raw.split("x", 1)
            width = max(940, int(width_text))
            height = max(560, int(height_text))
            return width, height
        except Exception:
            return 980, 610

    def schedule_main_window_size_save(self, event=None):
        if event is not None and event.widget is not self:
            return

        if self.state() == "zoomed":
            return

        if self._main_geometry_save_after:
            self.after_cancel(self._main_geometry_save_after)

        self._main_geometry_save_after = self.after(700, self.save_main_window_size)

    def save_main_window_size(self):
        self._main_geometry_save_after = None
        save_window_geometry(self, "main")
        self.settings = load_settings()

    def on_main_close(self):
        if self._main_geometry_save_after:
            self.after_cancel(self._main_geometry_save_after)
            self._main_geometry_save_after = None

        self.save_main_window_size()
        self.destroy()

    def build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=260, fg_color=THEME["surface"], corner_radius=22)
        self.sidebar.grid(row=0, column=0, sticky="ns", padx=(18, 12), pady=18)
        self.sidebar.grid_propagate(False)

        ctk.CTkLabel(self.sidebar, text="VNC-Menu", font=FONT_TITLE, text_color=THEME["text"]).pack(anchor="w", padx=20, pady=(22, 4))
        self.source_label = ctk.CTkLabel(self.sidebar, text="", font=FONT_SMALL, text_color=THEME["muted"])
        self.source_label.pack(anchor="w", padx=22, pady=(0, 22))

        ctk.CTkLabel(self.sidebar, text="UNIDADE", font=FONT_SMALL_BOLD, text_color=THEME["muted"]).pack(anchor="w", padx=20, pady=(0, 6))
        self.unit_menu = ctk.CTkOptionMenu(
            self.sidebar,
            font=FONT_BOLD,
            values=self.unit_names,
            variable=self.selected_unit,
            command=lambda _v: self.on_main_unit_changed(),
            fg_color=THEME["surface_3"],
            button_color=THEME["accent_soft"],
            button_hover_color=THEME["accent_hover"],
            text_color=THEME["secondary_button_text"],
            dropdown_fg_color=THEME["surface"],
            dropdown_hover_color=THEME["accent_soft"],
            dropdown_text_color=THEME["text"],
        )
        self.unit_menu.pack(fill="x", padx=20, pady=(0, 18))

        ctk.CTkLabel(self.sidebar, text="SETORES", font=FONT_SMALL_BOLD, text_color=THEME["muted"]).pack(anchor="w", padx=20, pady=(0, 6))
        self.sector_frame = ctk.CTkScrollableFrame(self.sidebar, fg_color=THEME["bg"], corner_radius=16)
        self.sector_frame.pack(fill="both", expand=True, padx=20, pady=(0, 18))

        ctk.CTkButton(
            self.sidebar,
            font=FONT_BOLD,
            text="Configurações",
            height=42,
            command=self.open_settings,
            fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"],
            text_color=THEME["text"],
        ).pack(fill="x", padx=20, pady=(0, 20))

    def build_search_row(self):
        """Full-width search bar above the action buttons."""
        row = ctk.CTkFrame(self.main, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew", padx=22, pady=(22, 12))
        row.grid_columnconfigure(0, weight=1)

        self.search_entry = ctk.CTkEntry(
            row,
            textvariable=self.search_var,
            height=38,
            font=FONT_NORMAL,
            placeholder_text="Buscar por nome ou IP/hostname nesta unidade",
            placeholder_text_color=THEME["muted"],
            fg_color=THEME["surface_2"],
            border_color=THEME["border"],
            text_color=THEME["text"],
        )
        self.search_entry.grid(row=0, column=0, sticky="ew")
        self.search_entry.bind("<Escape>", self.on_search_escape)

        ctk.CTkButton(
            row,
            font=FONT_BOLD,
            text="✕",
            width=44,
            height=38,
            command=self.clear_search,
            fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"],
        ).grid(row=0, column=1, sticky="e", padx=(8, 0))

    def on_search_changed(self, *_args):
        if self._suppress_search_trace:
            return
        self.cancel_pending_search()
        self._search_after_id = self.after(SEARCH_DEBOUNCE_MS, self.apply_search)

    def cancel_pending_search(self):
        if self._search_after_id is None:
            return
        try:
            self.after_cancel(self._search_after_id)
        except Exception:
            pass
        self._search_after_id = None

    def apply_search(self):
        self._search_after_id = None
        self.search_query = self.search_var.get().strip()
        self.refresh_sectors()
        self.render_hosts()
        self.update_search_state_label()
        reset_scrollable_frame_position(self.host_grid)

    def reset_search_state(self):
        """Drop the query WITHOUT redrawing. The caller redraws.

        Used by the sector and unit switches, which already redraw right
        after; clearing through apply_search() there would render twice.
        """
        self.cancel_pending_search()
        self.search_query = ""
        if not self.search_var.get():
            return
        self._suppress_search_trace = True
        try:
            self.search_var.set("")
        finally:
            self._suppress_search_trace = False

    def clear_search(self):
        if not self.search_query and not self.search_var.get():
            return
        self.reset_search_state()
        self.refresh_sectors()
        self.render_hosts()
        self.update_search_state_label()
        reset_scrollable_frame_position(self.host_grid)

    def on_search_escape(self, _event=None):
        self.clear_search()
        return "break"

    def build_main_panel(self):
        self.main = ctk.CTkFrame(self, fg_color=THEME["surface"], corner_radius=22)
        self.main.grid(row=0, column=1, sticky="nsew", padx=(0, 18), pady=18)
        self.main.grid_columnconfigure(0, weight=1)
        # Row 0 is the search bar, so the host grid moved from row 2 to row 3.
        self.main.grid_rowconfigure(3, weight=1)

        self.build_search_row()

        top = ctk.CTkFrame(self.main, fg_color="transparent")
        top.grid(row=1, column=0, sticky="ew", padx=22, pady=(0, 16))
        top.grid_columnconfigure(0, weight=1)

        actions = ctk.CTkFrame(top, fg_color="transparent")
        # sticky="ew" mais colunas de peso igual: os botoes dividem a linha
        # inteira em vez de ficarem com largura fixa. Assim a linha continua
        # cheia em qualquer largura de janela, e acrescentar ou remover um
        # botao no futuro so muda a fatia de cada um, sem cortar nem sobrar.
        actions.grid(row=0, column=0, sticky="ew")

        self.btn_users = ctk.CTkButton(
            actions,
            font=FONT_BOLD,
            text="Usuários",
            height=38,
            command=self.show_qwinsta_users,
            fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"],
        )

        self.btn_printers = ctk.CTkButton(
            actions,
            font=FONT_BOLD,
            text="Impressoras",
            height=38,
            command=self.show_remote_printers,
            fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"],
        )

        self.btn_ocs = ctk.CTkButton(
            actions,
            font=FONT_BOLD,
            text="Inventário",
            height=38,
            command=self.open_ocs_search,
            fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"],
        )

        # uniform= amarra as colunas na mesma largura; sem isso o texto mais
        # longo puxaria a coluna dele e os botoes ficariam desiguais.
        # Conectar e Reiniciar sairam daqui: conectar virou o clique no host,
        # reiniciar foi para o menu de contexto. Sobram as tres ferramentas
        # que agem por conta propria.
        botoes = (self.btn_users, self.btn_printers, self.btn_ocs)
        for coluna, botao in enumerate(botoes):
            ultimo = coluna == len(botoes) - 1
            actions.grid_columnconfigure(coluna, weight=1, uniform="acoes")
            botao.grid(row=0, column=coluna, sticky="ew", padx=(0, 0 if ultimo else 8))

        hint = ctk.CTkFrame(self.main, fg_color=THEME["surface_2"], corner_radius=16)
        hint.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 16))
        hint.grid_columnconfigure(0, weight=1)

        self.mode_label = ctk.CTkLabel(
            hint,
            text="",
            font=FONT_NORMAL,
            text_color=THEME["muted"],
            anchor="w",
        )
        self.mode_label.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=(16, 10),
            pady=12,
        )

        hint_actions = ctk.CTkFrame(hint, fg_color="transparent")
        hint_actions.grid(
            row=0,
            column=1,
            sticky="e",
            padx=(0, 12),
            pady=10,
        )

        ctk.CTkButton(
            hint_actions,
            font=FONT_BOLD,
            text="Host manual",
            width=120,
            height=32,
            command=self.open_manual_host,
            fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"],
        ).pack(side="left", padx=(0, 8))

        self.btn_login_mode = ctk.CTkButton(
            hint_actions,
            font=FONT_BOLD,
            text="",
            width=145,
            height=32,
            command=self.toggle_login_mode,
            text_color=THEME["button_text"],
        )
        self.btn_login_mode.pack(side="left")
        self.update_login_mode_button()

        self.host_grid = ctk.CTkScrollableFrame(self.main, fg_color=THEME["bg"], corner_radius=18)
        self.host_grid.grid(row=3, column=0, sticky="nsew", padx=22, pady=(0, 18))

        self.footer = ctk.CTkFrame(self.main, fg_color="transparent")
        self.footer.grid(row=4, column=0, sticky="ew", padx=22, pady=(0, 18))

        self.signature_button = ctk.CTkButton(
            self.footer,
            text=f"{APP_NAME} v{APP_VERSION} • {APP_AUTHOR}",
            width=235,
            height=26,
            command=self.open_about,
            font=FONT_SMALL,
            fg_color="transparent",
            hover_color=THEME["accent_soft"],
            text_color=THEME["muted"],
            anchor="w",
            corner_radius=8,
        )
        self.signature_button.pack(side="left")

        self.count_label = ctk.CTkLabel(
            self.footer,
            text="",
            font=FONT_SMALL,
            text_color=THEME["muted"],
        )
        self.count_label.pack(side="right")

    def update_login_mode_button(self):
        if not hasattr(self, "btn_login_mode"):
            return

        mode = normalize_login_mode(self.login_mode.get())

        if mode == LOGIN_MODE_MANUAL:
            self.btn_login_mode.configure(
                text="Login manual",
                fg_color=THEME["surface_3"],
                hover_color=THEME["accent_soft"],
                text_color=THEME["secondary_button_text"],
            )
        else:
            self.btn_login_mode.configure(
                text="Login automático",
                fg_color=THEME["accent"],
                hover_color=THEME["accent_hover"],
                text_color=THEME["button_text"],
            )

    def toggle_login_mode(self):
        current = normalize_login_mode(self.login_mode.get())
        new_mode = (
            LOGIN_MODE_MANUAL
            if current == LOGIN_MODE_AUTO
            else LOGIN_MODE_AUTO
        )

        self.login_mode.set(new_mode)
        self.settings["login_mode"] = new_mode
        save_settings(self.settings)
        self.update_login_mode_button()
        audit_log("LOGIN_MODE_CHANGED", f"mode={new_mode}")

    def automatic_login_enabled(self) -> bool:
        return normalize_login_mode(self.login_mode.get()) == LOGIN_MODE_AUTO

    def update_search_state_label(self):
        # A busca some a lista do setor e mostra os resultados; sem este aviso
        # nao ha como saber que a lista curta e um filtro, e nao a lista real
        # do setor. Fica vazio fora da busca.
        try:
            self.mode_label.configure(
                text=f"Buscando em: {self.selected_unit.get()}" if self.search_query else ""
            )
        except tk.TclError:
            pass

    def apply_theme_repaint(self):
        # Remove the old widget tree before changing CustomTkinter's global
        # appearance mode. This prevents the brief old-theme redraw and avoids
        # callbacks touching widgets that are about to be destroyed.
        try:
            self.sidebar.destroy()
            self.main.destroy()
        except Exception:
            pass

        apply_color_theme(self.dark_mode, self.color_scheme)
        self.configure(fg_color=THEME["bg"])

        self.build_sidebar()
        self.build_main_panel()
        self.refresh_all()
        self.update_search_state_label()

    def apply_theme_repaint_and_reopen_settings(self):
        try:
            self.apply_theme_repaint()
        except Exception as exc:
            log_exception(exc)
            return

        # Reopen after the main interface has finished rebuilding.
        self.after(40, self.open_settings)

    def refresh_all(self, reset_scroll=False):
        self.refresh_unit_menu()
        self.refresh_sectors()
        self.render_hosts()
        self.update_window_title()
        if reset_scroll:
            self.reset_main_scroll_positions()

    def reset_main_scroll_positions(self):
        reset_scrollable_frame_position(self.sector_frame)
        reset_scrollable_frame_position(self.host_grid)

    def refresh_unit_menu(self):
        self.unit_names = get_unit_names(self.hosts_data) or ["Geral"]
        if self.selected_unit.get() not in self.unit_names:
            self.selected_unit.set(self.unit_names[0])
        self.unit_menu.configure(values=self.unit_names)
        self.unit_menu.set(self.selected_unit.get())

    def refresh_sectors(self):
        for child in self.sector_frame.winfo_children():
            child.destroy()

        sector_names = get_sector_names(self.hosts_data, self.selected_unit.get()) or ["Geral"]
        if self.selected_sector.get() not in sector_names:
            self.selected_sector.set(sector_names[0])

        for name in sector_names:
            # While searching, no sector is driving the list, so none is shown
            # as selected. Highlighting one next to results from other sectors
            # is the kind of small lie that turns into a support call.
            selected = (not self.search_query) and name == self.selected_sector.get()
            btn = ctk.CTkButton(
                self.sector_frame,
                font=FONT_BOLD,
                text=name,
                anchor="w",
                height=38,
                fg_color=THEME["accent"] if selected else THEME["surface_2"],
                hover_color=(
                    THEME["accent_hover"]
                    if selected
                    else THEME["accent_soft"]
                ),
                text_color=(
                    THEME["button_text"]
                    if selected
                    else THEME["text"]
                ),
                command=lambda n=name: self.set_sector(n),
            )
            btn.pack(fill="x", padx=8, pady=5)

    def render_hosts(self):
        for child in self.host_grid.winfo_children():
            child.destroy()

        self.source_label.configure(text=f"Lista: {hosts_source_display_name(self.hosts_source)}")

        if self.search_query:
            self.render_search_results()
            return

        hosts = get_sector_hosts(self.hosts_data, self.selected_unit.get(), self.selected_sector.get())
        self.count_label.configure(text=f"{len(hosts)} host(s) encontrado(s)")

        if not hosts:
            ctk.CTkLabel(
                self.host_grid,
                text="Nenhum host cadastrado neste setor.",
                font=FONT_NORMAL,
                text_color=THEME["muted"],
            ).pack(anchor="w", padx=18, pady=18)
            return

        cols = max(1, min(int(self.host_columns), 6))

        for start in range(0, len(hosts), cols):
            row_hosts = hosts[start:start + cols]
            row_frame = ctk.CTkFrame(self.host_grid, fg_color="transparent")
            row_frame.pack(fill="x", padx=8, pady=6)

            for item in row_hosts:
                display_name = str(item.get("name") or "Host")
                if len(display_name) > 22:
                    display_name = display_name[:21] + "…"

                # Each button sits inside an equal-width cell. This prevents
                # longer labels from making one button wider/taller than the others.
                cell = ctk.CTkFrame(row_frame, fg_color="transparent", height=44)
                cell.pack(side="left", fill="x", expand=True, padx=6)
                cell.pack_propagate(False)

                card = ctk.CTkButton(
                    cell,
                    text=display_name,
                    font=("Segoe UI", 12, "bold"),
                    text_color=THEME["text"],
                    anchor="center",
                    height=44,
                    fg_color=THEME["surface_2"],
                    hover_color=THEME["accent_soft"],
                    corner_radius=14,
                    command=lambda n=item.get("name"), h=item.get("host"), v=item.get("viewer", DEFAULT_VIEWER), p=item.get("port"): self.run_host_action(n, h, v, p),
                )
                card.pack(fill="both", expand=True)
                card.bind(
                    "<Button-3>",
                    lambda event, h=item.get("host"), n=item.get("name"), p=item.get("port"): self.show_host_context_menu(event, h, n, p),
                    add="+",
                )

            missing = cols - len(row_hosts)
            for _ in range(missing):
                spacer = ctk.CTkFrame(row_frame, fg_color="transparent", height=44)
                spacer.pack(side="left", fill="x", expand=True, padx=6)
                spacer.pack_propagate(False)


    def render_search_results(self):
        """One row per match: name, IP/hostname, sector.

        A list rather than the usual grid on purpose. The row has room for the
        three values at any window size, and it stays readable no matter what
        "Colunas da Tela" is set to, which a two-line card would not.
        """
        results = filter_unit_hosts(self.hosts_data, self.selected_unit.get(), self.search_query)
        self.count_label.configure(text=f"{len(results)} host(s) encontrado(s)")

        if not results:
            ctk.CTkLabel(
                self.host_grid,
                text=f'Nenhum host encontrado para "{self.search_query}" em {self.selected_unit.get()}.',
                font=FONT_NORMAL,
                text_color=THEME["muted"],
            ).pack(anchor="w", padx=18, pady=18)
            return

        for sector_name, item in results:
            self.build_search_result_row(sector_name, item)

    def build_search_result_row(self, sector_name, item):
        name = str(item.get("name") or "Host")
        host = str(item.get("host") or "")
        viewer = item.get("viewer", DEFAULT_VIEWER)
        port = item.get("port")

        row = ctk.CTkFrame(self.host_grid, fg_color=THEME["surface_2"], corner_radius=12, height=40)
        row.pack(fill="x", padx=8, pady=4)
        row.pack_propagate(False)

        # The sector chip and the address keep their natural width; the name
        # column absorbs whatever the window has to spare. Fixed pixel widths
        # here would leave the row stretching while its contents stayed put.
        sector_label = ctk.CTkLabel(
            row,
            text=sector_name if len(sector_name) <= 18 else sector_name[:17] + "…",
            font=FONT_SMALL_BOLD,
            text_color=THEME["secondary_button_text"],
            fg_color=THEME["surface_3"],
            corner_radius=999,
            width=SEARCH_SECTOR_COLUMN_WIDTH,
            anchor="center",
        )
        sector_label.pack(side="right", padx=(8, 14), pady=7)

        host_label = ctk.CTkLabel(
            row,
            # Shows the port only when it is not the default one, same rule the
            # context menu already uses.
            text=format_host_port(host, sanitize_port(port)),
            font=FONT_SMALL,
            text_color=THEME["muted"],
            width=SEARCH_HOST_COLUMN_WIDTH,
            anchor="w",
        )
        host_label.pack(side="right", padx=(8, 8))

        name_label = ctk.CTkLabel(
            row,
            text=name if len(name) <= 60 else name[:59] + "…",
            font=("Segoe UI", 12, "bold"),
            text_color=THEME["text"],
            anchor="w",
        )
        name_label.pack(side="left", fill="x", expand=True, padx=(14, 8))

        def on_click(_event=None):
            # The row carries its OWN sector, not the selected one: it decides
            # which RealVNC profile gets opened.
            self.run_host_action(name, host, viewer, port, sector=sector_name)

        def on_context(event):
            self.show_host_context_menu(event, host, name, port)

        bind_clickable_row(
            row, (name_label, host_label, sector_label), on_click, on_context,
            THEME["surface_2"], THEME["accent_soft"],
        )

    def on_main_unit_changed(self):
        # The search only ever covers one unit. Carrying the query across a unit
        # switch would show a short or empty list for a unit the user has not
        # searched yet, which reads as "my hosts disappeared".
        self.reset_search_state()
        sector_names = get_sector_names(self.hosts_data, self.selected_unit.get()) or ["Geral"]
        self.selected_sector.set(sector_names[0])
        self.save_main_selection()
        self.refresh_sectors()
        self.render_hosts()
        self.update_search_state_label()
        self.reset_main_scroll_positions()

    def set_sector(self, sector_name):
        # Picking a sector is the natural "get me out of the search" gesture.
        self.reset_search_state()
        self.selected_sector.set(sector_name)
        self.save_main_selection()
        self.refresh_sectors()
        self.render_hosts()
        self.update_search_state_label()
        reset_scrollable_frame_position(self.host_grid)

    def save_main_selection(self):
        self.settings["selected_unit"] = self.selected_unit.get()
        self.settings["selected_sector"] = self.selected_sector.get()
        save_settings(self.settings)

    def copy_host_to_clipboard(self, host):
        host = str(host or "").strip()
        if not host:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(host)
            self.update_idletasks()
            audit_log("HOST_COPIED", f"host={host}")
        except Exception as e:
            log_exception(e)
            show_error(self, "Copiar host", f"Falha ao copiar host/IP:\n{e}")

    def open_host_admin_share(self, host):
        host = str(host or "").strip().lstrip("\\")
        if not host:
            return

        unc_path = rf"\\{host}\c$"

        try:
            # Use the Windows shell directly, matching the behavior of opening
            # a UNC path through Win+R more closely than explorer.exe.
            result = ctypes.windll.shell32.ShellExecuteW(
                None,
                "open",
                unc_path,
                None,
                None,
                1,
            )

            if result <= 32:
                raise OSError(f"ShellExecuteW falhou com código {result}")

            audit_log("HOST_ADMIN_SHARE_OPENED", f"host={host}; path={unc_path}")
        except Exception as e:
            log_exception(e)
            audit_log("HOST_ADMIN_SHARE_ERROR", f"host={host}; path={unc_path}; error={e}")
            show_error(
                self,
                "Abrir pasta",
                f"Falha ao abrir:\n{unc_path}\n\n{e}",
            )

    def open_host_startup_folder(self, host):
        host = str(host or "").strip().lstrip("\\")
        if not host:
            return

        unc_path = (
            rf"\\{host}\c$\ProgramData\Microsoft\Windows"
            rf"\Start Menu\Programs\Startup"
        )

        try:
            result = ctypes.windll.shell32.ShellExecuteW(
                None,
                "open",
                unc_path,
                None,
                None,
                1,
            )

            if result <= 32:
                raise OSError(f"ShellExecuteW falhou com código {result}")

            audit_log(
                "HOST_STARTUP_FOLDER_OPENED",
                f"host={host}; path={unc_path}",
            )
        except Exception as e:
            log_exception(e)
            audit_log(
                "HOST_STARTUP_FOLDER_ERROR",
                f"host={host}; path={unc_path}; error={e}",
            )
            show_error(
                self,
                "Abrir Menu Iniciar",
                f"Falha ao abrir:\n{unc_path}\n\n{e}",
            )

    def show_host_context_menu(self, event, host, display_name=None, port=None):
        host = str(host or "").strip()
        display_name = str(display_name or "").strip()
        if not host:
            return
        # Shown with the port only when it is not the default one.
        host_label = format_host_port(host, sanitize_port(port))

        # Keep the menu alive while it is open. Destroying it immediately after
        # tk_popup()/post() can make the entries visible but prevent commands
        # from executing when clicked.
        old_menu = getattr(self, "_host_context_menu", None)
        if old_menu is not None:
            try:
                old_menu.destroy()
            except Exception:
                pass

        menu = tk.Menu(self, tearoff=0)
        self._host_context_menu = menu

        def close_menu():
            try:
                menu.unpost()
            except Exception:
                pass
            try:
                menu.destroy()
            except Exception:
                pass
            if getattr(self, "_host_context_menu", None) is menu:
                self._host_context_menu = None

        def copy_ip():
            close_menu()
            self.copy_host_to_clipboard(host)

        def open_c_share():
            close_menu()
            self.open_host_admin_share(host)

        def open_startup_folder():
            close_menu()
            self.open_host_startup_folder(host)

        def open_printers():
            close_menu()
            self.show_remote_printers(host, display_name)

        def open_sessions():
            close_menu()
            self.show_host_sessions(host, display_name)

        def open_restart():
            close_menu()
            self.restart_host_from_menu(host, display_name)

        # Show the configured hostname/IP as the first line so support can
        # quickly confirm the target without opening the hosts configuration.
        menu.add_command(
            label=f"Host/IP: {host_label}",
            state="disabled",
        )
        menu.add_separator()
        # Reiniciar era um modo global; virou acao por host aqui, com a mesma
        # confirmacao de antes, para nao reiniciar maquina por engano.
        menu.add_command(label="Reiniciar", command=open_restart)
        menu.add_separator()
        menu.add_command(label="Copiar IP", command=copy_ip)
        menu.add_command(label="Abrir c$", command=open_c_share)
        menu.add_command(
            label="Abrir Menu Iniciar",
            command=open_startup_folder,
        )
        menu.add_command(label="Impressoras", command=open_printers)
        # Mesma consulta do botao Usuarios, porem em um host so. E o unico
        # caminho para ver o texto cru do qwinsta de uma maquina especifica,
        # que e o que diz POR QUE ela aparece como "erro" na busca do OCS.
        menu.add_command(label="Sessões", command=open_sessions)

        # post() leaves the menu active until the user selects an item or clicks
        # elsewhere. Do not destroy it in a finally block.
        menu.post(event.x_root, event.y_root)
        menu.focus_set()

    def restart_host_async(self, host, display_name=None):
        """Send the restart from a worker thread so the interface stays usable."""
        target = str(host or "").strip()
        if not target:
            return

        label = str(display_name or "").strip() or target

        if getattr(self, "_restart_running", False):
            show_info(self, "Reiniciar", "Um reinício já está sendo enviado. Aguarde.")
            return

        # Guard so a second restart cannot be sent while one is in flight.
        # There is no longer a Reiniciar button to grey out, but the guard
        # still prevents a double reboot from two quick confirmations.
        self._restart_running = True

        def worker():
            try:
                restart_host(target)
                error = None
            except Exception as exc:
                error = exc

            def finish():
                self._restart_running = False

                if error is not None:
                    show_error(
                        self,
                        "Erro",
                        f'Falha ao reiniciar "{label}":\n{error}\n\nLog: {ERROR_LOG}',
                    )
                    return

                # Sucesso nao avisa nada. O botao ja mostrou "Enviando..." e
                # voltou ao normal, a confirmacao antes do envio ja disse o que
                # ia acontecer, e a falha abre um dialogo. Um aviso de sucesso
                # ainda diria so que o comando foi aceito, nao que a maquina
                # reiniciou, e teria que ser fechado a cada host.

            self.after(0, finish)

        threading.Thread(
            target=worker,
            name="VNC-Menu-Restart",
            daemon=True,
        ).start()

    def run_host_action(self, name, host, viewer=DEFAULT_VIEWER, port=None, sector=None):
        # O clique num host agora significa sempre conectar. Reiniciar saiu
        # daqui para o menu de contexto, entao um clique distraido nao reinicia
        # mais a maquina.
        #
        # O setor escolhe o perfil RealVNC (<Setor>_<Nome>.vnc), entao tem que
        # ser o setor a que o host pertence de fato. Um resultado de busca pode
        # vir de outro setor, e passar a selecao abriria o perfil errado.
        sector_name = sector if sector is not None else self.selected_sector.get()
        launch_vnc(
            host,
            viewer,
            name,
            sector_name,
            self,
            automatic_login=self.automatic_login_enabled(),
            port=port,
        )

    def restart_host_from_menu(self, host, display_name=None):
        """Reinicio pelo menu de contexto do host, com a mesma confirmacao."""
        label = str(display_name or "").strip() or str(host or "").strip()
        if not label:
            return
        if confirm_action(self, "Confirmar reinício", f'Reiniciar "{label}" agora?'):
            self.restart_host_async(host, display_name)

    def open_manual_host(self):
        """Janela de acoes para um host digitado a mao.

        Substitui o antigo botao que alternava conectar/reiniciar. Reune num
        so lugar tudo que o app sabe fazer com um host, e e onde a limpeza de
        perfis vai entrar depois.
        """
        HostActionsWindow(self)

    def connect_manual_host(self, host, viewer=DEFAULT_VIEWER, port=None):
        host = str(host or "").strip().lstrip("\\")
        if not host:
            return
        # Sem nome nem setor: um host avulso nao esta no hosts.json, entao nao
        # existe perfil RealVNC <Setor>_<Nome>.vnc para ele.
        launch_vnc(
            host,
            viewer,
            parent=self,
            automatic_login=self.automatic_login_enabled(),
            port=port,
        )

    def restart_manual_host(self, host):
        host = str(host or "").strip().lstrip("\\")
        if not host:
            return
        if confirm_action(self, "Confirmar reinício", f'Reiniciar "{host}" agora?'):
            self.restart_host_async(host)

    def reload_hosts_from_current_source(self):
        self.hosts_source = normalize_hosts_source(self.settings.get("hosts_source")) or HOSTS_SOURCE_SHARED
        self.hosts_path = get_hosts_path_for_source(self.hosts_source)
        self.hosts_data = load_hosts_data(self.hosts_path)
        self.refresh_all(reset_scroll=True)

    def update_window_title(self):
        self.title(f"VNC-Menu [{hosts_source_display_name(self.hosts_source)}]")

    def show_pending_update_result(self):
        if not UPDATE_RESULT_JSON.exists():
            return
        try:
            result = json.loads(UPDATE_RESULT_JSON.read_text(encoding="utf-8"))
        except Exception:
            result = {}
        try:
            UPDATE_RESULT_JSON.unlink(missing_ok=True)
        except Exception:
            pass

        status = str(result.get("status") or "")
        version = str(result.get("version") or "")
        message = str(result.get("message") or "")

        if status == "success":
            show_info(
                self,
                "Atualização concluída",
                f"O VNC-Menu foi atualizado para a versão {version or APP_VERSION}.",
            )
        elif status == "error":
            show_error(
                self,
                "Falha na atualização",
                message or "A atualização falhou e a versão anterior foi restaurada.",
            )

    def maybe_check_for_updates_on_startup(self):
        if not bool(self.settings.get("check_updates_on_startup", True)):
            return

        self.check_for_updates(manual=False)

    def check_for_updates(self, manual: bool = True):
        if self._update_check_running:
            if manual:
                show_info(self, "Atualizações", "Uma verificação já está em andamento.")
            return

        self._update_check_running = True
        progress = UpdateCheckProgressWindow(self) if manual else None
        audit_log("UPDATE_CHECK_STARTED", f"manual={manual}")

        def worker():
            try:
                release = fetch_latest_release()
                error = None
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    error = RuntimeError("Nenhuma release publicada foi encontrada no GitHub.")
                elif exc.code == 403:
                    error = RuntimeError(
                        "O GitHub recusou a consulta, possivelmente por limite temporário de requisições."
                    )
                else:
                    error = RuntimeError(f"GitHub respondeu com HTTP {exc.code}.")
                release = None
            except urllib.error.URLError as exc:
                release = None
                reason = getattr(exc, "reason", None)
                if isinstance(reason, ssl.SSLCertVerificationError):
                    error = RuntimeError(
                        "Não foi possível validar o certificado HTTPS do GitHub. "
                        "Verifique o certificado da rede/proxy ou tente novamente."
                    )
                else:
                    error = exc
            except ssl.SSLError as exc:
                release = None
                error = RuntimeError(
                    f"Falha na conexão segura com o GitHub: {exc}"
                )
            except Exception as exc:
                release = None
                error = exc

            def finish():
                self._update_check_running = False
                if progress is not None:
                    try:
                        progress.close()
                    except Exception:
                        pass

                if error is not None:
                    audit_log("UPDATE_CHECK_ERROR", f"error={error}")
                    if manual:
                        show_error(self, "Atualizações", f"Falha ao verificar atualizações:\n{error}")
                    return

                # Pylance cannot infer that release is non-None only because
                # error is None. Keep an explicit runtime/type guard here.
                if not isinstance(release, dict):
                    audit_log(
                        "UPDATE_CHECK_ERROR",
                        "error=GitHub release response is missing or invalid",
                    )
                    if manual:
                        show_error(
                            self,
                            "Atualizações",
                            "O GitHub retornou uma resposta de release inválida.",
                        )
                    return

                latest_version = normalize_release_version(release.get("tag_name", ""))
                audit_log(
                    "UPDATE_CHECK_COMPLETED",
                    f"current={APP_VERSION}; latest={latest_version}",
                )

                if parse_version(latest_version) <= parse_version(APP_VERSION):
                    if manual:
                        show_info(
                            self,
                            "Atualizações",
                            f"O VNC-Menu já está atualizado.\n\nVersão instalada: {APP_VERSION}",
                        )
                    return

                skipped = str(self.settings.get("skipped_update_version") or "")
                if not manual and skipped == latest_version:
                    return

                UpdateAvailableWindow(self, release)

            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def download_and_install_update(self, release: dict):
        latest_version = normalize_release_version(release.get("tag_name", ""))
        download_window = UpdateDownloadWindow(self, latest_version)

        def worker():
            try:
                asset = find_release_zip_asset(release)
                asset_url = str(asset.get("browser_download_url") or "").strip()
                asset_name = str(asset.get("name") or f"VNC-Menu-v{latest_version}.zip")
                if not asset_url:
                    raise RuntimeError("URL do arquivo de atualização não encontrada.")

                expected_sha256 = get_release_asset_checksum(release, asset)
                version_dir = UPDATE_DOWNLOAD_DIR / safe_filename(latest_version)
                if version_dir.exists():
                    shutil.rmtree(version_dir, ignore_errors=True)
                version_dir.mkdir(parents=True, exist_ok=True)
                archive_path = version_dir / asset_name

                request = urllib.request.Request(
                    asset_url,
                    headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"},
                )
                with urllib.request.urlopen(request, timeout=60, context=HTTPS_CONTEXT) as response:
                    try:
                        total = int(response.headers.get("Content-Length") or 0)
                    except Exception:
                        total = 0
                    downloaded = 0
                    with archive_path.open("wb") as file:
                        while True:
                            chunk = response.read(1024 * 256)
                            if not chunk:
                                break
                            file.write(chunk)
                            downloaded += len(chunk)
                            self.after(
                                0,
                                lambda current=downloaded, size=total: download_window.update_progress(current, size),
                            )

                self.after(0, lambda: download_window.set_status("Verificando integridade..."))
                actual_sha256 = calculate_sha256(archive_path)
                if actual_sha256.lower() != expected_sha256.lower():
                    raise RuntimeError(
                        "A verificação SHA-256 falhou. Nenhum arquivo foi alterado."
                    )

                with zipfile.ZipFile(archive_path, "r") as archive:
                    if archive.testzip() is not None:
                        raise RuntimeError("O arquivo ZIP da atualização está corrompido.")

                command = get_updater_launch_command(version_dir)
                command.extend([
                    "--pid", str(os.getpid()),
                    "--archive", str(archive_path),
                    "--install-dir", str(SCRIPT_DIR),
                    "--main-entry", current_main_entry_name(),
                    "--version", latest_version,
                ])

                creationflags = 0
                creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
                creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)

                subprocess.Popen(
                    command,
                    cwd=str(SCRIPT_DIR),
                    close_fds=True,
                    creationflags=creationflags,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

                audit_log(
                    "UPDATE_INSTALLER_STARTED",
                    f"version={latest_version}; archive={archive_path}; install_dir={SCRIPT_DIR}",
                )
                self.after(0, lambda: download_window.set_status("Reiniciando para instalar..."))
                self.after(600, self.destroy)
                return

            except Exception as exc:
                log_exception(exc)
                audit_log("UPDATE_DOWNLOAD_ERROR", f"version={latest_version}; error={exc}")

                def show_failure():
                    try:
                        download_window.close()
                    except Exception:
                        pass
                    show_error(self, "Atualizações", f"Falha ao preparar a atualização:\n{exc}")

                self.after(0, show_failure)

        threading.Thread(target=worker, daemon=True).start()

    def open_settings(self):
        SettingsWindow(self)

    def open_about(self):
        AboutWindow(self)

    def open_hosts_source_config(self):
        source = choose_hosts_source_dialog(self, required=False)
        if not source:
            return

        try:
            saved = set_hosts_source(self.settings, source, overwrite_user_file=True)
        except Exception as exc:
            log_exception(exc)
            audit_log("HOSTS_SOURCE_CHANGE_ERROR", f"source={source}; error={exc}")
            show_error(
                self,
                "Selecionar Lista",
                f"Não foi possível preparar a lista selecionada:\n\n{exc}\n\nLog: {ERROR_LOG}",
            )
            return

        if not saved:
            show_warning(
                self,
                "Selecionar Lista",
                "A lista foi trocada, mas não foi possível salvar a preferência.\n"
                "Ela pode voltar ao valor anterior no próximo início.",
            )

        audit_log("HOSTS_SOURCE_CHANGED_BY_USER", f"source={hosts_source_display_name(source)}; file={self.settings.get('hosts_file', '')}")
        self.reload_hosts_from_current_source()

    def open_config(self):
        if normalize_hosts_source(self.settings.get("hosts_source")) == HOSTS_SOURCE_SHARED:
            choice = shared_hosts_edit_warning(self)
            audit_log("SHARED_HOSTS_EDIT_PROMPT", f"choice={choice}; file={self.hosts_path}")
            if choice == "cancel":
                return
            if choice == "copy":
                try:
                    set_hosts_source(self.settings, HOSTS_SOURCE_CUSTOM, overwrite_user_file=True)
                except Exception as exc:
                    log_exception(exc)
                    audit_log("HOSTS_SOURCE_COPY_ERROR", f"error={exc}")
                    show_error(
                        self,
                        "Hosts e Setores",
                        "Não foi possível preparar sua lista pessoal.\n"
                        "A edição foi cancelada para não alterar a lista compartilhada "
                        f"sem querer.\n\n{exc}\n\nLog: {ERROR_LOG}",
                    )
                    return
                self.reload_hosts_from_current_source()

        HostUnitsConfigWindow(self, self.hosts_data, self.on_hosts_saved, self.hosts_path)

    def open_ocs_search(self):
        """Busca de maquinas por usuario no inventario do OCS."""
        OcsSearchWindow(self)

    def open_ocs_config(self):
        OcsConfigWindow(self)

    def open_creds(self):
        CredsWindow(self)

    def open_viewer_paths(self):
        ViewerPathsWindow(self)

    def open_psexec_path(self):
        PsExecPathWindow(self)

    def open_host_columns_config(self):
        current = str(self.host_columns)
        value = ask_text(
            self,
            "Colunas da Tela",
            "Quantas colunas de hosts? (1 a 6)",
            current,
        )
        if value is None:
            return

        try:
            columns = int(value.strip())
        except Exception:
            show_warning(self, "Colunas da Tela", "Digite um número de 1 a 6.")
            return

        if columns < 1 or columns > 6:
            show_warning(self, "Colunas da Tela", "Digite um número de 1 a 6.")
            return

        self.host_columns = columns
        self.settings["host_columns"] = columns
        save_settings(self.settings)
        audit_log("HOST_COLUMNS_CHANGED", f"columns={columns}")
        self.render_hosts()

    def on_hosts_saved(self, hosts_data):
        self.hosts_data = hosts_data
        self.refresh_all(reset_scroll=True)

    def show_qwinsta_users(self):
        unit_name = self.selected_unit.get()
        sector_name = self.selected_sector.get()
        hosts = [dict(item) for item in get_sector_hosts(self.hosts_data, unit_name, sector_name)]
        label = f"{unit_name} > {sector_name}"

        if not hosts:
            show_text_window(
                self,
                "Usuários logados",
                f"Setor sem hosts ou inexistente: {label}",
                remember_geometry_key=None,
            )
            return

        audit_log("USERS_QUERY", f"unidade={unit_name}; setor={sector_name}; hosts={len(hosts)}")

        progress = QwinstaProgressWindow(self, label, len(hosts))
        self.btn_users.configure(state="disabled", text="Consultando...")

        def worker():
            try:
                result = query_all_logged_users(hosts)
                error = None
            except Exception as exc:
                log_exception(exc)
                result = ""
                error = exc

            def finish():
                try:
                    if progress.winfo_exists():
                        progress.close()
                except Exception:
                    pass

                self.btn_users.configure(state="normal", text="Usuários")

                if error:
                    show_error(self, "Usuários logados", f"Falha ao consultar usuários:\n{error}\n\nLog: {ERROR_LOG}")
                    return

                show_text_window(
                    self,
                    f"Usuários logados - {label}",
                    result,
                    remember_geometry_key=None,
                )

            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def show_host_sessions(self, host, display_name=None):
        """Consulta as sessoes de UM host e mostra o retorno cru do qwinsta.

        O botao Usuarios so consulta o setor inteiro e a busca do OCS so tem
        espaco para "erro" na coluna. Aqui a maquina e escolhida a mao e o
        texto do qwinsta aparece inteiro, que e o que diz se foi acesso
        negado, nome nao resolvido ou tempo esgotado.
        """
        host = str(host or "").strip().lstrip("\\")
        if not host:
            return
        display_name = str(display_name or "").strip()
        label = display_name or host

        # Uma consulta por host de cada vez. Sem isso, dois cliques seguidos
        # abrem duas janelas de progresso e duas de resultado para o mesmo
        # host, e a segunda cobre a primeira.
        em_andamento = getattr(self, "_session_queries", None)
        if em_andamento is None:
            em_andamento = self._session_queries = set()
        chave = host.casefold()
        if chave in em_andamento:
            return
        em_andamento.add(chave)

        audit_log("HOST_SESSION_QUERY", f"name={display_name or '-'}; host={host}")
        progress = QwinstaProgressWindow(self, label, 1)

        def worker():
            try:
                rows = query_logged_users_raw([{"name": label, "host": host}])
                error = None
            except Exception as exc:
                log_exception(exc)
                rows, error = [], exc

            def finish():
                em_andamento.discard(chave)
                try:
                    if progress.winfo_exists():
                        progress.close()
                except Exception:
                    pass

                if error is not None:
                    show_error(
                        self,
                        "Sessões",
                        f"Falha ao consultar as sessões de {label}:\n{error}\n\nLog: {ERROR_LOG}",
                    )
                    return

                show_text_window(
                    self,
                    f"Sessões - {label}",
                    format_users_output(rows),
                    remember_geometry_key=None,
                )

            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def show_remote_printers(
        self,
        host: str | None = None,
        display_name: str | None = None,
    ):
        if str(self.btn_printers.cget("state")) == "disabled":
            return

        if host is None:
            display_name = None
            host = ask_text(
                self,
                "Consultar impressoras",
                "Digite o hostname ou IP do computador:",
            )
        if not host:
            return

        host = str(host).strip().lstrip("\\")
        display_name = str(display_name or "").strip()
        psexec_path = find_psexec()
        if psexec_path is None:
            audit_log("PSEXEC_NOT_FOUND_IN_PATH")
            psexec_path = show_psexec_required_dialog(self)
        if psexec_path is None:
            return

        audit_log(
            "PRINTERS_QUERY",
            f"name={display_name or '-'}; host={host}; psexec={psexec_path}",
        )
        progress = PrinterProgressWindow(self, host)
        self.btn_printers.configure(state="disabled", text="Consultando...")

        def worker():
            status = "ok"
            result = ""
            error = None

            try:
                if not host_responds_to_ping(host):
                    status = "offline"
                    audit_log("PRINTERS_HOST_OFFLINE", f"host={host}")
                else:
                    result = query_remote_printers(host, psexec_path)
            except PsExecQueryError as exc:
                log_psexec_failure(host, psexec_path, exc)
                audit_log(
                    "PRINTERS_PSEXEC_ERROR",
                    f"host={host}; category={exc.category}; code={exc.returncode}; error={exc.summary}",
                )
                status = "error"
                error = exc
            except Exception as exc:
                log_exception(exc)
                audit_log("PRINTERS_QUERY_ERROR", f"host={host}; error={exc}")
                status = "error"
                error = exc

            def finish():
                try:
                    if progress.winfo_exists():
                        progress.close()
                except Exception:
                    pass

                self.btn_printers.configure(
                    state="normal",
                    text="Impressoras",
                )

                if status == "offline":
                    show_error(
                        self,
                        "Erro",
                        "O computador está desligado ou não respondeu à rede.",
                    )
                    return

                if error:
                    if isinstance(error, PsExecQueryError):
                        show_psexec_error_dialog(self, host, error)
                    else:
                        show_error(
                            self,
                            "Consultar impressoras",
                            f"Falha ao consultar impressoras em {host}:\n\n"
                            f"{error}\n\nLog: {ERROR_LOG}",
                        )
                    return

                audit_log("PRINTERS_QUERY_OK", f"host={host}")
                result_target = (
                    f"{display_name} ({host})"
                    if display_name
                    else host
                )
                show_text_window(
                    self,
                    f"Impressoras - {result_target}",
                    result,
                    remember_geometry_key=None,
                )

            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()


def main():
    problems = bootstrap_directories()
    app = App()

    if problems:
        # Reported after the interface exists, so the user sees which folder
        # failed instead of the application silently not opening.
        details = "\n".join(problems)
        audit_log("BOOTSTRAP_DIRECTORIES_ERROR", details.replace("\n", " | "))
        app.after(
            900,
            lambda: show_warning(
                app,
                "VNC-Menu",
                "Não foi possível preparar algumas pastas do aplicativo.\n"
                "O VNC-Menu vai abrir, mas salvar configurações, logs ou hosts "
                "pode falhar.\n\n"
                f"{details}",
            ),
        )

    app.mainloop()
