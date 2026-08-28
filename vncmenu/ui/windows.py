"""Janelas maiores.

Editor de hosts e setores, credenciais, caminhos, configuracoes,
sobre, janelas de progresso e a janela de saida de texto.
"""

from typing import Any
from datetime import datetime
from pathlib import Path
import customtkinter as ctk
from tkinter import filedialog
import json
import os
import threading
import tkinter as tk
import webbrowser

from ..config import APP_AUTHOR, APP_NAME, APP_VERSION, COLOR_SCHEME_BLUE, COLOR_SCHEME_PURPLE, DEFAULT_VIEWER, ERROR_LOG, OCS_COL_AGE, OCS_COL_DATE, OCS_COL_IP, OCS_COL_SESSION, OCS_COL_TAG, OCS_ROW_PITCH, OCS_STALE_DAYS, OCS_VISIBLE_ROWS, OCS_WINDOW_HEIGHT, OCS_WINDOW_WIDTH, GITHUB_PROFILE_URL, GITHUB_RELEASES_URL, GITHUB_URL, LICENSE_URL, LOGS_DIR, REALVNC_EXE, SHARED_HOSTS_JSON, ULTRAVNC_EXE, VIEWER_OPTIONS, VIEWER_REALVNC
from ..applog import audit_log, log_exception
from ..storage import format_host_port, load_ocs_creds, load_ocs_url, sanitize_port, split_host_port, save_ocs_creds, save_ocs_url, get_sector_by_name, get_sector_names, get_unit_by_name, get_unit_names, load_creds, load_global_paths, load_psexec_path, normalize_hosts_data, sanitize_viewer, save_creds, save_global_paths, save_json, save_psexec_path, save_settings, viewer_display_name
from ..theme import FONT_BOLD, FONT_NORMAL, FONT_SMALL, FONT_SMALL_BOLD, FONT_SUBTITLE, THEME, color_scheme_display_name
from ..helpers import bind_clickable_row, center_window, reset_scrollable_frame_position, fit_dialog_to_content, remember_window_geometry, rename_realvnc_profile, rename_realvnc_profiles_for_sector, safe_filename, save_window_geometry, show_error, show_warning
from ..updates import fetch_latest_release, format_release_notes_for_display, normalize_release_version
from .dialogs import ModalDialog, ask_host_details, ask_text, confirm_action
from ..remote import PsExecQueryError, format_users_output, query_logged_users_raw
from ..ocs import (OcsError, SESSION_DIFFERENT, SESSION_ERROR, SESSION_NONE, SESSION_OFFLINE,
                   SESSION_SAME, connection_target, count_stale, format_session, is_stale,
                   search_machines_by_user, session_status)

def show_text_window(
    parent,
    title,
    content,
    *,
    remember_geometry_key: str | None = "window_text_output",
):
    lines = str(content or "").splitlines() or [""]
    max_len = max((len(line) for line in lines), default=40)
    line_count = max(len(lines), 1)

    try:
        screen_width = parent.winfo_screenwidth()
        screen_height = parent.winfo_screenheight()
    except Exception:
        screen_width, screen_height = 1366, 768

    max_width = max(520, min(1000, screen_width - 140))
    max_height = max(360, min(760, screen_height - 140))
    title_width = (len(str(title)) * 8) + 120
    width = min(max((max_len * 8) + 110, title_width, 480), max_width)
    height = min(max((line_count * 19) + 155, 285), max_height)
    textbox_height = max(height - 155, 130)

    win = ctk.CTkToplevel(parent)
    win.title(title)
    win.geometry(f"{width}x{height}")
    win.minsize(440, 260)
    win.configure(fg_color=THEME["bg"])

    outer = ctk.CTkFrame(win, fg_color=THEME["surface"], corner_radius=18)
    outer.pack(fill="both", expand=True, padx=18, pady=18)

    ctk.CTkLabel(
        outer,
        text=title,
        font=FONT_SUBTITLE,
        text_color=THEME["text"],
    ).pack(anchor="w", padx=18, pady=(18, 10))

    textbox = ctk.CTkTextbox(
        outer,
        height=textbox_height,
        font=("Consolas", 12),
        fg_color=THEME["bg"],
        text_color=THEME["text"],
        corner_radius=12,
        wrap="none",
    )
    textbox.pack(fill="both", expand=True, padx=18, pady=(0, 14))
    textbox.insert("1.0", content)
    textbox.configure(state="disabled")

    ctk.CTkButton(
        outer,
        font=FONT_BOLD,
        text="Fechar",
        width=140,
        height=36,
        command=win.destroy,
        fg_color=THEME["surface_3"],
        hover_color=THEME["accent_soft"],
        text_color=THEME["secondary_button_text"],
    ).pack(anchor="e", padx=18, pady=(0, 18))

    if remember_geometry_key:
        remember_window_geometry(win, remember_geometry_key, width, height)
    else:
        center_window(win, width, height)

    win.transient(parent)
    win.lift()
    win.focus()

    try:
        win.attributes("-topmost", True)
        win.after(250, lambda: win.attributes("-topmost", False))
    except Exception:
        pass


def show_psexec_error_dialog(parent, host: str, error: PsExecQueryError):
    dialog = ModalDialog(
        parent,
        "Falha no PsExec",
        heading=error.summary,
        heading_wraplength=560,
        message=error.hint,
        wraplength=560,
        message_pady=(0, 10),
    )

    code_text = "" if error.returncode is None else f"  •  Código: {error.returncode}"
    ctk.CTkLabel(
        dialog.box,
        text=f"Host: {host}{code_text}",
        font=FONT_SMALL,
        text_color=THEME["muted"],
        justify="left",
        anchor="w",
    ).pack(fill="x", padx=18, pady=(0, 12))

    details_frame = ctk.CTkFrame(dialog.box, fg_color="transparent")
    details_box = ctk.CTkTextbox(
        details_frame,
        width=560,
        height=180,
        font=("Consolas", 11),
        fg_color=THEME["bg"],
        text_color=THEME["text"],
        corner_radius=10,
        wrap="word",
    )
    details_box.pack(fill="both", expand=True)
    details_box.insert("1.0", error.details or "Sem detalhes adicionais.")
    details_box.configure(state="disabled")

    details_visible = {"value": False}

    def toggle_details():
        if details_visible["value"]:
            details_frame.pack_forget()
            details_button.configure(text="Detalhes")
            details_visible["value"] = False
        else:
            # Insert above the button row, which is already packed.
            details_frame.pack(
                fill="both", expand=True, padx=18, pady=(0, 14), before=dialog.buttons
            )
            details_button.configure(text="Ocultar detalhes")
            details_visible["value"] = True
        fit_dialog_to_content(dialog.win, parent, width=640, min_height=245)

    dialog.add_buttons([
        {"text": "Fechar", "command": dialog.close,
         "style": "primary", "width": 110, "height": 38},
    ])

    details_button = ctk.CTkButton(
        dialog.buttons,
        text="Detalhes",
        width=130,
        height=38,
        command=toggle_details,
        font=FONT_BOLD,
        fg_color=THEME["surface_3"],
        hover_color=THEME["accent_soft"],
        text_color=THEME["secondary_button_text"],
    )
    details_button.pack(side="left")

    dialog.show(width=640, min_height=245)


class IndeterminateProgressWindow(ctk.CTkToplevel):
    """Shared shell for the indeterminate progress dialogs.

    Replaces three near-identical classes. Every visual difference that existed
    between them is a parameter here, so behaviour is unchanged per caller.
    """

    def __init__(
        self,
        parent,
        *,
        title: str,
        heading: str,
        description: str,
        footer: str | None = None,
        width: int = 430,
        height: int = 190,
        wraplength: int = 360,
        modal: bool = False,
        bring_to_front: bool = False,
    ):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.configure(fg_color=THEME["bg"])

        box = ctk.CTkFrame(self, fg_color=THEME["surface"], corner_radius=18)
        box.pack(fill="both", expand=True, padx=18, pady=18)

        ctk.CTkLabel(
            box,
            text=heading,
            font=FONT_SUBTITLE,
            text_color=THEME["text"],
        ).pack(anchor="w", padx=18, pady=(18, 8))

        ctk.CTkLabel(
            box,
            text=description,
            font=FONT_NORMAL,
            text_color=THEME["muted"],
            wraplength=wraplength,
            justify="left",
        ).pack(anchor="w", padx=18, pady=(0, 14))

        self.progress = ctk.CTkProgressBar(box, mode="indeterminate")
        self.progress.pack(fill="x", padx=18, pady=(0, 14 if footer else 18))
        self.progress.start()

        if footer:
            ctk.CTkLabel(
                box,
                text=footer,
                font=FONT_SMALL,
                text_color=THEME["muted"],
            ).pack(anchor="w", padx=18, pady=(0, 18))

        center_window(self, width, height)
        self.transient(parent)

        if modal:
            self.grab_set()
        else:
            self.lift()
            self.focus()

        if bring_to_front:
            try:
                self.attributes("-topmost", True)
                self.after(250, lambda: self.attributes("-topmost", False))
            except Exception:
                pass

    def close(self):
        try:
            self.progress.stop()
        except Exception:
            pass
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


class QwinstaProgressWindow(IndeterminateProgressWindow):
    def __init__(self, parent, label: str, host_count: int):
        super().__init__(
            parent,
            title="Consultando usuários",
            heading="Consultando usuários logados",
            description=f"Executando qwinsta em {host_count} host(s): {label}",
            footer="Aguarde. A janela de resultado abrirá automaticamente.",
            bring_to_front=True,
        )


class PrinterProgressWindow(IndeterminateProgressWindow):
    def __init__(self, parent, host: str):
        super().__init__(
            parent,
            title="Consultando impressoras",
            heading="Consultando impressoras",
            description=f"Verificando impressoras locais e de rede em: {host}",
            footer="Aguarde. O resultado abrirá automaticamente.",
            bring_to_front=True,
        )


class CredsWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Credenciais UltraVNC")
        self.geometry("500x390")
        self.resizable(False, False)
        self.configure(fg_color=THEME["bg"])

        user, pwd = load_creds()
        box = ctk.CTkFrame(self, fg_color=THEME["surface"], corner_radius=18)
        box.pack(fill="both", expand=True, padx=18, pady=18)

        ctk.CTkLabel(box, text="Credenciais UltraVNC", font=FONT_SUBTITLE, text_color=THEME["text"]).pack(anchor="w", padx=18, pady=(18, 8))
        ctk.CTkLabel(box, text="Salvas somente para o seu usuário do Windows.", font=FONT_NORMAL, text_color=THEME["muted"]).pack(anchor="w", padx=18, pady=(0, 18))

        ctk.CTkLabel(box, text="Usuário", font=FONT_NORMAL, text_color=THEME["muted"]).pack(anchor="w", padx=18, pady=(0, 6))
        self.user_entry = ctk.CTkEntry(
            box,
            height=36,
            fg_color=THEME["surface_2"],
            border_color=THEME["border"],
            text_color=THEME["text"],
            placeholder_text_color=THEME["muted"],
        )
        self.user_entry.pack(fill="x", padx=18, pady=(0, 14))
        self.user_entry.insert(0, user)

        ctk.CTkLabel(box, text="Senha", font=FONT_NORMAL, text_color=THEME["muted"]).pack(anchor="w", padx=18, pady=(0, 6))
        self.pwd_entry = ctk.CTkEntry(
            box,
            height=36,
            show="*",
            fg_color=THEME["surface_2"],
            border_color=THEME["border"],
            text_color=THEME["text"],
            placeholder_text_color=THEME["muted"],
        )
        self.pwd_entry.pack(fill="x", padx=18, pady=(0, 18))
        self.pwd_entry.insert(0, pwd)

        buttons = ctk.CTkFrame(box, fg_color="transparent")
        buttons.pack(fill="x", padx=18, pady=(8, 18))
        ctk.CTkButton(
            buttons,
            font=FONT_BOLD,
            text="Cancelar",
            width=130,
            height=42,
            command=self.destroy,
            fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"],
            text_color=THEME["text"],
        ).pack(side="right", padx=(10, 0))
        ctk.CTkButton(
            buttons,
            font=FONT_BOLD,
            text="Salvar",
            width=130,
            height=42,
            command=self.save,
            fg_color=THEME["accent"],
            hover_color=THEME["accent_hover"],
            text_color=THEME["button_text"],
        ).pack(side="right")

        center_window(self, 500, 390)
        self.transient(parent)
        self.grab_set()
        self.user_entry.focus_set()

    def save(self):
        try:
            save_creds(self.user_entry.get().strip(), self.pwd_entry.get())
            audit_log("CREDS_SAVED", "user_saved=true")
            self.destroy()
        except Exception as e:
            log_exception(e)
            show_error(self, "Erro", f"Falha ao salvar credenciais:\n{e}")


