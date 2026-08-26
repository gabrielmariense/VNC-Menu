"""ModalDialog e os dialogos modais da aplicacao.

ModalDialog concentra a moldura comum: frame, titulo, corpo, linha de
botoes, Escape e o botao X. Widgets proprios de cada dialogo vao
direto em dialog.box.
"""

from typing import Any
from pathlib import Path
import customtkinter as ctk
from tkinter import filedialog
import tkinter as tk
import webbrowser

from ..config import PORT, DEFAULT_VIEWER, ERROR_LOG, HOSTS_SOURCE_CUSTOM, HOSTS_SOURCE_EMPTY, HOSTS_SOURCE_SHARED, PSEXEC_DOWNLOAD_URL, USER_HOSTS_JSON, VIEWER_OPTIONS
from ..applog import audit_log, log_exception
from ..storage import sanitize_port, split_host_port, get_hosts_path_for_source, hosts_source_display_name, normalize_hosts_source, sanitize_viewer, save_psexec_path, set_hosts_source, update_hosts_file_setting
from ..theme import FONT_BOLD, FONT_NORMAL, FONT_SMALL, FONT_SUBTITLE, THEME
from ..helpers import center_window, fit_dialog_to_content, modal_window, show_error, show_info, show_warning

DIALOG_BUTTON_STYLES = {
    "primary": ("accent", "accent_hover", "button_text"),
    "secondary": ("surface_3", "accent_soft", "secondary_button_text"),
    "danger": ("danger", "danger_hover", "button_text"),
}


class ModalDialog:
    """Shared chrome for the modal dialogs.

    Each dialog used to repeat the same block: Toplevel, rounded surface frame,
    heading, body text, a right-aligned button row, Escape and close wiring,
    then fit_dialog_to_content() plus modal_window(). Two of them silently
    lacked WM_DELETE_WINDOW, so closing them with the X did nothing.

    Widgets specific to one dialog are packed straight into `self.box`. The
    button row is created on first use so it always packs below them.
    """

    def __init__(
        self,
        parent,
        title: str,
        *,
        heading: str | None = None,
        message: str | None = None,
        wraplength: int = 500,
        message_pady: tuple[int, int] = (0, 18),
        heading_wraplength: int | None = None,
    ):
        self.parent = parent
        self.result = None

        self.win = ctk.CTkToplevel(parent)
        self.win.title(title)
        self.win.resizable(False, False)
        self.win.configure(fg_color=THEME["bg"])

        self.box = ctk.CTkFrame(self.win, fg_color=THEME["surface"], corner_radius=18)
        self.box.pack(fill="both", expand=True, padx=18, pady=18)

        if heading is not None:
            heading_kwargs = {}
            if heading_wraplength is not None:
                heading_kwargs = {
                    "wraplength": heading_wraplength,
                    "justify": "left",
                    "anchor": "w",
                }
            ctk.CTkLabel(
                self.box,
                text=heading,
                font=FONT_SUBTITLE,
                text_color=THEME["text"],
                **heading_kwargs,
            ).pack(anchor="w", padx=18, pady=(18, 8), fill="x" if heading_wraplength else None)

        if message is not None:
            ctk.CTkLabel(
                self.box,
                text=message,
                font=FONT_NORMAL,
                text_color=THEME["muted"],
                justify="left",
                anchor="w",
                wraplength=wraplength,
            ).pack(fill="x", padx=18, pady=message_pady)

        self._buttons = None

    @property
    def buttons(self):
        if self._buttons is None:
            self._buttons = ctk.CTkFrame(self.box, fg_color="transparent")
            self._buttons.pack(fill="x", padx=18, pady=(0, 18))
        return self._buttons

    def add_buttons(self, specs):
        """Create the button row from specs given RIGHT TO LEFT.

        Each spec is a dict with text, command and optional style, width and
        height. Omitted width/height keep the CustomTkinter defaults.
        """
        created = []
        for index, spec in enumerate(specs):
            fg, hover, text_color = DIALOG_BUTTON_STYLES[spec.get("style", "secondary")]
            kwargs = {
                "text": spec["text"],
                "command": spec["command"],
                "font": FONT_BOLD,
                "fg_color": THEME[fg],
                "hover_color": THEME[hover],
                "text_color": THEME[text_color],
            }
            for key in ("width", "height"):
                if spec.get(key) is not None:
                    kwargs[key] = spec[key]

            button = ctk.CTkButton(self.buttons, **kwargs)
            # side="right" packs right to left, so only the leftmost button
            # (the last one created) goes without a left gap.
            button.pack(side="right", padx=(8, 0) if index < len(specs) - 1 else 0)
            created.append(button)
        return created

    def close(self, result=None):
        if result is not None:
            self.result = result
        self.win.destroy()

    def show(
        self,
        *,
        width: int = 560,
        min_height: int = 190,
        on_cancel=None,
        closable: bool = True,
    ):
        cancel = on_cancel if on_cancel is not None else self.close
        self.win.protocol("WM_DELETE_WINDOW", cancel if closable else (lambda: None))
        if closable:
            self.win.bind("<Escape>", lambda _event: cancel())
        fit_dialog_to_content(self.win, self.parent, width=width, min_height=min_height)
        modal_window(self.win, self.parent)
        return self.result


