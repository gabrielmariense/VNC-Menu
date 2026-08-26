"""Janelas maiores.

Editor de hosts e setores, credenciais, caminhos, configuracoes,
sobre, janelas de progresso e a janela de saida de texto.
"""

from typing import Any
from pathlib import Path
import customtkinter as ctk
from tkinter import filedialog
import json
import os
import tkinter as tk
import webbrowser

from ..config import APP_AUTHOR, APP_NAME, APP_VERSION, COLOR_SCHEME_BLUE, COLOR_SCHEME_PURPLE, ERROR_LOG, GITHUB_PROFILE_URL, GITHUB_RELEASES_URL, GITHUB_URL, LICENSE_URL, LOGS_DIR, REALVNC_EXE, SHARED_HOSTS_JSON, ULTRAVNC_EXE, VIEWER_REALVNC
from ..applog import audit_log, log_exception
from ..storage import format_host_port, sanitize_port, get_sector_by_name, get_sector_names, get_unit_by_name, get_unit_names, load_creds, load_global_paths, load_psexec_path, normalize_hosts_data, sanitize_viewer, save_creds, save_global_paths, save_json, save_psexec_path, save_settings, viewer_display_name
from ..theme import FONT_BOLD, FONT_NORMAL, FONT_SMALL, FONT_SMALL_BOLD, FONT_SUBTITLE, THEME, color_scheme_display_name
from ..helpers import center_window, fit_dialog_to_content, remember_window_geometry, rename_realvnc_profile, rename_realvnc_profiles_for_sector, safe_filename, save_window_geometry, show_error, show_warning
from ..updates import format_release_notes_for_display, normalize_release_version
from .dialogs import ModalDialog, ask_host_details, ask_text, confirm_action
from ..remote import PsExecQueryError

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


class AboutWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent

        self.title(f"Sobre o {APP_NAME}")
        self.geometry("610x430")
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

        center_window(self, 610, 430)

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
        self._nav_button(paths, "PsExec", self.parent.open_psexec_path, last=True)

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