class SimpleListEditor(ctk.CTkToplevel):
    def __init__(self, parent, title, items, on_change=None):
        super().__init__(parent)
        self.parent = parent
        self.items = items
        self.on_change = on_change
        self.selected_index: int | None = None
        self.title(title)
        self.geometry("520x520")
        self.minsize(460, 460)
        self.configure(fg_color=THEME["bg"])

        outer = ctk.CTkFrame(self, fg_color=THEME["surface"], corner_radius=18)
        outer.pack(fill="both", expand=True, padx=18, pady=18)

        ctk.CTkLabel(outer, text=title, font=FONT_SUBTITLE, text_color=THEME["text"]).pack(anchor="w", padx=18, pady=(18, 12))

        self.list_frame = ctk.CTkScrollableFrame(outer, fg_color=THEME["bg"], corner_radius=14)
        self.list_frame.pack(fill="both", expand=True, padx=18, pady=(0, 14))

        actions = ctk.CTkFrame(outer, fg_color="transparent")
        actions.pack(fill="x", padx=18, pady=(0, 18))

        for text, cmd in [
            ("↑", self.move_up),
            ("↓", self.move_down),
            ("Adicionar", self.add_item),
            ("Renomear", self.rename_item),
            ("Remover", self.remove_item),
            ("A-Z", self.sort_items),
        ]:
            ctk.CTkButton(actions, text_color=THEME["secondary_button_text"], font=FONT_BOLD, text=text, command=cmd, width=70, fg_color=THEME["surface_3"], hover_color=THEME["accent_soft"]).pack(side="left", padx=(0, 8))

        ctk.CTkButton(actions, text_color=THEME["button_text"], font=FONT_BOLD, text="Fechar", command=self.destroy, width=80, fg_color=THEME["accent"], hover_color=THEME["accent_hover"]).pack(side="right")

        self.render_items()
        remember_window_geometry(self, f"window_list_editor_{safe_filename(title)}", 520, 520)
        self.transient(parent)
        self.grab_set()

    def get_item_name(self, item):
        return item.get("name", "")

    def set_item_name(self, item, name):
        item["name"] = name

    def notify(self, action, **kwargs):
        if self.on_change:
            self.on_change(action, **kwargs)

    def render_items(self):
        for child in self.list_frame.winfo_children():
            child.destroy()

        for idx, item in enumerate(self.items):
            selected = idx == self.selected_index
            row = ctk.CTkButton(
                self.list_frame,
                font=FONT_BOLD,
                text=self.get_item_name(item),
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
                command=lambda i=idx: self.select(i),
            )
            row.pack(fill="x", padx=8, pady=5)

    def select(self, idx):
        self.selected_index = idx
        self.render_items()

    def current_item(self):
        if self.selected_index is None or self.selected_index < 0 or self.selected_index >= len(self.items):
            return None
        return self.items[self.selected_index]

    def add_item(self):
        # Every subclass defines the prompt and the dict shape it appends, and
        # SimpleListEditor is never instantiated directly.
        raise NotImplementedError

    def rename_item(self):
        item = self.current_item()
        if not item:
            return
        old_name = self.get_item_name(item)
        new_name = ask_text(self, "Renomear", "Novo nome:", old_name)
        if not new_name or new_name == old_name:
            return
        self.set_item_name(item, new_name)
        self.notify("rename", old_name=old_name, new_name=new_name, item=item)
        self.render_items()

    def remove_item(self):
        item = self.current_item()
        idx = self.selected_index
        if not item or idx is None:
            return
        name = self.get_item_name(item)
        if not confirm_action(self, "Remover item", f'Remover "{name}" da lista?'):
            return
        del self.items[idx]
        self.selected_index = min(idx, len(self.items) - 1) if self.items else None
        self.notify("remove", name=name)
        self.render_items()

    def move_up(self):
        idx = self.selected_index
        if idx is None or idx <= 0:
            return
        self.items[idx - 1], self.items[idx] = self.items[idx], self.items[idx - 1]
        self.selected_index = idx - 1
        self.notify("move", direction="up")
        self.render_items()

    def move_down(self):
        idx = self.selected_index
        if idx is None or idx >= len(self.items) - 1:
            return
        self.items[idx + 1], self.items[idx] = self.items[idx], self.items[idx + 1]
        self.selected_index = idx + 1
        self.notify("move", direction="down")
        self.render_items()

    def sort_items(self):
        self.items.sort(key=lambda x: self.get_item_name(x).lower())
        self.selected_index = None
        self.notify("sort")
        self.render_items()


class UnitsWindow(SimpleListEditor):
    def add_item(self):
        name = ask_text(self, "Adicionar unidade", "Nome da unidade:")
        if not name:
            return
        self.items.append({"name": name, "sectors": [{"name": "Geral", "hosts": []}]})
        self.selected_index = len(self.items) - 1
        self.notify("add", name=name)
        self.render_items()


class SectorsWindow(SimpleListEditor):
    def add_item(self):
        name = ask_text(self, "Adicionar setor", "Nome do setor:")
        if not name:
            return
        self.items.append({"name": name, "hosts": []})
        self.selected_index = len(self.items) - 1
        self.notify("add", name=name)
        self.render_items()