def confirm_action(parent, title, message) -> bool:
    dialog = ModalDialog(parent, title, heading=title, message=message)
    dialog.add_buttons([
        {"text": "Cancelar", "command": dialog.close, "width": 110, "height": 38},
        {"text": "Confirmar", "command": lambda: dialog.close(True),
         "style": "primary", "width": 110, "height": 38},
    ])
    return bool(dialog.show(width=560, min_height=190))


def confirm_empty_list_overwrite(parent) -> bool:
    dialog = ModalDialog(
        parent,
        "Criar lista vazia",
        heading="Substituir sua lista pessoal?",
        message=(
            "Você já possui uma lista personalizada. Criar uma lista vazia vai "
            "substituí-la e remover os hosts salvos nela.\n\n"
            "A lista Padrão não será alterada."
        ),
    )
    dialog.add_buttons([
        {"text": "Cancelar", "command": dialog.close, "width": 110, "height": 38},
        {"text": "Criar vazia", "command": lambda: dialog.close(True),
         "style": "danger", "width": 125, "height": 38},
    ])
    return bool(dialog.show(width=570, min_height=220))


def ask_text(parent: Any, title: str, label: str, initial: str = "") -> str | None:
    dialog = ModalDialog(parent, title, heading=title)

    ctk.CTkLabel(
        dialog.box, text=label, font=FONT_NORMAL, text_color=THEME["muted"],
    ).pack(anchor="w", padx=18, pady=(0, 8))

    entry = ctk.CTkEntry(
        dialog.box,
        width=380,
        height=38,
        fg_color=THEME["surface_2"],
        border_color=THEME["border"],
        text_color=THEME["text"],
        placeholder_text_color=THEME["muted"],
    )
    entry.pack(fill="x", padx=18, pady=(0, 18))
    entry.insert(0, initial or "")
    entry.focus_set()
    entry.select_range(0, tk.END)

    def confirm(_event=None):
        dialog.close(entry.get().strip() or None)

    dialog.add_buttons([
        {"text": "Cancelar", "command": dialog.close},
        {"text": "OK", "command": confirm, "style": "primary"},
    ])
    dialog.win.bind("<Return>", confirm)

    # Fixed size: this dialog is always heading + label + entry + buttons.
    center_window(dialog.win, 460, 235)
    dialog.win.protocol("WM_DELETE_WINDOW", dialog.close)
    dialog.win.bind("<Escape>", lambda _event: dialog.close())
    modal_window(dialog.win, parent)
    return dialog.result


def select_psexec_executable(parent) -> Path | None:
    while True:
        selected = filedialog.askopenfilename(
            parent=parent,
            title="Selecionar PsExec",
            filetypes=(
                ("PsExec", "PsExec*.exe"),
                ("Executáveis", "*.exe"),
                ("Todos os arquivos", "*.*"),
            ),
        )

        if not selected:
            audit_log("PSEXEC_SELECTION_CANCELLED")
            return None

        candidate = Path(selected)
        if candidate.is_file() and candidate.suffix.casefold() == ".exe":
            if not save_psexec_path(candidate):
                show_error(
                    parent,
                    "PsExec",
                    "Não foi possível salvar o caminho global.",
                )
                return None
            audit_log("PSEXEC_SELECTED", f"path={candidate}")
            return candidate

        show_error(parent, "PsExec", "Selecione PsExec.exe ou PsExec64.exe.")


def show_psexec_required_dialog(parent) -> Path | None:
    dialog = ModalDialog(
        parent,
        "PsExec não encontrado",
        heading="PsExec não encontrado",
        message=(
            "O PsExec é necessário para consultar impressoras em computadores remotos. "
            "Selecione PsExec.exe ou PsExec64.exe neste computador.\n\n"
            "Se ele ainda não estiver instalado, abra a página oficial da Microsoft para baixar."
        ),
        wraplength=540,
        message_pady=(0, 20),
    )

    def download_psexec():
        try:
            if not webbrowser.open_new_tab(PSEXEC_DOWNLOAD_URL):
                raise RuntimeError("O Windows não encontrou um navegador disponível.")
            audit_log("PSEXEC_DOWNLOAD_PAGE_OPENED", f"url={PSEXEC_DOWNLOAD_URL}")
        except Exception as exc:
            log_exception(exc)
            show_error(dialog.win, "PsExec", f"Não foi possível abrir a página:\n{exc}")

    def select_executable():
        selected = select_psexec_executable(dialog.win)
        if selected is None:
            return
        dialog.close(selected)

    dialog.add_buttons([
        {"text": "Cancelar", "command": dialog.close, "width": 100, "height": 38},
        {"text": "Selecionar arquivo", "command": select_executable,
         "style": "primary", "width": 145, "height": 38},
        {"text": "Abrir download", "command": download_psexec, "width": 135, "height": 38},
    ])
    return dialog.show(width=620, min_height=245)


def ask_host_details(parent: Any, title: str, initial: dict[str, str] | None = None) -> dict[str, str] | None:
    initial = initial or {}
    # A port stored in the entry wins; otherwise accept one typed into the host.
    initial_host, host_port = split_host_port(initial.get("host", ""))
    initial_port = sanitize_port(initial.get("port"), host_port)
    dialog = ModalDialog(parent, title, heading=title)

    # The fields use grid, so they live in their own frame: box already holds
    # packed widgets and Tk refuses to mix the two managers in one container.
    form = ctk.CTkFrame(dialog.box, fg_color="transparent")
    form.pack(fill="x", padx=0, pady=(8, 0))
    form.grid_columnconfigure(0, weight=1)

    def field_label(text: str, row: int):
        ctk.CTkLabel(form, text=text, font=FONT_NORMAL, text_color=THEME["muted"]).grid(
            row=row, column=0, sticky="w", padx=18, pady=(0, 6)
        )

    def field_entry(row: int, value: str):
        entry = ctk.CTkEntry(
            form,
            width=360,
            height=36,
            fg_color=THEME["surface_2"],
            border_color=THEME["border"],
            text_color=THEME["text"],
            placeholder_text_color=THEME["muted"],
        )
        entry.grid(row=row, column=0, columnspan=2, sticky="ew", padx=18, pady=(0, 14))
        entry.insert(0, value)
        return entry

    field_label("Nome", 0)
    name_entry = field_entry(1, initial.get("name", ""))

    field_label("Host/IP", 2)
    host_entry = field_entry(3, initial_host)

    field_label("Porta", 4)
    port_entry = field_entry(5, "" if initial_port == PORT else str(initial_port))
    port_entry.configure(placeholder_text=f"{PORT} (padrao)")

    field_label("Viewer", 6)
    viewer_var = tk.StringVar(value=sanitize_viewer(initial.get("viewer", DEFAULT_VIEWER)))
    ctk.CTkOptionMenu(
        form,
        font=FONT_BOLD,
        values=VIEWER_OPTIONS,
        variable=viewer_var,
        width=180,
        fg_color=THEME["surface_3"],
        button_color=THEME["accent_soft"],
        button_hover_color=THEME["accent_hover"],
        text_color=THEME["secondary_button_text"],
        dropdown_fg_color=THEME["surface"],
        dropdown_hover_color=THEME["accent_soft"],
        dropdown_text_color=THEME["text"],
    ).grid(row=7, column=0, sticky="w", padx=18, pady=(0, 18))

    def confirm(_event=None):
        name = name_entry.get().strip()
        host, typed_port = split_host_port(host_entry.get())
        if not name or not host:
            show_warning(dialog.win, "Campos obrigatórios", "Preencha Nome e Host/IP.")
            return

        port_text = port_entry.get().strip()
        if port_text:
            if not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
                show_warning(dialog.win, "Porta inválida", "Digite uma porta de 1 a 65535, ou deixe vazio para usar a padrão.")
                return
            port = int(port_text)
        else:
            port = typed_port

        entry = {
            "name": name,
            "host": host,
            "viewer": sanitize_viewer(viewer_var.get()),
        }
        if port != PORT:
            entry["port"] = port
        dialog.close(entry)

    dialog.add_buttons([
        {"text": "Cancelar", "command": dialog.close},
        {"text": "Salvar", "command": confirm, "style": "primary"},
    ])
    dialog.win.bind("<Return>", confirm)

    center_window(dialog.win, 450, 480)
    dialog.win.protocol("WM_DELETE_WINDOW", dialog.close)
    dialog.win.bind("<Escape>", lambda _event: dialog.close())
    name_entry.focus_set()
    modal_window(dialog.win, parent)
    return dialog.result