class HostUnitsConfigWindow(ctk.CTkToplevel):
    def __init__(self, parent, hosts_data, on_save, hosts_path=SHARED_HOSTS_JSON):
        super().__init__(parent)
        self.parent = parent
        self.data = normalize_hosts_data(json.loads(json.dumps(hosts_data)))
        self._initial_snapshot = self._snapshot()
        self._on_save = on_save
        self._hosts_path = Path(hosts_path)
        self.selected_unit = tk.StringVar(value=(get_unit_names(self.data) or ["Geral"])[0])
        self.selected_sector = tk.StringVar(value=(get_sector_names(self.data, self.selected_unit.get()) or ["Geral"])[0])
        self.selected_host_index: int | None = None

        self.title("Hosts e Setores")
        self.geometry("1060x660")
        self.minsize(950, 600)
        self.configure(fg_color=THEME["bg"])
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.left = ctk.CTkFrame(self, width=270, fg_color=THEME["surface"], corner_radius=18)
        self.left.grid(row=0, column=0, sticky="ns", padx=(18, 12), pady=18)
        self.left.grid_propagate(False)

        self.right = ctk.CTkFrame(self, fg_color=THEME["surface"], corner_radius=18)
        self.right.grid(row=0, column=1, sticky="nsew", padx=(0, 18), pady=18)
        self.right.grid_columnconfigure(0, weight=1)
        self.right.grid_rowconfigure(3, weight=1)

        self.build_left_panel()
        self.build_right_panel()
        self.refresh_all()
        remember_window_geometry(self, "window_hosts_config", 1060, 660)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _snapshot(self) -> str:
        """Return a stable serialized copy so we can detect unsaved changes."""
        return json.dumps(normalize_hosts_data(self.data), ensure_ascii=False, sort_keys=True)

    def has_unsaved_changes(self) -> bool:
        return self._snapshot() != self._initial_snapshot

    def close(self):
        save_window_geometry(self, "window_hosts_config")
        if self.has_unsaved_changes():
            should_close = confirm_action(
                self,
                "Alterações não salvas",
                "Há alterações que ainda não foram salvas.\n\nDeseja fechar sem salvar?"
            )
            if not should_close:
                return
            self._audit("CLOSE_WITH_UNSAVED_CHANGES")
        self.destroy()

    def _audit(self, action: str, details: str = ""):
        audit_log(action, f"file={self._hosts_path}; unidade={self.selected_unit.get()}; setor={self.selected_sector.get()}; {details}")

    def build_left_panel(self):
        ctk.CTkLabel(self.left, text="Lista de Hosts", font=FONT_SUBTITLE, text_color=THEME["text"]).pack(anchor="w", padx=18, pady=(20, 14))

        ctk.CTkLabel(self.left, text="Unidade", font=FONT_SMALL_BOLD, text_color=THEME["muted"]).pack(anchor="w", padx=18, pady=(0, 6))
        self.unit_menu = ctk.CTkOptionMenu(
            self.left,
            font=FONT_BOLD,
            values=get_unit_names(self.data) or ["Geral"],
            variable=self.selected_unit,
            command=lambda _v: self.on_unit_changed(),
            fg_color=THEME["surface_3"],
            button_color=THEME["accent_soft"],
            button_hover_color=THEME["accent_hover"],
            text_color=THEME["secondary_button_text"],
            dropdown_fg_color=THEME["surface"],
            dropdown_hover_color=THEME["accent_soft"],
            dropdown_text_color=THEME["text"],
        )
        self.unit_menu.pack(fill="x", padx=18, pady=(0, 12))

        ctk.CTkButton(
            self.left,
            font=FONT_BOLD,
            text="Editar Unidades",
            command=self.open_units_editor,
            fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"],
        ).pack(fill="x", padx=18, pady=(0, 18))

        ctk.CTkLabel(self.left, text="Setores", font=FONT_SMALL_BOLD, text_color=THEME["muted"]).pack(anchor="w", padx=18, pady=(0, 6))
        self.sector_frame = ctk.CTkScrollableFrame(self.left, fg_color=THEME["bg"], corner_radius=14)
        self.sector_frame.pack(fill="both", expand=True, padx=18, pady=(0, 14))

        ctk.CTkButton(
            self.left,
            font=FONT_BOLD,
            text="Editar Setores",
            command=self.open_sectors_editor,
            fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"],
        ).pack(fill="x", padx=18, pady=(0, 18))

    def build_right_panel(self):
        header = ctk.CTkFrame(self.right, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=22, pady=(18, 8))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(header, text="Hosts do Setor", font=FONT_SUBTITLE, text_color=THEME["text"]).grid(row=0, column=0, sticky="w")
        self.path_label = ctk.CTkLabel(header, text="", font=FONT_SMALL, text_color=THEME["muted"])
        self.path_label.grid(row=1, column=0, sticky="w", pady=(2, 0))

        toolbar = ctk.CTkFrame(self.right, fg_color=THEME["surface_2"], corner_radius=14)
        toolbar.grid(row=1, column=0, sticky="ew", padx=22, pady=(0, 10))

        actions = [
            ("+ Adicionar", self.add_host, THEME["accent"], 118),
            ("Editar", self.edit_host, THEME["surface_3"], 92),
            ("Remover", self.remove_host, THEME["surface_3"], 92),
            ("↑", self.move_host_up, THEME["surface_3"], 46),
            ("↓", self.move_host_down, THEME["surface_3"], 46),
            ("Ordenar A-Z", self.sort_hosts, THEME["surface_3"], 118),
        ]

        for idx, (label, command, color, width) in enumerate(actions):
            ctk.CTkButton(
                toolbar,
                font=FONT_BOLD,
                text=label,
                width=width,
                height=34,
                command=command,
                fg_color=color,
                hover_color=THEME["accent_hover"] if color == THEME["accent"] else THEME["accent_soft"],
                text_color=THEME["button_text"] if color == THEME["accent"] else THEME["secondary_button_text"],
            ).pack(side="left", padx=(10 if idx == 0 else 4, 4), pady=9)

        table_header = ctk.CTkFrame(self.right, fg_color=THEME["surface_2"], corner_radius=12)
        table_header.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 6))
        table_header.grid_columnconfigure(0, weight=3, uniform="host_table")
        table_header.grid_columnconfigure(1, weight=3, uniform="host_table")
        table_header.grid_columnconfigure(2, weight=1, uniform="host_table")

        for col, label in enumerate(("Nome", "Host/IP", "Viewer")):
            ctk.CTkLabel(
                table_header,
                text=label,
                font=FONT_SMALL_BOLD,
                text_color=THEME["muted"],
                anchor="w" if col < 2 else "center",
            ).grid(row=0, column=col, sticky="ew", padx=16, pady=8)

        self.host_rows = ctk.CTkScrollableFrame(
            self.right,
            fg_color=THEME["bg"],
            corner_radius=14,
            scrollbar_button_color=THEME["surface_3"],
            scrollbar_button_hover_color=THEME["accent_soft"],
        )
        self.host_rows.grid(row=3, column=0, sticky="nsew", padx=22, pady=(0, 10))

        footer = ctk.CTkFrame(self.right, fg_color="transparent")
        footer.grid(row=4, column=0, sticky="ew", padx=22, pady=(0, 16))

        ctk.CTkButton(
            footer,
            font=FONT_BOLD,
            text="Fechar",
            width=118,
            height=38,
            command=self.close,
            fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"],
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            footer,
            font=FONT_BOLD,
            text="Salvar",
            width=118,
            height=38,
            command=self.save,
            fg_color=THEME["accent"],
            hover_color=THEME["accent_hover"],
            text_color=THEME["button_text"],
        ).pack(side="right")

    def current_unit(self):
        unit = get_unit_by_name(self.data, self.selected_unit.get())
        if not unit:
            units = self.data.setdefault("units", [])
            if not units:
                units.append({"name": "Geral", "sectors": [{"name": "Geral", "hosts": []}]})
            unit = units[0]
            self.selected_unit.set(unit.get("name", "Geral"))
        return unit

    def current_sector(self):
        unit = self.current_unit()
        sectors = unit.setdefault("sectors", [])
        sector = get_sector_by_name(self.data, self.selected_unit.get(), self.selected_sector.get())
        if not sector:
            if not sectors:
                sectors.append({"name": "Geral", "hosts": []})
            sector = sectors[0]
            self.selected_sector.set(sector.get("name", "Geral"))
        return sector

    def current_hosts(self):
        return self.current_sector().setdefault("hosts", [])

    def refresh_all(self):
        self.refresh_units()
        self.refresh_sectors()
        self.render_hosts()

    def refresh_units(self):
        names = get_unit_names(self.data) or ["Geral"]
        if self.selected_unit.get() not in names:
            self.selected_unit.set(names[0])
        self.unit_menu.configure(values=names)
        self.unit_menu.set(self.selected_unit.get())

    def refresh_sectors(self):
        for child in self.sector_frame.winfo_children():
            child.destroy()

        names = get_sector_names(self.data, self.selected_unit.get()) or ["Geral"]
        if self.selected_sector.get() not in names:
            self.selected_sector.set(names[0])

        for name in names:
            selected = name == self.selected_sector.get()
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
                command=lambda n=name: self.select_sector(n),
            )
            btn.pack(fill="x", padx=8, pady=5)

    def render_hosts(self):
        for child in self.host_rows.winfo_children():
            child.destroy()

        self.host_row_widgets = {}

        self.path_label.configure(text=f"{self.selected_unit.get()} > {self.selected_sector.get()}")
        hosts = self.current_hosts()

        if not hosts:
            ctk.CTkLabel(
                self.host_rows,
                text="Nenhum host neste setor.",
                font=FONT_NORMAL,
                text_color=THEME["muted"],
            ).pack(anchor="w", padx=16, pady=16)
            return

        for idx, item in enumerate(hosts):
            selected = idx == self.selected_host_index
            bg = THEME["accent_soft"] if selected else THEME["surface_2"]

            row = ctk.CTkFrame(self.host_rows, fg_color=bg, corner_radius=10, height=36)
            self.host_row_widgets[idx] = row
            row.pack(fill="x", padx=8, pady=3)
            row.pack_propagate(False)
            row.grid_columnconfigure(0, weight=3, uniform="host_table")
            row.grid_columnconfigure(1, weight=3, uniform="host_table")
            row.grid_columnconfigure(2, weight=1, uniform="host_table")

            values = [
                str(item.get("name") or ""),
                format_host_port(item.get("host"), sanitize_port(item.get("port"))),
                viewer_display_name(item.get("viewer")),
            ]

            for col, value in enumerate(values):
                label = ctk.CTkLabel(
                    row,
                    text=value,
                    font=("Segoe UI", 12),
                    text_color=THEME["text"],
                    anchor="w" if col < 2 else "center",
                )
                label.grid(row=0, column=col, sticky="ew", padx=14, pady=7)
                label.bind("<Button-1>", lambda _e, i=idx: self.select_host(i))
                label.bind("<Double-Button-1>", lambda _e, i=idx: self.edit_host_index(i))

            row.bind("<Button-1>", lambda _e, i=idx: self.select_host(i))
            row.bind("<Double-Button-1>", lambda _e, i=idx: self.edit_host_index(i))

    def select_sector(self, name):
        self.selected_sector.set(name)
        self.selected_host_index = None
        self.refresh_sectors()
        self.render_hosts()

    def select_host(self, idx):
        self.selected_host_index = idx

        # Update selection colors in place instead of rebuilding the list.
        # Rebuilding on the first click destroyed the widget before Tk could
        # receive the second click, which prevented double-click editing.
        for row_idx, row in getattr(self, "host_row_widgets", {}).items():
            try:
                row.configure(
                    fg_color=THEME["accent_soft"] if row_idx == idx else THEME["surface_2"]
                )
            except Exception:
                pass

    def on_unit_changed(self):
        sectors = get_sector_names(self.data, self.selected_unit.get()) or ["Geral"]
        self.selected_sector.set(sectors[0])
        self.selected_host_index = None
        self.refresh_sectors()
        self.render_hosts()

    def selected_host(self):
        hosts = self.current_hosts()
        idx = self.selected_host_index
        if idx is None or idx < 0 or idx >= len(hosts):
            return None
        return hosts[idx]

    def open_units_editor(self):
        def changed(action: str, **kwargs: Any):
            old_name = str(kwargs.get("old_name") or "")
            new_name = str(kwargs.get("new_name") or "")
            if action == "rename" and new_name and self.selected_unit.get() == old_name:
                self.selected_unit.set(new_name)
            self._audit(f"UNIT_{action.upper()}", "; ".join(f"{k}={v}" for k, v in kwargs.items() if k != "item"))
            self.refresh_all()

        UnitsWindow(self, "Editar Unidades", self.data.setdefault("units", []), on_change=changed)

    def open_sectors_editor(self):
        unit = self.current_unit()

        def changed(action: str, **kwargs: Any):
            if action == "rename":
                old_name = str(kwargs.get("old_name") or "")
                new_name = str(kwargs.get("new_name") or "")
                item = kwargs.get("item")
                hosts = item.get("hosts", []) if isinstance(item, dict) else []
                if new_name and self.selected_sector.get() == old_name:
                    self.selected_sector.set(new_name)
                if old_name and new_name:
                    rename_realvnc_profiles_for_sector(old_name, new_name, hosts, self)
            self._audit(f"SECTOR_{action.upper()}", "; ".join(f"{k}={v}" for k, v in kwargs.items() if k != "item"))
            self.refresh_all()

        SectorsWindow(self, "Editar Setores", unit.setdefault("sectors", []), on_change=changed)

    def add_host(self):
        item = ask_host_details(self, "Adicionar host")
        if not item:
            return
        self.current_hosts().append(item)
        self.selected_host_index = len(self.current_hosts()) - 1
        self._audit("HOST_ADD", f"name={item['name']}; host={item['host']}; viewer={item['viewer']}")
        self.render_hosts()

    def edit_host_index(self, idx):
        self.selected_host_index = idx
        self.edit_host()

    def edit_host(self):
        item = self.selected_host()
        if not item:
            return
        old = dict(item)
        new_item = ask_host_details(self, "Editar host", item)
        if not new_item:
            return

        if sanitize_viewer(old.get("viewer")) == VIEWER_REALVNC:
            rename_realvnc_profile(self.selected_sector.get(), old.get("name", ""), self.selected_sector.get(), new_item.get("name", ""), self)

        item.update(new_item)
        self._audit("HOST_EDIT", f"old_name={old.get('name')}; new_name={item.get('name')}; host={item.get('host')}; viewer={item.get('viewer')}")
        self.render_hosts()

    def remove_host(self):
        item = self.selected_host()
        idx = self.selected_host_index
        if not item or idx is None:
            return
        if not confirm_action(self, "Remover host", f'Remover "{item.get("name")}" deste setor?'):
            return
        hosts = self.current_hosts()
        removed = hosts.pop(idx)
        self._audit("HOST_REMOVE", f"name={removed.get('name')}; host={removed.get('host')}")
        self.selected_host_index = min(idx, len(hosts) - 1) if hosts else None
        self.render_hosts()

    def move_host_up(self):
        idx = self.selected_host_index
        hosts = self.current_hosts()
        if idx is None or idx <= 0:
            return
        hosts[idx - 1], hosts[idx] = hosts[idx], hosts[idx - 1]
        self.selected_host_index = idx - 1
        self._audit("HOST_MOVE", "direction=up")
        self.render_hosts()

    def move_host_down(self):
        idx = self.selected_host_index
        hosts = self.current_hosts()
        if idx is None or idx >= len(hosts) - 1:
            return
        hosts[idx + 1], hosts[idx] = hosts[idx], hosts[idx + 1]
        self.selected_host_index = idx + 1
        self._audit("HOST_MOVE", "direction=down")
        self.render_hosts()

    def sort_hosts(self):
        self.current_hosts().sort(key=lambda x: x.get("name", "").lower())
        self.selected_host_index = None
        self._audit("HOST_SORT", "by=name")
        self.render_hosts()

    def save(self):
        normalized = normalize_hosts_data(self.data)

        try:
            save_json(normalized, self._hosts_path)
        except Exception as exc:
            # Without this the exception died inside a Tk callback: no console in
            # a .pyw, no message, and the window closed as if the save worked.
            log_exception(exc)
            self._audit("LIST_SAVE_ERROR", f"error={exc}")
            show_error(
                self,
                "Salvar lista",
                "Não foi possível salvar a lista de hosts.\n\n"
                f"Arquivo: {self._hosts_path}\n{exc}\n\n"
                "Suas alterações continuam abertas nesta janela.\n\n"
                f"Log: {ERROR_LOG}",
            )
            return

        self._initial_snapshot = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
        self._audit("LIST_SAVE", f"units={len(normalized.get('units', []))}")
        self._on_save(normalized)
        self.destroy()


class ViewerPathsWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.paths = load_global_paths(parent.settings)
        self.title("Viewers VNC")
        self.geometry("720x390")
        self.resizable(False, False)
        self.configure(fg_color=THEME["bg"])

        box = ctk.CTkFrame(self, fg_color=THEME["surface"], corner_radius=18)
        box.pack(fill="both", expand=True, padx=18, pady=18)
        box.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(box, text="Viewers VNC", font=FONT_SUBTITLE, text_color=THEME["text"]).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=18, pady=(18, 6)
        )
        ctk.CTkLabel(
            box,
            text="Defina os executáveis usados neste computador. Vale para todos os usuários.",
            font=FONT_NORMAL,
            text_color=THEME["muted"],
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=18, pady=(0, 18))

        self.ultravnc_var = tk.StringVar(value=str(self.paths.get("ultravnc_exe") or ULTRAVNC_EXE))
        self.realvnc_var = tk.StringVar(value=str(self.paths.get("realvnc_exe") or REALVNC_EXE))

        self._path_row(box, 2, "UltraVNC Viewer", self.ultravnc_var)
        self._path_row(box, 4, "RealVNC Viewer", self.realvnc_var)

        buttons = ctk.CTkFrame(box, fg_color="transparent")
        buttons.grid(row=6, column=0, columnspan=3, sticky="ew", padx=18, pady=(18, 18))

        ctk.CTkButton(
            buttons, font=FONT_BOLD, text="Usar padrões", width=135, height=40,
            command=self.restore_defaults, fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"], text_color=THEME["secondary_button_text"],
        ).pack(side="left")

        ctk.CTkButton(
            buttons, font=FONT_BOLD, text="Cancelar", width=110, height=40,
            command=self.destroy, fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"], text_color=THEME["secondary_button_text"],
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            buttons, font=FONT_BOLD, text="Salvar", width=110, height=40,
            command=self.save, fg_color=THEME["accent"],
            hover_color=THEME["accent_hover"], text_color=THEME["button_text"],
        ).pack(side="right")

        center_window(self, 720, 390)
        self.transient(parent)
        self.grab_set()

    def _path_row(self, parent, row: int, label: str, variable: tk.StringVar):
        ctk.CTkLabel(parent, text=label, font=FONT_SMALL_BOLD, text_color=THEME["muted"]).grid(
            row=row, column=0, columnspan=3, sticky="w", padx=18, pady=(0, 6)
        )
        entry = ctk.CTkEntry(
            parent, textvariable=variable, height=38, fg_color=THEME["surface_2"],
            border_color=THEME["border"], text_color=THEME["text"],
            placeholder_text_color=THEME["muted"],
        )
        entry.grid(row=row + 1, column=0, sticky="ew", padx=(18, 8), pady=(0, 12))
        ctk.CTkButton(
            parent, font=FONT_BOLD, text="Procurar...", width=110, height=38,
            command=lambda v=variable, l=label: self.browse(v, l),
            fg_color=THEME["surface_3"], hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"],
        ).grid(row=row + 1, column=1, sticky="e", padx=(0, 8), pady=(0, 12))

    def browse(self, variable: tk.StringVar, title: str):
        current = variable.get().strip()
        initial_dir = str(Path(current).parent) if current and Path(current).parent.exists() else r"C:\Program Files"
        selected = filedialog.askopenfilename(
            parent=self, title=f"Selecionar {title}", initialdir=initial_dir,
            filetypes=[("Executáveis", "*.exe"), ("Todos os arquivos", "*.*")],
        )
        if selected:
            variable.set(selected)

    def restore_defaults(self):
        self.ultravnc_var.set(ULTRAVNC_EXE)
        self.realvnc_var.set(REALVNC_EXE)

    def save(self):
        paths = load_global_paths(self.parent.settings)
        paths["ultravnc_exe"] = self.ultravnc_var.get().strip() or ULTRAVNC_EXE
        paths["realvnc_exe"] = self.realvnc_var.get().strip() or REALVNC_EXE
        if not save_global_paths(paths):
            show_error(self, "Viewers VNC", "Não foi possível salvar os caminhos globais.")
            return
        audit_log(
            "VIEWER_PATHS_UPDATED",
            f"ultravnc={paths['ultravnc_exe']}; realvnc={paths['realvnc_exe']}",
        )
        self.destroy()


class PsExecPathWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("PsExec")
        self.geometry("680x270")
        self.resizable(False, False)
        self.configure(fg_color=THEME["bg"])

        box = ctk.CTkFrame(self, fg_color=THEME["surface"], corner_radius=18)
        box.pack(fill="both", expand=True, padx=18, pady=18)
        box.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(box, text="PsExec", font=FONT_SUBTITLE, text_color=THEME["text"]).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=18, pady=(18, 6)
        )
        ctk.CTkLabel(
            box,
            text="Defina o PsExec usado neste computador. Vale para todos os usuários.",
            font=FONT_NORMAL, text_color=THEME["muted"],
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=18, pady=(0, 6))
        ctk.CTkLabel(
            box,
            text="Deixe vazio para procurar automaticamente no PATH.",
            font=FONT_SMALL, text_color=THEME["muted"],
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=18, pady=(0, 14))

        self.path_var = tk.StringVar(value=load_psexec_path())
        self.entry = ctk.CTkEntry(
            box, textvariable=self.path_var, height=38, fg_color=THEME["surface_2"],
            border_color=THEME["border"], text_color=THEME["text"],
            placeholder_text="PsExec no PATH", placeholder_text_color=THEME["muted"],
        )
        self.entry.grid(row=3, column=0, sticky="ew", padx=(18, 8), pady=(0, 18))
        ctk.CTkButton(
            box, text="Procurar...", width=110, height=38, command=self.browse, font=FONT_BOLD,
            fg_color=THEME["surface_3"], hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"],
        ).grid(row=3, column=1, sticky="e", padx=(0, 18), pady=(0, 18))

        buttons = ctk.CTkFrame(box, fg_color="transparent")
        buttons.grid(row=4, column=0, columnspan=2, sticky="ew", padx=18, pady=(0, 18))

        ctk.CTkButton(
            buttons, text="Usar PATH", width=110, height=40, command=lambda: self.path_var.set(""),
            font=FONT_BOLD, fg_color=THEME["surface_3"], hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"],
        ).pack(side="left")
        ctk.CTkButton(
            buttons, text="Cancelar", width=110, height=40, command=self.destroy, font=FONT_BOLD,
            fg_color=THEME["surface_3"], hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"],
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            buttons, text="Salvar", width=110, height=40, command=self.save, font=FONT_BOLD,
            fg_color=THEME["accent"], hover_color=THEME["accent_hover"],
            text_color=THEME["button_text"],
        ).pack(side="right")

        center_window(self, 680, 270)
        self.transient(parent)
        self.grab_set()
        self.entry.focus_set()

    def browse(self):
        selected = filedialog.askopenfilename(
            parent=self,
            title="Selecionar PsExec",
            filetypes=(("PsExec", "PsExec*.exe"), ("Executáveis", "*.exe"), ("Todos os arquivos", "*.*")),
        )
        if selected:
            self.path_var.set(selected)

    def save(self):
        value = self.path_var.get().strip().strip('"')
        if value:
            candidate = Path(value).expanduser()
            if not candidate.is_file() or candidate.suffix.casefold() != ".exe":
                show_warning(self, "PsExec", "Selecione PsExec.exe ou PsExec64.exe.")
                return
            value = str(candidate)

        if not save_psexec_path(value):
            show_error(self, "PsExec", "Não foi possível salvar o caminho global.")
            return

        audit_log("PSEXEC_PATH_UPDATED", f"path={value or 'PATH'}")
        self.destroy()


class UpdateCheckProgressWindow(IndeterminateProgressWindow):
    def __init__(self, parent):
        super().__init__(
            parent,
            title="Verificando atualizações",
            heading="Verificando atualizações",
            description="Consultando a release mais recente no GitHub...",
            width=460,
            height=175,
            # The original label had no wraplength; 0 disables wrapping in Tk.
            wraplength=0,
            modal=True,
        )


class UpdateDownloadWindow(ctk.CTkToplevel):
    def __init__(self, parent, version: str):
        super().__init__(parent)
        self.title("Atualizando VNC-Menu")
        self.resizable(False, False)
        self.configure(fg_color=THEME["bg"])

        box = ctk.CTkFrame(self, fg_color=THEME["surface"], corner_radius=18)
        box.pack(fill="both", expand=True, padx=18, pady=18)

        ctk.CTkLabel(
            box,
            text=f"Baixando VNC-Menu {version}",
            font=FONT_SUBTITLE,
            text_color=THEME["text"],
        ).pack(anchor="w", padx=18, pady=(18, 8))

        self.status_label = ctk.CTkLabel(
            box,
            text="Preparando download...",
            font=FONT_NORMAL,
            text_color=THEME["muted"],
        )
        self.status_label.pack(anchor="w", padx=18, pady=(0, 14))

        self.progress = ctk.CTkProgressBar(box)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=18, pady=(0, 18))

        center_window(self, 500, 190)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", lambda: None)

    def update_progress(self, current: int, total: int):
        if total > 0:
            fraction = min(max(current / total, 0), 1)
            self.progress.set(fraction)
            self.status_label.configure(
                text=f"Baixando... {fraction * 100:.0f}%"
            )
        else:
            self.status_label.configure(
                text=f"Baixando... {current / (1024 * 1024):.1f} MB"
            )

    def set_status(self, text: str):
        self.status_label.configure(text=text)

    def close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