def ask_custom_connection(parent: Any) -> tuple[str, str, int] | None:
    dialog = ModalDialog(parent, "Conexão manual", heading="Conexão manual")

    ctk.CTkLabel(
        dialog.box,
        text="Digite o hostname ou IP e selecione o viewer.",
        font=FONT_NORMAL,
        text_color=THEME["muted"],
    ).pack(anchor="w", padx=18, pady=(0, 14))

    entry = ctk.CTkEntry(
        dialog.box,
        width=380,
        height=38,
        placeholder_text="hostname ou IP (ou host::5901)",
        fg_color=THEME["surface_2"],
        border_color=THEME["border"],
        text_color=THEME["text"],
        placeholder_text_color=THEME["muted"],
    )
    entry.pack(fill="x", padx=18, pady=(0, 14))
    entry.focus_set()

    viewer_var = tk.StringVar(value=DEFAULT_VIEWER)
    ctk.CTkOptionMenu(
        dialog.box,
        font=FONT_BOLD,
        values=VIEWER_OPTIONS,
        variable=viewer_var,
        width=180,
        fg_color=THEME["surface_3"],
        button_color=THEME["accent_soft"],
        button_hover_color=THEME["accent_hover"],
        text_color=THEME["secondary_button_text"],
        dropdown_fg_color=THEME["surface"],
        dropdown_hover_color=THEME["accent_soft"],
        dropdown_text_color=THEME["text"],
    ).pack(anchor="w", padx=18, pady=(0, 18))

    def confirm(_event=None):
        host, port = split_host_port(entry.get())
        if not host:
            show_warning(dialog.win, "Campo obrigatório", "Digite um hostname ou IP.")
            return
        dialog.close((host, sanitize_viewer(viewer_var.get()), port))

    dialog.add_buttons([
        {"text": "Cancelar", "command": dialog.close},
        {"text": "Conectar", "command": confirm, "style": "primary"},
    ])
    dialog.win.bind("<Return>", confirm)

    center_window(dialog.win, 460, 310)
    dialog.win.protocol("WM_DELETE_WINDOW", dialog.close)
    dialog.win.bind("<Escape>", lambda _event: dialog.close())
    modal_window(dialog.win, parent)
    return dialog.result


def show_realvnc_profile_dialog(parent, profile_path: Path, profile_name: str) -> None:
    dialog = ModalDialog(
        parent,
        "Perfil RealVNC",
        heading="Perfil RealVNC não encontrado",
        message=(
            "Não encontrei o perfil RealVNC deste host.\n\n"
            f"Arquivo esperado:\n{profile_path}\n\n"
            "Você pode criar um arquivo vazio com o nome correto ou copiar o nome "
            "para configurar o perfil manualmente."
        ),
        wraplength=560,
    )

    def create_empty():
        try:
            profile_path.parent.mkdir(parents=True, exist_ok=True)
            profile_path.touch(exist_ok=False)
            audit_log("REALVNC_PROFILE_CREATED_EMPTY", f"file={profile_path}")
            show_info(dialog.win, "RealVNC", f"Arquivo criado:\n{profile_path}")
        except FileExistsError:
            show_info(dialog.win, "RealVNC", f"Arquivo já existe:\n{profile_path}")
        except Exception as e:
            audit_log("REALVNC_PROFILE_CREATE_ERROR", f"file={profile_path}; error={e}")
            show_error(dialog.win, "RealVNC", f"Falha ao criar arquivo:\n{e}")

    def copy_name():
        try:
            dialog.win.clipboard_clear()
            dialog.win.clipboard_append(profile_name)
            show_info(dialog.win, "RealVNC", "Nome copiado para a área de transferência.")
        except Exception as e:
            show_error(dialog.win, "RealVNC", f"Falha ao copiar nome:\n{e}")

    dialog.add_buttons([
        {"text": "Fechar", "command": dialog.close, "width": 100, "height": 38},
        {"text": "Copiar nome", "command": copy_name, "width": 120, "height": 38},
        {"text": "Criar arquivo", "command": create_empty,
         "style": "primary", "width": 120, "height": 38},
    ])
    dialog.show(width=640, min_height=285)


def choose_hosts_source_dialog(parent, required=False) -> str | None:
    dialog = ModalDialog(
        parent,
        "Escolher lista de hosts",
        heading="Escolher lista de hosts",
        message=(
            "Escolha de onde o VNC-Menu deve carregar os hosts neste usuário. "
            "Você pode trocar essa opção depois em Configurações."
        ),
        wraplength=540,
        message_pady=(0, 14),
    )

    def choose(value: str) -> None:
        if value == HOSTS_SOURCE_EMPTY and USER_HOSTS_JSON.exists():
            if not confirm_empty_list_overwrite(dialog.win):
                audit_log("EMPTY_HOSTS_SOURCE_OVERWRITE_CANCELLED", f"file={USER_HOSTS_JSON}")
                return
            audit_log("EMPTY_HOSTS_SOURCE_OVERWRITE_CONFIRMED", f"file={USER_HOSTS_JSON}")
        dialog.close(value)

    def option_row(title: str, description: str, button_text: str, value: str, primary: bool = False):
        row = ctk.CTkFrame(dialog.box, fg_color=THEME["surface_2"], corner_radius=12)
        row.pack(fill="x", padx=18, pady=(0, 8))
        row.grid_columnconfigure(0, weight=1)

        text_frame = ctk.CTkFrame(row, fg_color="transparent")
        text_frame.grid(row=0, column=0, sticky="ew", padx=(14, 10), pady=11)
        ctk.CTkLabel(
            text_frame, text=title, font=FONT_BOLD, text_color=THEME["text"], anchor="w"
        ).pack(anchor="w")
        ctk.CTkLabel(
            text_frame, text=description, font=FONT_SMALL, text_color=THEME["muted"],
            justify="left", anchor="w", wraplength=350,
        ).pack(anchor="w", pady=(2, 0))

        ctk.CTkButton(
            row,
            text=button_text,
            width=125,
            height=36,
            font=FONT_BOLD,
            command=lambda: choose(value),
            fg_color=THEME["accent"] if primary else THEME["surface_3"],
            hover_color=THEME["accent_hover"] if primary else THEME["accent_soft"],
            text_color=THEME["button_text"] if primary else THEME["secondary_button_text"],
        ).grid(row=0, column=1, sticky="e", padx=(0, 12), pady=11)

    option_row(
        "Padrão",
        "Lista compartilhada. Alterações nela podem aparecer para outros usuários.",
        "Usar padrão",
        HOSTS_SOURCE_SHARED,
        primary=True,
    )
    option_row(
        "Personalizada",
        "Sua lista pessoal, salva somente para este usuário.",
        "Usar pessoal",
        HOSTS_SOURCE_CUSTOM,
    )
    option_row(
        "Vazia",
        "Cria uma lista pessoal sem hosts para você montar do zero.",
        "Criar vazia",
        HOSTS_SOURCE_EMPTY,
    )

    if required:
        # No way out: the application cannot start without a list selected.
        ctk.CTkLabel(
            dialog.box, text="Escolha uma opção para continuar.", font=FONT_SMALL,
            text_color=THEME["muted"],
        ).pack(anchor="w", padx=18, pady=(4, 18))
    else:
        footer = ctk.CTkFrame(dialog.box, fg_color="transparent")
        footer.pack(fill="x", padx=18, pady=(4, 18))
        ctk.CTkButton(
            footer, text="Cancelar", width=110, height=38, command=dialog.close,
            font=FONT_BOLD, fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"], text_color=THEME["secondary_button_text"],
        ).pack(side="right")

    return dialog.show(width=640, min_height=360, closable=not required)