class UpdateAvailableWindow(ctk.CTkToplevel):
    def __init__(self, parent, release: dict):
        super().__init__(parent)
        self.parent = parent
        self.release = release
        self.latest_version = normalize_release_version(
            release.get("tag_name", "")
        )

        notes = format_release_notes_for_display(
            str(release.get("body") or "")
        )

        # Size the window from the amount of release-note text instead of using
        # one oversized fixed height. Keep enough room for all footer buttons.
        note_lines = max(len(notes.splitlines()), 1)
        notes_height = min(max(105 + (note_lines * 18), 145), 220)
        window_height = min(max(315 + notes_height, 450), 525)

        self.title("Atualização disponível")
        self.configure(fg_color=THEME["bg"])
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        # Keep a sensible initial size, but let the user resize the window if
        # release notes or display scaling make the automatic size awkward.
        self.resizable(True, True)
        self.minsize(570, 410)
        center_window(self, 660, window_height)

        outer = ctk.CTkFrame(
            self,
            fg_color=THEME["surface"],
            corner_radius=20,
        )
        outer.pack(fill="both", expand=True, padx=14, pady=14)

        header = ctk.CTkFrame(
            outer,
            fg_color="transparent",
        )
        header.pack(fill="x", padx=20, pady=(18, 12))

        ctk.CTkLabel(
            header,
            text="Nova atualização disponível",
            font=("Segoe UI", 20, "bold"),
            text_color=THEME["text"],
        ).pack(anchor="w")

        ctk.CTkLabel(
            header,
            text="Uma versão mais recente do VNC-Menu está pronta para instalação.",
            font=FONT_NORMAL,
            text_color=THEME["muted"],
        ).pack(anchor="w", pady=(4, 0))

        version_card = ctk.CTkFrame(
            outer,
            fg_color=THEME["surface_2"],
            corner_radius=15,
        )
        version_card.pack(fill="x", padx=20, pady=(0, 14))
        version_card.grid_columnconfigure((0, 2), weight=1)

        current_box = ctk.CTkFrame(
            version_card,
            fg_color="transparent",
        )
        current_box.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=(16, 8),
            pady=12,
        )

        ctk.CTkLabel(
            current_box,
            text="VERSÃO INSTALADA",
            font=FONT_SMALL_BOLD,
            text_color=THEME["muted"],
        ).pack(anchor="w")

        ctk.CTkLabel(
            current_box,
            text=APP_VERSION,
            font=("Segoe UI", 19, "bold"),
            text_color=THEME["text"],
        ).pack(anchor="w", pady=(2, 0))

        ctk.CTkLabel(
            version_card,
            text="→",
            font=("Segoe UI", 22, "bold"),
            text_color=THEME["accent_hover"],
        ).grid(row=0, column=1, padx=10)

        new_box = ctk.CTkFrame(
            version_card,
            fg_color="transparent",
        )
        new_box.grid(
            row=0,
            column=2,
            sticky="ew",
            padx=(8, 16),
            pady=12,
        )

        ctk.CTkLabel(
            new_box,
            text="NOVA VERSÃO",
            font=FONT_SMALL_BOLD,
            text_color=THEME["muted"],
        ).pack(anchor="w")

        ctk.CTkLabel(
            new_box,
            text=self.latest_version,
            font=("Segoe UI", 19, "bold"),
            text_color=THEME["accent_hover"],
        ).pack(anchor="w", pady=(2, 0))

        notes_header = ctk.CTkFrame(
            outer,
            fg_color="transparent",
        )
        notes_header.pack(fill="x", padx=20, pady=(0, 7))

        ctk.CTkLabel(
            notes_header,
            text="Notas da versão",
            font=FONT_BOLD,
            text_color=THEME["text"],
        ).pack(side="left")

        release_name = str(release.get("name") or "").strip()
        if release_name:
            ctk.CTkLabel(
                notes_header,
                text=release_name,
                font=FONT_SMALL,
                text_color=THEME["muted"],
            ).pack(side="right")

        notes_box = ctk.CTkTextbox(
            outer,
            height=notes_height,
            font=("Segoe UI", 12),
            fg_color=THEME["bg"],
            text_color=THEME["text"],
            border_width=1,
            border_color=THEME["border"],
            corner_radius=13,
            wrap="word",
            spacing1=3,
            spacing3=3,
        )
        notes_box.pack(
            fill="both",
            expand=True,
            padx=20,
            pady=(0, 14),
        )
        notes_box.insert("1.0", notes)
        notes_box.configure(state="disabled")

        footer = ctk.CTkFrame(
            outer,
            fg_color="transparent",
        )
        footer.pack(fill="x", padx=20, pady=(0, 18))

        # Equal columns keep the four actions aligned at any window width.
        for column in range(4):
            footer.grid_columnconfigure(column, weight=1, uniform="update_actions")

        button_specs = (
            ("Atualizar agora", self.start_update, THEME["accent"], THEME["accent_hover"], THEME["button_text"]),
            ("Ver no GitHub", self.open_release, THEME["surface_3"], THEME["accent_soft"], THEME["secondary_button_text"]),
            ("Ignorar versão", self.skip_version, THEME["surface_3"], THEME["accent_soft"], THEME["secondary_button_text"]),
            ("Agora não", self.destroy, THEME["surface_3"], THEME["accent_soft"], THEME["secondary_button_text"]),
        )

        for column, (text, command, fg_color, hover_color, text_color) in enumerate(button_specs):
            ctk.CTkButton(
                footer,
                text=text,
                font=FONT_BOLD,
                height=38,
                command=command,
                fg_color=fg_color,
                hover_color=hover_color,
                text_color=text_color,
            ).grid(
                row=0,
                column=column,
                sticky="ew",
                padx=(0 if column == 0 else 4, 0 if column == 3 else 4),
            )

        # Do not restore an old saved size for this dialog. Release-note length
        # can vary a lot between versions, so start clean each time and allow
        # manual resizing instead.
        self.transient(parent)
        self.grab_set()
        self.lift()
        self.focus_force()

    def start_update(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
        self.parent.after(
            80,
            lambda: self.parent.download_and_install_update(self.release),
        )

    def open_release(self):
        url = str(
            self.release.get("html_url") or GITHUB_RELEASES_URL
        )
        webbrowser.open_new_tab(url)

    def skip_version(self):
        self.parent.settings["skipped_update_version"] = (
            self.latest_version
        )
        save_settings(self.parent.settings)
        audit_log(
            "UPDATE_VERSION_SKIPPED",
            f"version={self.latest_version}",
        )
        self.destroy()


class OcsConfigWindow(ctk.CTkToplevel):
    """Endereco do console OCS e credencial de acesso.

    O endereco vale para a instalacao inteira (data/paths.json), como os
    viewers e o PsExec. A credencial e por usuario do Windows e vai protegida
    por DPAPI no creds.json, junto da do UltraVNC.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("OCS Inventory")
        self.geometry("620x420")
        self.resizable(False, False)
        self.configure(fg_color=THEME["bg"])
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        box = ctk.CTkFrame(self, fg_color=THEME["surface"], corner_radius=18)
        box.pack(fill="both", expand=True, padx=18, pady=18)
        box.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(box, text="OCS Inventory", font=FONT_SUBTITLE,
                     text_color=THEME["text"]).grid(row=0, column=0, sticky="w",
                                                    padx=18, pady=(18, 4))
        ctk.CTkLabel(
            box,
            text=("Usado para descobrir em quais máquinas um usuário aparece.\n"
                  "O endereço vale para todos deste computador; a senha é só sua."),
            font=FONT_NORMAL, text_color=THEME["muted"], justify="left", anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 14))

        usuario_salvo, senha_salva = load_ocs_creds()
        campos = [
            ("Endereço do servidor", load_ocs_url(), "http://ocs.suaempresa.local", False),
            ("Usuário do console", usuario_salvo, "usuário do OCS", False),
            ("Senha", senha_salva, "senha do OCS", True),
        ]
        self.entries = []
        for indice, (rotulo, valor, dica, secreto) in enumerate(campos):
            ctk.CTkLabel(box, text=rotulo, font=FONT_SMALL_BOLD,
                         text_color=THEME["muted"]).grid(
                row=2 + indice * 2, column=0, sticky="w", padx=18, pady=(8, 2))
            entrada = ctk.CTkEntry(
                box, height=36, font=FONT_NORMAL, placeholder_text=dica,
                placeholder_text_color=THEME["muted"], fg_color=THEME["surface_2"],
                border_color=THEME["border"], text_color=THEME["text"],
                show="•" if secreto else "",
            )
            entrada.grid(row=3 + indice * 2, column=0, sticky="ew", padx=18)
            if valor:
                entrada.insert(0, valor)
            self.entries.append(entrada)

        acoes = ctk.CTkFrame(box, fg_color="transparent")
        acoes.grid(row=9, column=0, sticky="ew", padx=18, pady=(20, 18))
        ctk.CTkButton(acoes, font=FONT_BOLD, text="Salvar", width=120, height=38,
                      command=self.save, fg_color=THEME["accent"],
                      hover_color=THEME["accent_hover"],
                      text_color=THEME["button_text"]).pack(side="right")
        ctk.CTkButton(acoes, font=FONT_BOLD, text="Cancelar", width=110, height=38,
                      command=self.destroy, fg_color=THEME["surface_3"],
                      hover_color=THEME["accent_soft"],
                      text_color=THEME["secondary_button_text"]).pack(side="right", padx=(0, 8))

        center_window(self, 620, 420)
        self.transient(parent)
        self.grab_set()
        self.focus_force()

    def save(self):
        url = self.entries[0].get().strip()
        usuario = self.entries[1].get().strip()
        senha = self.entries[2].get()

        if not save_ocs_url(url):
            show_error(self, "OCS Inventory",
                       "Não foi possível salvar o endereço em data\\paths.json.")
            return
        try:
            save_ocs_creds(usuario, senha)
        except Exception as exc:
            log_exception(exc)
            show_error(self, "OCS Inventory",
                       f"Não foi possível salvar a credencial:\n{exc}")
            return

        # A senha nunca vai para o log.
        audit_log("OCS_CONFIG_SAVED", f"url={url}; usuario={usuario}")
        self.destroy()


class HostActionsWindow(ctk.CTkToplevel):
    """Um host digitado a mao, com as acoes do app reunidas num lugar.

    Substitui o antigo botao que alternava entre conectar e reiniciar. O host
    fica editavel no topo e cada acao age sobre ele, entao da para conectar,
    reiniciar, ver sessoes e impressoras sem reabrir a janela. E tambem onde a
    limpeza de perfis vai entrar depois, por isso vale mante-la organizada.

    Nao e modal: chama de volta o App (self.parent) para cada acao, do mesmo
    jeito que a janela do OCS faz, e nao segura grab nenhum.
    """

    def __init__(self, parent, initial_host=""):
        super().__init__(parent)
        self.parent = parent
        self.title("Host manual")
        self.configure(fg_color=THEME["bg"])
        self.resizable(False, False)
        center_window(self, 460, 384)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        box = ctk.CTkFrame(self, fg_color=THEME["surface"], corner_radius=18)
        box.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(box, text="Host manual", font=FONT_SUBTITLE,
                     text_color=THEME["text"]).pack(anchor="w", padx=18, pady=(18, 2))
        ctk.CTkLabel(
            box,
            text="Digite o hostname ou IP e escolha a ação. Aceita host::porta.",
            font=FONT_NORMAL, text_color=THEME["muted"],
            wraplength=400, justify="left",
        ).pack(anchor="w", padx=18, pady=(0, 14))

        self.host_var = tk.StringVar(value=str(initial_host or ""))
        self.entry = ctk.CTkEntry(
            box, textvariable=self.host_var, height=38, font=FONT_NORMAL,
            placeholder_text="hostname ou IP", placeholder_text_color=THEME["muted"],
            fg_color=THEME["surface_2"], border_color=THEME["border"],
            text_color=THEME["text"])
        self.entry.pack(fill="x", padx=18, pady=(0, 12))
        self.entry.bind("<Return>", lambda _e: self.do_connect())

        ctk.CTkLabel(box, text="Viewer", font=FONT_SMALL_BOLD,
                     text_color=THEME["muted"]).pack(anchor="w", padx=18, pady=(0, 4))
        self.viewer_var = tk.StringVar(value=DEFAULT_VIEWER)
        ctk.CTkOptionMenu(
            box, font=FONT_BOLD, values=VIEWER_OPTIONS, variable=self.viewer_var,
            width=180, fg_color=THEME["surface_3"], button_color=THEME["accent_soft"],
            button_hover_color=THEME["accent_hover"], text_color=THEME["secondary_button_text"],
            dropdown_fg_color=THEME["surface"], dropdown_hover_color=THEME["accent_soft"],
            dropdown_text_color=THEME["text"],
        ).pack(anchor="w", padx=18, pady=(0, 16))

        acoes = ctk.CTkFrame(box, fg_color="transparent")
        acoes.pack(fill="x", padx=18, pady=(0, 12))
        acoes.grid_columnconfigure(0, weight=1, uniform="hostacoes")
        acoes.grid_columnconfigure(1, weight=1, uniform="hostacoes")

        self.btn_connect = ctk.CTkButton(
            acoes, font=FONT_BOLD, text="Conectar", height=40, command=self.do_connect,
            fg_color=THEME["accent"], hover_color=THEME["accent_hover"],
            text_color=THEME["button_text"])
        self.btn_restart = ctk.CTkButton(
            acoes, font=FONT_BOLD, text="Reiniciar", height=40, command=self.do_restart,
            fg_color=THEME["warning"], hover_color=THEME["warning_hover"],
            text_color=THEME["button_text"])
        self.btn_sessions = ctk.CTkButton(
            acoes, font=FONT_BOLD, text="Sessões", height=40, command=self.do_sessions,
            fg_color=THEME["surface_3"], hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"])
        self.btn_printers = ctk.CTkButton(
            acoes, font=FONT_BOLD, text="Impressoras", height=40, command=self.do_printers,
            fg_color=THEME["surface_3"], hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"])

        self.btn_connect.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=(0, 8))
        self.btn_restart.grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=(0, 8))
        self.btn_sessions.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        self.btn_printers.grid(row=1, column=1, sticky="ew", padx=(6, 0))

        ctk.CTkButton(
            box, font=FONT_BOLD, text="Fechar", height=36, width=110, command=self.destroy,
            fg_color=THEME["surface_3"], hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"]).pack(anchor="e", padx=18, pady=(0, 18))

        # Botoes so ligam quando ha um host: agir sobre campo vazio abriria o
        # viewer sem alvo, ou pediria confirmacao de reinicio de coisa nenhuma.
        self.host_var.trace_add("write", lambda *_a: self.update_buttons_state())
        self.update_buttons_state()

        self.transient(parent)
        self.after(120, self.entry.focus_set)

    def current_host(self):
        return self.host_var.get().strip()

    def update_buttons_state(self):
        estado = "normal" if self.current_host() else "disabled"
        for botao in (self.btn_connect, self.btn_restart,
                      self.btn_sessions, self.btn_printers):
            try:
                botao.configure(state=estado)
            except tk.TclError:
                pass

    def do_connect(self):
        bruto = self.current_host()
        if not bruto:
            return
        host, port = split_host_port(bruto)
        self.parent.connect_manual_host(host, self.viewer_var.get(), port)

    def do_restart(self):
        bruto = self.current_host()
        if not bruto:
            return
        host, _port = split_host_port(bruto)
        self.parent.restart_manual_host(host)

    def do_sessions(self):
        bruto = self.current_host()
        if not bruto:
            return
        host, _port = split_host_port(bruto)
        self.parent.show_host_sessions(host, host)

    def do_printers(self):
        bruto = self.current_host()
        if not bruto:
            return
        host, _port = split_host_port(bruto)
        self.parent.show_remote_printers(host, host)


class OcsSearchWindow(ctk.CTkToplevel):
    """Em quais maquinas um usuario aparece, segundo o inventario do OCS.

    O dado NAO e ao vivo: o OCS guarda o usuario da ultima coleta do agente.
    Por isso cada linha mostra a data do inventario e as antigas ficam
    marcadas. Sem isso alguem tenta conectar numa maquina que nao reporta ha
    um ano achando que a informacao vale.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self._buscando = False
        self._conferindo = False
        self._maquinas = []
        self._conferido_em = None
        # Linhas ja desenhadas e o recuo atual do cabecalho. Ver align_header().
        self._linhas = []
        self._header_pad = None

        self.title("Buscar máquinas por usuário")
        self.configure(fg_color=THEME["bg"])
        self.resizable(True, True)
        # 740 e o minimo em que a coluna do nome ainda cabe: as colunas fixas
        # somam 476px com os espacamentos, e um nome tipo W04-554-045901
        # precisa de ~180px. Abaixo disso o nome comecava a ser cortado.
        # Com a coluna da sessao ao vivo as fixas somam ~622px com os
        # espacamentos, e o nome ainda precisa de ~180px.
        self.minsize(905, 430)
        center_window(self, OCS_WINDOW_WIDTH, OCS_WINDOW_HEIGHT)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        outer = ctk.CTkFrame(self, fg_color=THEME["surface"], corner_radius=20)
        outer.pack(fill="both", expand=True, padx=14, pady=14)
        self.corpo = outer

        ctk.CTkLabel(outer, text="Buscar máquinas por usuário",
                     font=("Segoe UI", 20, "bold"),
                     text_color=THEME["text"]).pack(anchor="w", padx=20, pady=(18, 2))
        ctk.CTkLabel(
            outer,
            text="Inventário do OCS, de toda a empresa. Não é a sessão atual da máquina.",
            font=FONT_NORMAL, text_color=THEME["muted"],
        ).pack(anchor="w", padx=20, pady=(0, 12))

        linha = ctk.CTkFrame(outer, fg_color="transparent")
        linha.pack(fill="x", padx=20, pady=(0, 10))
        linha.grid_columnconfigure(0, weight=1)

        self.entry = ctk.CTkEntry(
            linha, height=38, font=FONT_NORMAL,
            placeholder_text="nome de usuário, por exemplo nome.sobrenome",
            placeholder_text_color=THEME["muted"], fg_color=THEME["surface_2"],
            border_color=THEME["border"], text_color=THEME["text"],
        )
        self.entry.grid(row=0, column=0, sticky="ew")
        self.entry.bind("<Return>", lambda _e: self.start_search())

        self.btn = ctk.CTkButton(
            linha, font=FONT_BOLD, text="Buscar", width=110, height=38,
            command=self.start_search, fg_color=THEME["accent"],
            hover_color=THEME["accent_hover"], text_color=THEME["button_text"])
        self.btn.grid(row=0, column=1, padx=(8, 0))

        self.status = ctk.CTkLabel(outer, text="", font=FONT_SMALL,
                                   text_color=THEME["muted"], anchor="w", justify="left")
        self.status.pack(fill="x", padx=20, pady=(0, 8))

        # O rodape e empacotado ANTES da lista, com side="bottom". No pack do
        # Tk quem tem expand=True fica com o espaco que sobra, e ao encolher a
        # janela os widgets empacotados DEPOIS dele sao os primeiros a sumir.
        # Era por isso que os botoes desapareciam ao reduzir a janela. Reservar
        # a faixa de baixo primeiro garante que eles fiquem sempre visiveis e
        # que quem encolhe e a lista, que ja tem rolagem.
        rodape = ctk.CTkFrame(outer, fg_color="transparent")
        rodape.pack(side="bottom", fill="x", padx=20, pady=(0, 18))
        ctk.CTkButton(rodape, font=FONT_BOLD, text="Fechar", width=110, height=38,
                      command=self.destroy, fg_color=THEME["accent"],
                      hover_color=THEME["accent_hover"],
                      text_color=THEME["button_text"]).pack(side="right")
        ctk.CTkButton(rodape, font=FONT_BOLD, text="Configurar OCS", width=150, height=38,
                      command=self.open_config, fg_color=THEME["surface_3"],
                      hover_color=THEME["accent_soft"],
                      text_color=THEME["secondary_button_text"]).pack(side="left")

        # Sob demanda, nao automatico: sao um ping e um qwinsta por maquina,
        # e disparar isso a cada busca castigaria a rede sem necessidade.
        self.btn_conferir = ctk.CTkButton(
            rodape, font=FONT_BOLD, text="Confirmar sessões", width=170, height=38,
            command=self.start_session_check, fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"], text_color=THEME["secondary_button_text"])
        self.btn_conferir.pack(side="left", padx=(8, 0))
        self.btn_conferir.configure(state="disabled")

        # Sem isto, a coluna vazia da sessao e ambigua entre "ninguem logado"
        # e "ninguem conferiu ainda", que sao coisas bem diferentes.
        self.sessao_label = ctk.CTkLabel(rodape, text="", font=FONT_SMALL,
                                         text_color=THEME["muted"], anchor="w")
        self.sessao_label.pack(side="left", padx=(12, 0))

        self.btn_detalhes = ctk.CTkButton(
            rodape, font=FONT_BOLD, text="Detalhes", width=100, height=38,
            command=self.show_session_details, fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"], text_color=THEME["secondary_button_text"])

        # Cabecalho fora da area rolavel, para nao subir junto com as linhas.
        # Usa as MESMAS constantes de largura que build_row, senao desalinha.
        # O recuo lateral inicial e so um chute razoavel: quem acerta a coluna
        # e align_header(), depois que existe uma linha para medir.
        cabecalho = ctk.CTkFrame(outer, fg_color="transparent", height=22)
        cabecalho.pack(fill="x", padx=28, pady=(0, 2))
        cabecalho.pack_propagate(False)
        self.cabecalho = cabecalho

        def coluna(texto, largura, lado="right", pad=(8, 8)):
            ctk.CTkLabel(cabecalho, text=texto, font=FONT_SMALL_BOLD,
                         text_color=THEME["muted"], width=largura,
                         anchor="w").pack(side=lado, padx=pad)

        coluna("UNIDADE", OCS_COL_TAG, pad=(8, 14))
        coluna("IDADE", OCS_COL_AGE)
        coluna("ÚLTIMO INVENTÁRIO", OCS_COL_DATE)
        coluna("LOGADO AGORA", OCS_COL_SESSION)
        coluna("IP", OCS_COL_IP)
        ctk.CTkLabel(cabecalho, text="MÁQUINA", font=FONT_SMALL_BOLD,
                     text_color=THEME["muted"], anchor="w").pack(
            side="left", fill="x", expand=True, padx=(14, 8))

        self.lista = ctk.CTkScrollableFrame(outer, fg_color=THEME["bg"], corner_radius=16)
        self.lista.pack(fill="both", expand=True, padx=20, pady=(0, 14))
        # Redimensionar a janela pode fazer a barra de rolagem aparecer ou
        # sumir, e isso sozinho ja move a borda direita das linhas.
        self.lista.bind("<Configure>", lambda _e: self.align_header())

        self.transient(parent)
        self.after(120, self.entry.focus_set)
        self.show_message("Digite um usuário e clique em Buscar.")

    # ------------------------------------------------------------------ ui

    def clear_list(self):
        for filho in self.lista.winfo_children():
            filho.destroy()
        self._linhas = []

    def align_header(self):
        """Encosta o cabecalho nas linhas, medindo uma linha de verdade.

        As linhas ficam dentro do CTkScrollableFrame, que tem recuo proprio e
        ainda perde largura para a barra de rolagem quando ela aparece; o
        cabecalho fica fora dele. Somar esses recuos na mao nao resolve: o
        recuo interno e detalhe privado do customtkinter, que nao esta preso a
        uma versao no requirements.txt, e a barra de rolagem desalinharia
        mesmo com o numero certo, porque aparece e some conforme o resultado.
        Medir a linha cobre os dois casos e nao depende de versao.
        """
        if not self._linhas:
            return
        referencia = self._linhas[0]
        try:
            if not (referencia.winfo_exists() and self.corpo.winfo_exists()):
                return
            self.update_idletasks()
            base_x = self.corpo.winfo_rootx()
            base_w = self.corpo.winfo_width()
            linha_x = referencia.winfo_rootx()
            linha_w = referencia.winfo_width()
        except tk.TclError:
            return

        esquerda = linha_x - base_x
        direita = (base_x + base_w) - (linha_x + linha_w)
        # Janela ainda nao desenhada: as medidas vem como 1x1 e produziriam um
        # recuo negativo, que o Tk recusa.
        if esquerda < 0 or direita < 0:
            return

        novo = (esquerda, direita)
        if novo == self._header_pad:
            return
        self._header_pad = novo
        try:
            self.cabecalho.pack_configure(padx=novo)
        except tk.TclError:
            pass

    def show_message(self, texto, cor=None):
        self.clear_list()
        ctk.CTkLabel(self.lista, text=texto, font=FONT_NORMAL,
                     text_color=cor or THEME["muted"], justify="left",
                     anchor="w", wraplength=760).pack(anchor="w", padx=16, pady=16)

    def open_config(self):
        # Mesma troca de grab do Sobre: sem soltar, a filha abriria atras.
        try:
            self.grab_release()
        except Exception:
            pass
        OcsConfigWindow(self)

    # --------------------------------------------------------------- busca

    def start_search(self):
        if self._buscando:
            return
        termo = self.entry.get().strip()
        if not termo:
            self.show_message("Digite um nome de usuário para buscar.")
            return

        url = load_ocs_url()
        usuario, senha = load_ocs_creds()
        if not url or not usuario:
            self.show_message(
                "O OCS ainda não está configurado.\n\n"
                "Clique em Configurar OCS e informe o endereço do servidor "
                "e a sua credencial do console.",
                THEME["warning_hover"],
            )
            return

        # Busca nova invalida a conferencia anterior: manter "verificadas as
        # 14:32" ao lado de resultados de OUTRA pessoa seria mentira.
        self._conferido_em = None
        self._maquinas = []
        self.update_session_label()

        self._buscando = True
        self.btn.configure(state="disabled", text="Buscando...")
        self.status.configure(text="")
        self.show_message(f"Consultando o OCS por {termo}...")

        def worker():
            try:
                resultado = search_machines_by_user(url, usuario, senha, termo)
                erro = None
            except OcsError as exc:
                resultado, erro = None, exc
            except Exception as exc:
                log_exception(exc)
                resultado, erro = None, OcsError(f"Falha inesperada ao consultar o OCS:\n{exc}")

            def finish():
                self._buscando = False
                try:
                    self.btn.configure(state="normal", text="Buscar")
                except tk.TclError:
                    # A janela foi fechada enquanto a consulta corria.
                    return
                if erro is not None:
                    self.show_message(str(erro), THEME["warning_hover"])
                    self.status.configure(text="")
                    return
                self.render(termo, resultado or {})

            try:
                self.after(0, finish)
            except tk.TclError:
                pass

        threading.Thread(target=worker, name="VNC-Menu-OCS", daemon=True).start()

    def render(self, termo, resultado):
        maquinas = resultado.get("machines") or []
        self._maquinas = maquinas
        self._resultado = resultado
        self._termo = termo
        self.update_session_label()
        try:
            self.btn_conferir.configure(state="normal" if maquinas else "disabled")
        except tk.TclError:
            pass
        self.clear_list()

        if not maquinas:
            self.show_message(
                f'Nenhuma máquina encontrada para "{termo}".\n\n'
                "O OCS registra o usuário da última coleta do agente, então "
                "quem nunca fez login numa máquina inventariada não aparece."
            )
            self.status.configure(text="")
            return

        antigas = count_stale(maquinas)
        partes = [f"{len(maquinas)} máquina(s)"]
        if antigas:
            partes.append(f"{antigas} com inventário de mais de {OCS_STALE_DAYS} dias")
        if resultado.get("truncated"):
            partes.append(
                f"mostrando só as primeiras de {resultado.get('total')}, refine a busca"
            )

        divergentes = sum(1 for m in maquinas if m.get("session_status") == SESSION_DIFFERENT)
        confirmadas = sum(1 for m in maquinas if m.get("session_status") == SESSION_SAME)
        if confirmadas:
            partes.append(f"{confirmadas} confirmada(s) agora")
        if divergentes:
            partes.append(f"{divergentes} com OUTRO usuário logado agora")
        naoverificadas = sum(
            1 for m in maquinas
            if m.get("session_status") in (SESSION_ERROR, SESSION_OFFLINE)
        )
        if naoverificadas:
            partes.append(f"{naoverificadas} não foi possível verificar")
        self.status.configure(text="   ·   ".join(partes))

        for maquina in maquinas:
            self.build_row(maquina)

        # A lista anterior podia estar rolada; sem isto uma busca com poucos
        # resultados abre fora da area visivel e parece vazia.
        reset_scrollable_frame_position(self.lista)

        # Duas vezes de proposito. A primeira acerta o caso comum; a segunda
        # cobre a barra de rolagem, que o customtkinter mostra ou esconde num
        # callback proprio, depois que este metodo ja voltou. align_header()
        # so mexe no layout quando o valor muda, entao a segunda chamada nao
        # custa nada quando a primeira ja acertou.
        self.align_header()
        self.after(60, self.align_header)

    def update_session_label(self):
        try:
            if self._conferido_em is None:
                self.sessao_label.configure(text="Sessões sem confirmação",
                                            text_color=THEME["muted"])
                self.btn_detalhes.pack_forget()
                return
            self.sessao_label.configure(
                text=f"Sessões verificadas em {self._conferido_em.strftime('%d/%m/%y %H:%M')}",
                text_color=THEME["muted"])
            if any(m.get("session_status") in (SESSION_ERROR, SESSION_OFFLINE)
                   for m in self._maquinas):
                self.btn_detalhes.pack(side="left", padx=(8, 0))
            else:
                self.btn_detalhes.pack_forget()
        except tk.TclError:
            pass

    def show_session_details(self):
        """Mostra o texto CRU que o qwinsta devolveu para cada maquina.

        A coluna so cabe "erro". O motivo real, que e o que permite agir,
        aparece aqui: acesso negado, nome nao resolvido, tempo esgotado.
        Reaproveita o mesmo formatador da tela de Usuarios.
        """
        linhas = [
            (m.get("name") or "?", m.get("session_live") or "(não verificado)")
            for m in self._maquinas
        ]
        show_text_window(self, "Detalhe das sessões", format_users_output(linhas),
                         remember_geometry_key=None)

    def start_session_check(self):
        """Roda ping + qwinsta nas maquinas achadas para saber quem esta nelas agora.

        O OCS so sabe quem estava logado na ULTIMA coleta do agente, que pode
        ser de meses atras. Esta conferencia e o que transforma um palpite
        velho numa resposta de agora.
        """
        if self._conferindo or not self._maquinas:
            return

        alvos = [
            {"name": m.get("name") or "?", "host": connection_target(m)}
            for m in self._maquinas
        ]

        self._conferindo = True
        self.btn_conferir.configure(state="disabled", text="Confirmando...")

        def worker():
            try:
                linhas = query_logged_users_raw(alvos)
                erro = None
            except Exception as exc:
                log_exception(exc)
                linhas, erro = [], exc

            def finish():
                self._conferindo = False
                try:
                    self.btn_conferir.configure(state="normal", text="Confirmar sessões")
                except tk.TclError:
                    return
                if erro is not None:
                    show_error(self, "Confirmar sessões",
                               f"Falha ao consultar as sessões:\n{erro}")
                    return
                # pool.map preserva a ordem de entrada, entao zip alinha certo.
                for maquina, (_nome, resultado) in zip(self._maquinas, linhas):
                    maquina["session_live"] = resultado
                    maquina["session_status"] = session_status(maquina.get("user"), resultado)
                self._conferido_em = datetime.now()
                audit_log(
                    "OCS_SESSION_CHECK",
                    f"maquinas={len(self._maquinas)}; "
                    f"divergentes={sum(1 for m in self._maquinas if m.get('session_status') == SESSION_DIFFERENT)}",
                )
                self.render(getattr(self, "_termo", ""), getattr(self, "_resultado", {}))

            try:
                self.after(0, finish)
            except tk.TclError:
                pass

        threading.Thread(target=worker, name="VNC-Menu-OCS-Sessao", daemon=True).start()

    def session_color(self, estado):
        if estado == SESSION_DIFFERENT:
            return THEME["accent_hover"]
        if estado == SESSION_ERROR:
            return THEME["warning_hover"]
        return THEME["muted"]

    def build_row(self, maquina):
        velha = is_stale(maquina)
        nome = maquina.get("name") or "?"
        alvo = connection_target(maquina)

        row = ctk.CTkFrame(self.lista, fg_color=THEME["surface_2"],
                           corner_radius=12, height=46)
        row.pack(fill="x", padx=8, pady=4)
        row.pack_propagate(False)
        # align_header() mede a primeira linha para achar o recuo do cabecalho.
        self._linhas.append(row)

        tag = ctk.CTkLabel(
            row, text=(maquina.get("tag") or "-")[:12], font=FONT_SMALL_BOLD,
            text_color=THEME["secondary_button_text"], fg_color=THEME["surface_3"],
            corner_radius=999, width=OCS_COL_TAG, anchor="center")
        tag.pack(side="right", padx=(8, 14), pady=8)

        # Idade separada da data: e ela que impede alguem de confiar num
        # registro de um ano atras, entao fica curta e sempre visivel.
        idade = ctk.CTkLabel(
            row, text=self.format_age(maquina), font=("Segoe UI", 12, "bold"),
            text_color=THEME["warning_hover"] if velha else THEME["muted"],
            width=OCS_COL_AGE, anchor="w")
        idade.pack(side="right", padx=(8, 8))

        data = ctk.CTkLabel(
            row, text=self.format_date(maquina), font=("Segoe UI", 12),
            text_color=THEME["warning_hover"] if velha else THEME["muted"],
            width=OCS_COL_DATE, anchor="w")
        data.pack(side="right", padx=(8, 8))

        estado = maquina.get("session_status")
        sessao = ctk.CTkLabel(
            row, text=format_session(maquina.get("session_live")),
            font=("Segoe UI", 12, "bold") if estado == SESSION_DIFFERENT else ("Segoe UI", 12),
            text_color=self.session_color(estado), width=OCS_COL_SESSION, anchor="w")
        sessao.pack(side="right", padx=(8, 8))

        endereco = ctk.CTkLabel(row, text=(maquina.get("ip") or "sem IP"),
                                font=("Segoe UI", 12), text_color=THEME["muted"],
                                width=OCS_COL_IP, anchor="w")
        endereco.pack(side="right", padx=(8, 8))

        etiqueta = ctk.CTkLabel(
            row, text=nome if len(nome) <= 40 else nome[:39] + "…",
            font=("Segoe UI", 13, "bold"),
            text_color=THEME["muted"] if velha else THEME["text"], anchor="w")
        etiqueta.pack(side="left", fill="x", expand=True, padx=(14, 8))

        def clicar(_event=None):
            if not alvo:
                show_warning(self, "OCS", f'"{nome}" não tem IP nem nome utilizável.')
                return
            # sector="" de proposito: estas maquinas nao estao no hosts.json,
            # entao nao existe perfil RealVNC <Setor>_<Nome>.vnc para elas.
            self.parent.run_host_action(nome, alvo, DEFAULT_VIEWER, None, sector="")

        def menu(event):
            if alvo:
                self.parent.show_host_context_menu(event, alvo, nome, None)

        bind_clickable_row(row, (etiqueta, endereco, sessao, data, idade, tag), clicar, menu,
                           THEME["surface_2"], THEME["accent_soft"])

    @staticmethod
    def format_date(maquina):
        """Data curta, sempre com ano: um registro de 448 dias sem ano engana."""
        bruto = str(maquina.get("lastdate") or "").strip()
        if not bruto:
            return "sem data"
        try:
            quando = datetime.strptime(bruto, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return bruto[:16]
        return quando.strftime("%d/%m/%y %H:%M")

    @staticmethod
    def format_age(maquina):
        """Idade curta, para caber ao lado da data sem empurrar o nome."""
        idade = maquina.get("age_days")
        if not isinstance(idade, int):
            return ""
        if idade == 0:
            return "hoje"
        if idade == 1:
            return "1 dia"
        return f"{idade} d"


class ChangelogWindow(ctk.CTkToplevel):
    """Notas da ultima versao publicada, dentro do aplicativo.

    Existe porque a janela de atualizacao so aparece quando HA atualizacao:
    depois de instalar, nao ha mais como reler o que mudou. Reaproveita o
    mesmo formatador e o mesmo estilo de caixa de texto usados la.

    A consulta ao GitHub roda em thread separada. A janela abre na hora, em
    estado de carregando, para nao travar a interface enquanto a rede
    responde.
    """

    def __init__(self, parent, on_close=None):
        super().__init__(parent)
        self.parent = parent
        self._on_close = on_close

        self.title("Changelog")
        self.configure(fg_color=THEME["bg"])
        self.resizable(True, True)
        self.minsize(520, 380)
        center_window(self, 660, 470)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        outer = ctk.CTkFrame(self, fg_color=THEME["surface"], corner_radius=20)
        outer.pack(fill="both", expand=True, padx=14, pady=14)

        header = ctk.CTkFrame(outer, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(18, 12))

        ctk.CTkLabel(
            header,
            text="Changelog",
            font=("Segoe UI", 20, "bold"),
            text_color=THEME["text"],
        ).pack(anchor="w")

        self.subtitle = ctk.CTkLabel(
            header,
            text=f"Versão instalada: {APP_VERSION}",
            font=FONT_NORMAL,
            text_color=THEME["muted"],
        )
        self.subtitle.pack(anchor="w", pady=(4, 0))

        notes_header = ctk.CTkFrame(outer, fg_color="transparent")
        notes_header.pack(fill="x", padx=20, pady=(0, 7))

        ctk.CTkLabel(
            notes_header,
            text="Notas da versão",
            font=FONT_BOLD,
            text_color=THEME["text"],
        ).pack(side="left")

        self.release_label = ctk.CTkLabel(
            notes_header,
            text="",
            font=FONT_SMALL,
            text_color=THEME["muted"],
        )
        self.release_label.pack(side="right")

        # Mesmo estilo da caixa da janela de atualizacao, de proposito.
        self.notes_box = ctk.CTkTextbox(
            outer,
            font=("Segoe UI", 12),
            fg_color=THEME["bg"],
            text_color=THEME["text"],
            border_width=1,
            border_color=THEME["border"],
            corner_radius=13,
            wrap="word",
            spacing1=3,
            spacing3=3,
        )
        self.notes_box.pack(fill="both", expand=True, padx=20, pady=(0, 14))
        self.set_notes("Carregando as notas da última versão...")

        footer = ctk.CTkFrame(outer, fg_color="transparent")
        footer.pack(fill="x", padx=20, pady=(0, 18))

        self.retry_button = ctk.CTkButton(
            footer,
            font=FONT_BOLD,
            text="Tentar de novo",
            width=145,
            height=38,
            command=self.load_async,
            fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"],
        )
        # So aparece se a consulta falhar.
        self.retry_button.pack_forget()

        ctk.CTkButton(
            footer,
            font=FONT_BOLD,
            text="Fechar",
            width=110,
            height=38,
            command=self.destroy,
            fg_color=THEME["accent"],
            hover_color=THEME["accent_hover"],
            text_color=THEME["button_text"],
        ).pack(side="right")

        # Quem abre esta janela e o Sobre, que e modal (grab_set). Sem tomar o
        # grab aqui, esta janela aparece ATRAS do Sobre e nao aceita clique
        # nenhum. O Sobre solta o grab antes de abrir e retoma no on_close.
        self.transient(parent)
        self.grab_set()
        self.lift()
        self.focus_force()

        self.load_async()

    def destroy(self):
        """Avisa quem abriu, uma unica vez, mesmo se fechar pelo X."""
        callback = self._on_close
        self._on_close = None
        try:
            super().destroy()
        finally:
            if callback is not None:
                try:
                    callback()
                except Exception:
                    pass

    def set_notes(self, texto: str):
        """Troca o conteudo da caixa, que fica sempre somente leitura."""
        try:
            self.notes_box.configure(state="normal")
            self.notes_box.delete("1.0", "end")
            self.notes_box.insert("1.0", texto)
            self.notes_box.configure(state="disabled")
        except tk.TclError:
            # A janela foi fechada no meio da atualizacao do texto.
            pass

    def load_async(self):
        self.retry_button.pack_forget()
        self.set_notes("Carregando as notas da última versão...")

        def worker():
            try:
                release = fetch_latest_release()
                erro = None
            except Exception as exc:
                release = None
                erro = exc

            def finish():
                if erro is not None:
                    log_exception(erro)
                    self.show_error_state(erro)
                    return
                self.show_release(release or {})

            # after() so vale enquanto a janela existir.
            try:
                self.after(0, finish)
            except tk.TclError:
                pass

        threading.Thread(target=worker, name="VNC-Menu-Changelog", daemon=True).start()

    def show_release(self, release: dict):
        versao = normalize_release_version(str(release.get("tag_name") or ""))
        nome = str(release.get("name") or "").strip()
        corpo = format_release_notes_for_display(str(release.get("body") or "")).strip()

        try:
            if versao:
                self.subtitle.configure(
                    text=f"Versão instalada: {APP_VERSION}    ·    Última publicada: {versao}"
                )
            self.release_label.configure(text=nome or (f"v{versao}" if versao else ""))
        except tk.TclError:
            return

        # Sem tratamento de corpo vazio aqui: format_release_notes_for_display()
        # ja devolve a propria mensagem quando a release nao tem notas, e e a
        # mesma que a janela de atualizacao mostra.
        self.set_notes(corpo)
        audit_log("CHANGELOG_VIEWED", f"versao_publicada={versao or '-'}")

    def show_error_state(self, erro: Exception):
        self.set_notes(
            "Não foi possível carregar as notas da última versão.\n\n"
            f"{erro}\n\n"
            "Verifique a conexão com a internet. Se a rede exigir proxy, o "
            "acesso ao GitHub precisa estar liberado.\n\n"
            f"O histórico também fica em:\n{GITHUB_RELEASES_URL}"
        )
        try:
            self.retry_button.pack(side="left")
        except tk.TclError:
            pass


class AboutWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent

        self.title(f"Sobre o {APP_NAME}")
        # 680 e nao 610: a linha de botoes ganhou o Changelog e nao cabia mais.
        self.geometry("680x430")
        self.resizable(False, False)
        self.configure(fg_color=THEME["bg"])

        outer = ctk.CTkFrame(
            self,
            fg_color=THEME["surface"],
            corner_radius=18,
        )
        outer.pack(fill="both", expand=True, padx=18, pady=18)

        ctk.CTkLabel(
            outer,
            text=APP_NAME,
            font=("Segoe UI", 26, "bold"),
            text_color=THEME["text"],
        ).pack(anchor="w", padx=22, pady=(20, 0))

        ctk.CTkLabel(
            outer,
            text=f"Versão {APP_VERSION}",
            font=FONT_NORMAL,
            text_color=THEME["muted"],
        ).pack(anchor="w", padx=22, pady=(2, 12))

        description = (
            "Centraliza conexões UltraVNC e RealVNC, hosts e ferramentas de suporte "
            "em uma única interface."
        )

        ctk.CTkLabel(
            outer,
            text=description,
            font=FONT_NORMAL,
            text_color=THEME["muted"],
            justify="left",
            anchor="w",
            wraplength=530,
        ).pack(fill="x", padx=22, pady=(0, 14))

        info = ctk.CTkFrame(
            outer,
            fg_color=THEME["surface_2"],
            corner_radius=14,
        )
        info.pack(fill="x", padx=22, pady=(0, 14))
        info.grid_columnconfigure(1, weight=1)

        links = [
            (
                "Desenvolvido por",
                APP_AUTHOR,
                GITHUB_PROFILE_URL,
            ),
            (
                "Repositório",
                "github.com/gabrielmariense/VNC-Menu",
                GITHUB_URL,
            ),
            (
                "Licença",
                "MIT License",
                LICENSE_URL,
            ),
        ]

        for row_index, (label, value, url) in enumerate(links):
            top_pad = 12 if row_index == 0 else 6
            bottom_pad = 12 if row_index == len(links) - 1 else 6

            ctk.CTkLabel(
                info,
                text=label,
                font=FONT_SMALL_BOLD,
                text_color=THEME["muted"],
                anchor="w",
            ).grid(
                row=row_index,
                column=0,
                sticky="w",
                padx=(16, 14),
                pady=(top_pad, bottom_pad),
            )

            ctk.CTkButton(
                info,
                text=value,
                height=28,
                command=lambda target=url: self.open_url(target),
                font=FONT_SMALL_BOLD,
                fg_color="transparent",
                hover_color=THEME["accent_soft"],
                text_color=THEME["accent_hover"],
                anchor="w",
                corner_radius=7,
            ).grid(
                row=row_index,
                column=1,
                sticky="ew",
                padx=(0, 16),
                pady=(top_pad, bottom_pad),
            )

        buttons = ctk.CTkFrame(
            outer,
            fg_color="transparent",
        )
        buttons.pack(fill="x", padx=22, pady=(0, 10))

        ctk.CTkButton(
            buttons,
            font=FONT_BOLD,
            text="Buscar atualização",
            width=170,
            height=38,
            command=self.check_updates,
            fg_color=THEME["accent"],
            hover_color=THEME["accent_hover"],
            text_color=THEME["button_text"],
        ).pack(side="left")

        ctk.CTkButton(
            buttons,
            font=FONT_BOLD,
            text="Changelog",
            width=130,
            height=38,
            command=self.open_changelog,
            fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"],
        ).pack(side="left", padx=(8, 0))

        ctk.CTkButton(
            buttons,
            font=FONT_BOLD,
            text="Pasta de logs",
            width=145,
            height=38,
            command=self.open_logs_folder,
            fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"],
        ).pack(side="left", padx=(8, 0))

        ctk.CTkButton(
            buttons,
            font=FONT_BOLD,
            text="Fechar",
            width=110,
            height=38,
            command=self.destroy,
            fg_color=THEME["accent"],
            hover_color=THEME["accent_hover"],
            text_color=THEME["button_text"],
        ).pack(side="right")

        ctk.CTkLabel(
            outer,
            text=f"© 2026 {APP_AUTHOR}",
            font=FONT_SMALL,
            text_color=THEME["muted"],
        ).pack(anchor="center", pady=(0, 14))

        center_window(self, 680, 430)

        self.transient(parent)
        self.grab_set()
        self.focus_force()

    def check_updates(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
        self.parent.after(80, lambda: self.parent.check_for_updates(manual=True))

    def open_changelog(self):
        """Abre as notas da ultima versao dentro do aplicativo.

        O Sobre e modal. Se ele mantiver o grab, a janela do changelog abre
        atras dele e fica sem receber clique, sem jeito de trazer para frente.
        Entao o grab e passado adiante e retomado quando a filha fecha, o que
        deixa o Sobre aberto e utilizavel de novo em vez de fecha-lo.
        """
        try:
            self.grab_release()
        except Exception:
            pass
        ChangelogWindow(self, on_close=self.retake_grab)

    def retake_grab(self):
        """Devolve a modalidade ao Sobre depois que o changelog fecha."""
        try:
            if self.winfo_exists():
                self.grab_set()
                self.lift()
                self.focus_force()
        except Exception:
            # O proprio Sobre pode ter sido fechado enquanto o changelog
            # estava aberto. Nesse caso nao ha grab para devolver.
            pass

    def open_url(self, url: str):
        try:
            if not webbrowser.open_new_tab(url):
                raise RuntimeError(
                    "O Windows não encontrou um navegador disponível."
                )

            audit_log(
                "ABOUT_LINK_OPENED",
                f"url={url}",
            )
        except Exception as e:
            log_exception(e)
            show_error(
                self,
                "Sobre o VNC-Menu",
                f"Falha ao abrir o link:\n{url}\n\n{e}",
            )

    def open_logs_folder(self):
        try:
            LOGS_DIR.mkdir(
                parents=True,
                exist_ok=True,
            )
            os.startfile(str(LOGS_DIR))

            audit_log(
                "ABOUT_LOGS_FOLDER_OPENED",
                f"path={LOGS_DIR}",
            )
        except Exception as e:
            log_exception(e)
            show_error(
                self,
                "Sobre o VNC-Menu",
                f"Falha ao abrir a pasta de logs:\n{LOGS_DIR}\n\n{e}",
            )


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Configurações")
        self.geometry("540x720")
        self.resizable(False, False)
        self.configure(fg_color=THEME["bg"])
        self._theme_refresh_pending = False
        self._build_content()

        center_window(self, 540, 720)
        self.transient(parent)
        self.grab_set()

    def _build_content(self):
        for child in self.winfo_children():
            child.destroy()

        self.configure(fg_color=THEME["bg"])
        outer = ctk.CTkFrame(self, fg_color=THEME["surface"], corner_radius=18)
        outer.pack(fill="both", expand=True, padx=18, pady=18)

        ctk.CTkLabel(outer, text="Configurações", font=FONT_SUBTITLE, text_color=THEME["text"]).pack(
            anchor="w", padx=18, pady=(16, 4)
        )
        ctk.CTkLabel(
            outer, text="Ajuste o VNC-Menu.", font=FONT_NORMAL, text_color=THEME["muted"]
        ).pack(anchor="w", padx=18, pady=(0, 12))

        content = ctk.CTkScrollableFrame(
            outer, fg_color="transparent", corner_radius=0,
            scrollbar_button_color=THEME["surface_3"],
            scrollbar_button_hover_color=THEME["accent_soft"],
        )
        content.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        config = self._section(content, "CONFIGURAÇÃO")
        self._nav_button(config, "Credenciais UltraVNC", self.parent.open_creds)
        self._nav_button(config, "Hosts e Setores", self.parent.open_config)
        self._nav_button(config, "Selecionar Lista", self.parent.open_hosts_source_config)
        self._nav_button(config, "Colunas da Tela", self.parent.open_host_columns_config, last=True)

        paths = self._section(content, "CAMINHOS")
        self._nav_button(paths, "Viewers VNC", self.parent.open_viewer_paths)
        self._nav_button(paths, "PsExec", self.parent.open_psexec_path)
        self._nav_button(paths, "OCS Inventory", self.parent.open_ocs_config, last=True)

        appearance = self._section(content, "APARÊNCIA")
        self.dark_var = tk.BooleanVar(value=bool(self.parent.dark_mode))
        self._switch_row(
            appearance, "Modo escuro", self.dark_var, self.on_dark_mode_changed
        )

        color_row = ctk.CTkFrame(appearance, fg_color=THEME["surface_2"], corner_radius=10)
        color_row.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(
            color_row, text="Cor do tema", font=FONT_BOLD, text_color=THEME["text"]
        ).pack(side="left", padx=12, pady=9)
        self.color_var = tk.StringVar(value=color_scheme_display_name(self.parent.color_scheme))
        ctk.CTkOptionMenu(
            color_row, values=["Azul", "Roxo"], variable=self.color_var,
            command=self.on_color_scheme_changed, width=105, height=30, font=FONT_BOLD,
            fg_color=THEME["surface_3"], button_color=THEME["accent_soft"],
            button_hover_color=THEME["accent_hover"], text_color=THEME["secondary_button_text"],
            dropdown_fg_color=THEME["surface"], dropdown_hover_color=THEME["accent_soft"],
            dropdown_text_color=THEME["text"],
        ).pack(side="right", padx=10, pady=7)

        system = self._section(content, "SISTEMA")
        self.updates_var = tk.BooleanVar(
            value=bool(self.parent.settings.get("check_updates_on_startup", True))
        )
        self._switch_row(
            system, "Atualizações ao iniciar", self.updates_var, self.on_update_checks_changed, last=True
        )

        other = self._section(content, "OUTROS")
        self._nav_button(other, "Sobre", self.parent.open_about, last=True)

        ctk.CTkButton(
            outer, font=FONT_BOLD, text="Fechar", command=self.destroy,
            fg_color=THEME["accent"], hover_color=THEME["accent_hover"],
            text_color=THEME["button_text"], height=40,
        ).pack(fill="x", padx=18, pady=(4, 16))

    def _section(self, parent, title: str):
        section = ctk.CTkFrame(
            parent, fg_color=THEME["surface_2"], corner_radius=14,
            border_width=1, border_color=THEME["border"],
        )
        section.pack(fill="x", padx=2, pady=(0, 10))
        ctk.CTkLabel(
            section, text=title, font=FONT_SMALL_BOLD, text_color=THEME["muted"]
        ).pack(anchor="w", padx=12, pady=(10, 7))
        return section

    def _nav_button(self, parent, text: str, command, last: bool = False):
        ctk.CTkButton(
            parent, font=FONT_BOLD, text=text, anchor="w",
            command=lambda c=command: self.run_and_close(c), height=36,
            fg_color=THEME["surface_3"], hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"],
        ).pack(fill="x", padx=10, pady=(0, 10 if last else 6))

    def _switch_row(self, parent, text: str, variable: tk.BooleanVar, command, last: bool = False):
        row = ctk.CTkFrame(parent, fg_color=THEME["surface_2"], corner_radius=10)
        row.pack(fill="x", padx=10, pady=(0, 10 if last else 6))
        ctk.CTkLabel(
            row, text=text, font=FONT_BOLD, text_color=THEME["text"]
        ).pack(side="left", padx=12, pady=9)
        ctk.CTkSwitch(
            row, text="", width=44, variable=variable, onvalue=True, offvalue=False,
            command=command, progress_color=THEME["accent"],
            button_color=THEME["text"], button_hover_color=THEME["muted"],
        ).pack(side="right", padx=12, pady=7)

    def on_dark_mode_changed(self):
        enabled = bool(self.dark_var.get())
        if enabled == self.parent.dark_mode:
            return
        self.parent.dark_mode = enabled
        self.parent.settings["dark_mode"] = enabled
        save_settings(self.parent.settings)
        audit_log("DARK_MODE_CHANGED", f"enabled={enabled}")
        self._apply_theme_change_safely()

    def on_color_scheme_changed(self, display_name: str):
        scheme = COLOR_SCHEME_BLUE if display_name == "Azul" else COLOR_SCHEME_PURPLE
        if scheme == self.parent.color_scheme:
            return
        self.parent.color_scheme = scheme
        self.parent.settings["color_scheme"] = scheme
        save_settings(self.parent.settings)
        audit_log("COLOR_SCHEME_CHANGED", f"scheme={scheme}; dark_mode={self.parent.dark_mode}")
        self._apply_theme_change_safely()

    def on_update_checks_changed(self):
        enabled = bool(self.updates_var.get())
        self.parent.settings["check_updates_on_startup"] = enabled
        save_settings(self.parent.settings)
        audit_log("UPDATE_STARTUP_CHECK_CHANGED", f"enabled={enabled}")

    def _apply_theme_change_safely(self):
        """Apply theme changes only after the current widget callback has returned."""
        if self._theme_refresh_pending:
            return
        self._theme_refresh_pending = True
        self.after_idle(self._finish_theme_change)

    def _finish_theme_change(self):
        try:
            self.grab_release()
        except tk.TclError:
            pass

        try:
            self.destroy()
        except tk.TclError:
            pass

        # Repaint only after the settings widget tree has been destroyed.
        # CustomTkinter updates every registered widget when appearance mode changes;
        # doing that while the switch/option menu still exists can deadlock Tcl/Tk.
        self.parent.after_idle(self.parent.apply_theme_repaint_and_reopen_settings)

    def run_and_close(self, command):
        try:
            self.grab_release()
            self.attributes("-alpha", 0.0)
        except tk.TclError:
            pass

        def safe_destroy():
            try:
                if self.winfo_exists():
                    self.destroy()
            except tk.TclError:
                pass

        self.parent.after(100, command)
        self.parent.after(1000, safe_destroy)