def ensure_hosts_source_selected(parent, settings):
    source = normalize_hosts_source(settings.get("hosts_source"))
    if not source:
        source = choose_hosts_source_dialog(parent, required=True) or HOSTS_SOURCE_SHARED
        try:
            set_hosts_source(settings, source, overwrite_user_file=True)
            audit_log("HOSTS_SOURCE_SELECTED", f"source={hosts_source_display_name(source)}; file={settings.get('hosts_file', '')}")
        except Exception as exc:
            # Falling back to the shared list keeps the application usable. The
            # preference stays unset, so the dialog appears again next start.
            log_exception(exc)
            audit_log("HOSTS_SOURCE_SELECT_ERROR", f"source={source}; error={exc}")
            show_error(
                parent,
                "Selecionar Lista",
                "Não foi possível preparar a lista escolhida.\n"
                "O VNC-Menu vai continuar com a lista Padrão desta vez.\n\n"
                f"{exc}\n\nLog: {ERROR_LOG}",
            )
            settings["hosts_source"] = HOSTS_SOURCE_SHARED
            settings["hosts_file"] = str(get_hosts_path_for_source(HOSTS_SOURCE_SHARED))
    else:
        update_hosts_file_setting(settings)
    return normalize_hosts_source(settings.get("hosts_source")) or HOSTS_SOURCE_SHARED


def shared_hosts_edit_warning(parent):
    personal_exists = USER_HOSTS_JSON.exists()
    personal_action = (
        "Você também pode abrir sua lista pessoal e alterar somente a sua configuração."
        if personal_exists
        else "Se preferir, crie uma cópia pessoal antes de editar."
    )

    dialog = ModalDialog(
        parent,
        "Editar lista padrão",
        heading="Esta lista é compartilhada",
        message=(
            "A lista Padrão é usada por outros usuários do VNC-Menu. "
            "Qualquer alteração feita nela pode aparecer para todos que usam essa lista.\n\n"
            f"{personal_action}"
        ),
        wraplength=520,
    )
    dialog.result = "cancel"

    dialog.add_buttons([
        {"text": "Cancelar", "command": lambda: dialog.close("cancel"),
         "width": 110, "height": 38},
        {"text": "Usar pessoal" if personal_exists else "Criar cópia",
         "command": lambda: dialog.close("copy"), "width": 125, "height": 38},
        {"text": "Editar padrão", "command": lambda: dialog.close("continue"),
         "style": "primary", "width": 125, "height": 38},
    ])
    return dialog.show(
        width=610,
        min_height=235,
        on_cancel=lambda: dialog.close("cancel"),
    )
