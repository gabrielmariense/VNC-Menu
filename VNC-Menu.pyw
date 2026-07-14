import base64
import getpass
import ctypes
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import traceback
import webbrowser
from ctypes import wintypes
from pathlib import Path
from typing import Any
import tkinter as tk
from tkinter import messagebox, filedialog

import customtkinter as ctk
from pywinauto import Desktop
from pywinauto.keyboard import send_keys


# =========================
# Configuração base
# =========================
ULTRAVNC_EXE = r"C:\Program Files\uvnc bvba\UltraVNC\vncviewer.exe"
REALVNC_EXE = r"C:\Program Files\RealVNC\VNC Viewer\vncviewer.exe"
PORT = 5900

APP_NAME = "VNC-Menu"
APP_VERSION = "1.0"
APP_AUTHOR = 'Gabriel "GMErebos" Mariense'
GITHUB_PROFILE_URL = "https://github.com/gabrielmariense"
GITHUB_URL = "https://github.com/gabrielmariense/VNC-Menu"
LICENSE_URL = "https://github.com/gabrielmariense/VNC-Menu/blob/main/LICENSE"

VIEWER_ULTRAVNC = "ultravnc"
VIEWER_REALVNC = "realvnc"
VIEWER_OPTIONS = [VIEWER_ULTRAVNC, VIEWER_REALVNC]
DEFAULT_VIEWER = VIEWER_ULTRAVNC

AUTH_TIMEOUT = 12
AUTH_TITLE_RE = r".*(UltraVNC|VNC).*(Auth|Authentication).*"

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "_internal" if (SCRIPT_DIR / "_internal").exists() else SCRIPT_DIR
DATA_DIR.mkdir(exist_ok=True)

SHARED_HOSTS_JSON = DATA_DIR / "hosts.json"
TEMPLATE_VNC = DATA_DIR / "template.vnc"
REALVNC_DIR = DATA_DIR / "realvnc"
REALVNC_DIR.mkdir(exist_ok=True)

USER_DATA_DIR = Path.home() / "Documents" / "VNC-Menu"
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

USER_HOSTS_JSON = USER_DATA_DIR / "hosts.json"
CREDS_JSON = USER_DATA_DIR / "creds.json"
SETTINGS_JSON = USER_DATA_DIR / "settings.json"

# Fallback for Windows environments where Documents\VNC-Menu\settings.json
# is blocked by ACLs, OneDrive, antivirus, or a stale read-only file.
_APPDATA_BASE = Path(os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Roaming"))
FALLBACK_USER_DATA_DIR = _APPDATA_BASE / "VNC-Menu"
FALLBACK_SETTINGS_JSON = FALLBACK_USER_DATA_DIR / "settings.json"

try:
    _LOG_USERNAME = getpass.getuser()
except Exception:
    _LOG_USERNAME = "unknown"

_SAFE_LOG_USERNAME = "".join(
    c if c.isalnum() or c in ("-", "_", ".") else "_"
    for c in _LOG_USERNAME
).strip("._") or "unknown"

LOGS_DIR = SCRIPT_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
AUDIT_LOG = LOGS_DIR / f"{_SAFE_LOG_USERNAME}.log"
ERROR_LOG = LOGS_DIR / f"{_SAFE_LOG_USERNAME}_error.log"

DEFAULT_HOSTS = {
    "units": [
        {
            "name": "Geral",
            "sectors": [
                {
                    "name": "Geral",
                    "hosts": [
                        {"name": "Example Host 01", "host": "demo-host.local", "viewer": VIEWER_ULTRAVNC},
                        {"name": "Example Host 02", "host": "192.0.2.10", "viewer": VIEWER_REALVNC},
                    ],
                }
            ],
        }
    ]
}

DEFAULT_SETTINGS = {
    "dark_mode": True,
    "hosts_source": "",
    "hosts_file": "",
    "selected_unit": "Geral",
    "selected_sector": "Geral",
    "host_columns": 3,
    "main_window_size": "980x610",
    "window_geometries": {},
    "ultravnc_exe": ULTRAVNC_EXE,
    "realvnc_exe": REALVNC_EXE,
}

HOSTS_SOURCE_SHARED = "padrao"
HOSTS_SOURCE_CUSTOM = "personalizada"
HOSTS_SOURCE_EMPTY = "vazia"
HOSTS_SOURCE_OPTIONS = {HOSTS_SOURCE_SHARED, HOSTS_SOURCE_CUSTOM, HOSTS_SOURCE_EMPTY}


# =========================
# Tema visual customtkinter
# =========================
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")
ctk.set_widget_scaling(1.0)

DARK_THEME = {
    "bg": "#07111f",
    "surface": "#0b1726",
    "surface_2": "#10243a",
    "surface_3": "#1b3554",
    "border": "#2a4a66",
    "accent": "#2f81f7",
    "accent_hover": "#58a6ff",
    "accent_soft": "#1b4d7a",
    "text": "#f8fbff",
    "muted": "#a9bed5",
    "button_text": "#ffffff",
    "secondary_button_text": "#eaf3ff",
    "danger": "#9b2c2c",
    "danger_hover": "#b83a3a",
    "warning": "#b7791f",
    "warning_hover": "#d69e2e",
}

LIGHT_THEME = {
    "bg": "#c9d8e8",
    "surface": "#f4f8fc",
    "surface_2": "#e3eef8",
    "surface_3": "#4e6e8e",
    "border": "#9ab0c7",
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
    "accent_soft": "#b9d4f0",
    "text": "#0f1b2a",
    "muted": "#40546a",
    "button_text": "#ffffff",
    "secondary_button_text": "#ffffff",
    "danger": "#b42318",
    "danger_hover": "#d92d20",
    "warning": "#b7791f",
    "warning_hover": "#945c12",
}

THEME = DARK_THEME.copy()


def apply_color_theme(dark_mode: bool):
    """Switch the custom color tokens used by all customtkinter widgets."""
    THEME.clear()
    THEME.update(DARK_THEME if dark_mode else LIGHT_THEME)
    ctk.set_appearance_mode("Dark" if dark_mode else "Light")

FONT_TITLE = ("Segoe UI", 24, "bold")
FONT_SUBTITLE = ("Segoe UI", 15, "bold")
FONT_NORMAL = ("Segoe UI", 13)
FONT_BOLD = ("Segoe UI", 13, "bold")
FONT_SMALL = ("Segoe UI", 11)
FONT_SMALL_BOLD = ("Segoe UI", 11, "bold")


# =========================
# Helpers gerais
# =========================
def log_exception(_: Exception | None = None):
    try:
        ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        ERROR_LOG.write_text(traceback.format_exc(), encoding="utf-8")
    except Exception:
        pass


def audit_log(action: str, details: str = ""):
    """Grava uma linha de auditoria por usuário."""
    try:
        username = getpass.getuser()
    except Exception:
        username = "unknown"

    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        clean_action = str(action).strip().replace("\n", " ")
        clean_details = str(details or "").strip().replace("\r", " ").replace("\n", " ")
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] user={username} action={clean_action}")
            if clean_details:
                f.write(f" details={clean_details}")
            f.write("\n")
    except Exception:
        pass


def center_window(win, width: int | None = None, height: int | None = None):
    """Centraliza a janela na tela."""
    win.update_idletasks()
    w = width or max(win.winfo_width(), win.winfo_reqwidth(), 1)
    h = height or max(win.winfo_height(), win.winfo_reqheight(), 1)
    x = max((win.winfo_screenwidth() - w) // 2, 0)
    y = max((win.winfo_screenheight() - h) // 2, 0)
    win.geometry(f"{w}x{h}+{x}+{y}")


_GEOMETRY_RE = re.compile(r"^\d+x\d+[+-]\d+[+-]\d+$")


def is_valid_geometry(value: str) -> bool:
    return bool(_GEOMETRY_RE.match(str(value or "").strip()))


def get_window_geometries(settings: dict | None = None) -> dict:
    settings = settings if isinstance(settings, dict) else load_settings()
    data = settings.get("window_geometries", {})
    return dict(data) if isinstance(data, dict) else {}


def get_saved_window_geometry(key: str) -> str | None:
    geometry = str(get_window_geometries().get(key) or "").strip()
    return geometry if is_valid_geometry(geometry) else None


def get_geometry_size(geometry: str, fallback_width: int, fallback_height: int) -> tuple[int, int]:
    try:
        size = str(geometry).split("+", 1)[0].split("-", 1)[0]
        width_text, height_text = size.lower().split("x", 1)
        return max(1, int(width_text)), max(1, int(height_text))
    except Exception:
        return fallback_width, fallback_height


def restore_window_geometry(win, key: str, width: int | None = None, height: int | None = None):
    """Restore saved geometry, or center the window if no valid geometry exists."""
    geometry = get_saved_window_geometry(key)
    if geometry:
        win.geometry(geometry)
    else:
        center_window(win, width, height)


def save_window_geometry(win, key: str):
    """Save current window size and position to settings.json."""
    try:
        if not key:
            return
        if hasattr(win, "state") and win.state() in {"iconic", "withdrawn"}:
            return

        win.update_idletasks()
        geometry = str(win.geometry())
        if not is_valid_geometry(geometry):
            return

        settings = load_settings()
        geometries = get_window_geometries(settings)
        geometries[key] = geometry
        settings["window_geometries"] = geometries

        if key == "main":
            settings["main_window_size"] = geometry.split("+", 1)[0].split("-", 1)[0]

        save_settings(settings)
    except Exception as e:
        try:
            log_exception(e)
        except Exception:
            pass


def remember_window_geometry(win, key: str, width: int | None = None, height: int | None = None):
    """Restore now and save when the exact window is destroyed."""
    restore_window_geometry(win, key, width, height)

    def _save_on_destroy(event=None):
        if event is not None and event.widget is not win:
            return
        save_window_geometry(win, key)

    try:
        win.bind("<Destroy>", _save_on_destroy, add="+")
    except Exception:
        pass


def safe_filename(s: str) -> str:
    invalid = '<>:"/\\|?*'
    cleaned = "".join("_" if c in invalid else c for c in str(s).strip())
    return cleaned or "host"


def realvnc_profile_name(sector_name: str | None, host_name: str) -> str:
    # Avoid generating names such as "Host.vnc.vnc" when the configured
    # display name already includes the .vnc extension.
    clean_host_name = safe_filename(host_name)

    while clean_host_name.lower().endswith(".vnc"):
        clean_host_name = clean_host_name[:-4].rstrip()

    clean_host_name = clean_host_name or "host"

    if sector_name:
        return f"{safe_filename(sector_name)}_{clean_host_name}.vnc"
    return f"{clean_host_name}.vnc"


def realvnc_profile_path(sector_name: str | None, host_name: str) -> Path:
    return REALVNC_DIR / realvnc_profile_name(sector_name, host_name)


def rename_realvnc_profile(old_sector: str | None, old_name: str, new_sector: str | None, new_name: str, parent=None):
    old_path = realvnc_profile_path(old_sector, old_name)
    new_path = realvnc_profile_path(new_sector, new_name)
    if old_path == new_path or not old_path.exists():
        return
    if new_path.exists():
        audit_log("REALVNC_PROFILE_RENAME_SKIPPED", f"from={old_path}; to={new_path}; reason=destination_exists")
        if parent:
            messagebox.showwarning(
                "RealVNC",
                "Perfil RealVNC não renomeado porque o arquivo de destino já existe:\n\n"
                f"{new_path}",
                parent=parent,
            )
        return
    try:
        old_path.rename(new_path)
        audit_log("REALVNC_PROFILE_RENAMED", f"from={old_path}; to={new_path}")
    except Exception as e:
        audit_log("REALVNC_PROFILE_RENAME_ERROR", f"from={old_path}; to={new_path}; error={e}")
        if parent:
            messagebox.showwarning("RealVNC", f"Falha ao renomear perfil RealVNC:\n{e}", parent=parent)


def rename_realvnc_profiles_for_sector(old_sector: str, new_sector: str, hosts, parent=None):
    for host in hosts or []:
        if sanitize_viewer(host.get("viewer")) == VIEWER_REALVNC:
            rename_realvnc_profile(old_sector, host.get("name", "host"), new_sector, host.get("name", "host"), parent)


def show_error(parent, title: str, message: str):
    messagebox.showerror(title, message, parent=parent)


def show_info(parent, title: str, message: str):
    messagebox.showinfo(title, message, parent=parent)


def show_warning(parent, title: str, message: str):
    messagebox.showwarning(title, message, parent=parent)


def modal_window(win, parent=None):
    if parent:
        win.transient(parent)
    win.grab_set()
    win.focus_force()
    win.wait_window()


# =========================
# Diálogos modernos
# =========================
def confirm_action(parent, title, message) -> bool:
    result = {"value": False}
    win = ctk.CTkToplevel(parent)
    win.title(title)
    win.resizable(False, False)
    win.configure(fg_color=THEME["bg"])

    box = ctk.CTkFrame(win, fg_color=THEME["surface"], corner_radius=18)
    box.pack(fill="both", expand=True, padx=18, pady=18)

    ctk.CTkLabel(box, text=title, font=FONT_SUBTITLE, text_color=THEME["text"]).pack(anchor="w", padx=18, pady=(18, 8))
    ctk.CTkLabel(box, text=message, font=FONT_NORMAL, text_color=THEME["muted"], justify="left").pack(anchor="w", padx=18, pady=(0, 18))

    buttons = ctk.CTkFrame(box, fg_color="transparent")
    buttons.pack(fill="x", padx=18, pady=(0, 18))

    def yes():
        result["value"] = True
        win.destroy()

    def no():
        win.destroy()

    ctk.CTkButton(buttons, text="Cancelar", command=no, fg_color=THEME["surface_3"], hover_color=THEME["accent_soft"]).pack(side="right", padx=(8, 0))
    ctk.CTkButton(buttons, text="Confirmar", command=yes, fg_color=THEME["accent"], hover_color=THEME["accent_hover"]).pack(side="right")

    remember_window_geometry(win, f"dialog_text_{safe_filename(title)}", 420, 210)
    modal_window(win, parent)
    return result["value"]


def ask_text(parent: Any, title: str, label: str, initial: str = "") -> str | None:
    result: dict[str, str | None] = {"value": None}
    win = ctk.CTkToplevel(parent)
    win.title(title)
    win.resizable(False, False)
    win.configure(fg_color=THEME["bg"])

    box = ctk.CTkFrame(win, fg_color=THEME["surface"], corner_radius=18)
    box.pack(fill="both", expand=True, padx=18, pady=18)

    ctk.CTkLabel(box, text=title, font=FONT_SUBTITLE, text_color=THEME["text"]).pack(anchor="w", padx=18, pady=(18, 8))
    ctk.CTkLabel(box, text=label, font=FONT_NORMAL, text_color=THEME["muted"]).pack(anchor="w", padx=18, pady=(0, 8))

    entry = ctk.CTkEntry(box, width=380, height=38)
    entry.pack(fill="x", padx=18, pady=(0, 18))
    entry.insert(0, initial or "")
    entry.focus_set()
    entry.select_range(0, tk.END)

    buttons = ctk.CTkFrame(box, fg_color="transparent")
    buttons.pack(fill="x", padx=18, pady=(0, 18))

    def ok(_event=None):
        value = entry.get().strip()
        result["value"] = value or None
        win.destroy()

    def cancel():
        win.destroy()

    ctk.CTkButton(buttons, text="Cancelar", command=cancel, fg_color=THEME["surface_3"], hover_color=THEME["accent_soft"]).pack(side="right", padx=(8, 0))
    ctk.CTkButton(buttons, text="OK", command=ok, fg_color=THEME["accent"], hover_color=THEME["accent_hover"]).pack(side="right")
    win.bind("<Return>", ok)
    win.bind("<Escape>", lambda _e: cancel())

    remember_window_geometry(win, "dialog_host_details", 460, 235)
    modal_window(win, parent)
    return result["value"]


def ask_host_details(parent: Any, title: str, initial: dict[str, str] | None = None) -> dict[str, str] | None:
    initial = initial or {}
    result: dict[str, dict[str, str] | None] = {"value": None}

    win = ctk.CTkToplevel(parent)
    win.title(title)
    win.resizable(False, False)
    win.configure(fg_color=THEME["bg"])

    box = ctk.CTkFrame(win, fg_color=THEME["surface"], corner_radius=18)
    box.pack(fill="both", expand=True, padx=18, pady=18)

    ctk.CTkLabel(box, text=title, font=FONT_SUBTITLE, text_color=THEME["text"]).grid(row=0, column=0, columnspan=2, sticky="w", padx=18, pady=(18, 16))

    ctk.CTkLabel(box, text="Nome", font=FONT_NORMAL, text_color=THEME["muted"]).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 6))
    name_entry = ctk.CTkEntry(box, width=360, height=36)
    name_entry.grid(row=2, column=0, columnspan=2, sticky="ew", padx=18, pady=(0, 14))
    name_entry.insert(0, initial.get("name", ""))

    ctk.CTkLabel(box, text="Host/IP", font=FONT_NORMAL, text_color=THEME["muted"]).grid(row=3, column=0, sticky="w", padx=18, pady=(0, 6))
    host_entry = ctk.CTkEntry(box, width=360, height=36)
    host_entry.grid(row=4, column=0, columnspan=2, sticky="ew", padx=18, pady=(0, 14))
    host_entry.insert(0, initial.get("host", ""))

    ctk.CTkLabel(box, text="Viewer", font=FONT_NORMAL, text_color=THEME["muted"]).grid(row=5, column=0, sticky="w", padx=18, pady=(0, 6))
    viewer_var = tk.StringVar(value=sanitize_viewer(initial.get("viewer", DEFAULT_VIEWER)))
    viewer_menu = ctk.CTkOptionMenu(box, values=VIEWER_OPTIONS, variable=viewer_var, width=180)
    viewer_menu.grid(row=6, column=0, sticky="w", padx=18, pady=(0, 18))

    buttons = ctk.CTkFrame(box, fg_color="transparent")
    buttons.grid(row=7, column=0, columnspan=2, sticky="e", padx=18, pady=(0, 18))

    def ok(_event=None):
        name = name_entry.get().strip()
        host = host_entry.get().strip()
        if not name or not host:
            show_warning(win, "Campos obrigatórios", "Preencha Nome e Host/IP.")
            return
        result["value"] = {"name": name, "host": host, "viewer": sanitize_viewer(viewer_var.get())}
        win.destroy()

    def cancel():
        win.destroy()

    ctk.CTkButton(buttons, text="Cancelar", command=cancel, fg_color=THEME["surface_3"], hover_color=THEME["accent_soft"]).pack(side="right", padx=(8, 0))
    ctk.CTkButton(buttons, text="Salvar", command=ok, fg_color=THEME["accent"], hover_color=THEME["accent_hover"]).pack(side="right")
    win.bind("<Return>", ok)
    win.bind("<Escape>", lambda _e: cancel())

    remember_window_geometry(win, "dialog_custom_connection", 450, 410)
    name_entry.focus_set()
    modal_window(win, parent)
    return result["value"]


def ask_custom_connection(parent: Any) -> tuple[str, str] | None:
    result: dict[str, tuple[str, str] | None] = {"value": None}
    win = ctk.CTkToplevel(parent)
    win.title("Conexão manual")
    win.resizable(False, False)
    win.configure(fg_color=THEME["bg"])

    box = ctk.CTkFrame(win, fg_color=THEME["surface"], corner_radius=18)
    box.pack(fill="both", expand=True, padx=18, pady=18)

    ctk.CTkLabel(box, text="Conexão manual", font=FONT_SUBTITLE, text_color=THEME["text"]).pack(anchor="w", padx=18, pady=(18, 8))
    ctk.CTkLabel(box, text="Digite o hostname ou IP e selecione o viewer.", font=FONT_NORMAL, text_color=THEME["muted"]).pack(anchor="w", padx=18, pady=(0, 14))

    entry = ctk.CTkEntry(box, width=380, height=38, placeholder_text="hostname ou IP")
    entry.pack(fill="x", padx=18, pady=(0, 14))
    entry.focus_set()

    viewer_var = tk.StringVar(value=DEFAULT_VIEWER)
    ctk.CTkOptionMenu(box, values=VIEWER_OPTIONS, variable=viewer_var, width=180).pack(anchor="w", padx=18, pady=(0, 18))

    buttons = ctk.CTkFrame(box, fg_color="transparent")
    buttons.pack(fill="x", padx=18, pady=(0, 18))

    def ok(_event=None):
        host = entry.get().strip()
        if not host:
            show_warning(win, "Campo obrigatório", "Digite um hostname ou IP.")
            return
        result["value"] = (host, sanitize_viewer(viewer_var.get()))
        win.destroy()

    def cancel():
        win.destroy()

    ctk.CTkButton(buttons, text="Cancelar", command=cancel, fg_color=THEME["surface_3"], hover_color=THEME["accent_soft"]).pack(side="right", padx=(8, 0))
    ctk.CTkButton(buttons, text="Conectar", command=ok, fg_color=THEME["accent"], hover_color=THEME["accent_hover"]).pack(side="right")
    win.bind("<Return>", ok)
    win.bind("<Escape>", lambda _e: cancel())

    remember_window_geometry(win, "dialog_realvnc_profile", 460, 310)
    modal_window(win, parent)
    return result["value"]


def show_realvnc_profile_dialog(parent, profile_path: Path, profile_name: str):
    result = {"value": None}
    win = ctk.CTkToplevel(parent)
    win.title("Perfil RealVNC")
    win.resizable(False, False)
    win.configure(fg_color=THEME["bg"])

    box = ctk.CTkFrame(win, fg_color=THEME["surface"], corner_radius=18)
    box.pack(fill="both", expand=True, padx=18, pady=18)

    ctk.CTkLabel(box, text="Perfil RealVNC não encontrado", font=FONT_SUBTITLE, text_color=THEME["text"]).pack(anchor="w", padx=18, pady=(18, 8))
    text = (
        "Crie ou copie o perfil esperado para este host.\n\n"
        f"Arquivo esperado:\n{profile_path}\n\n"
        "Depois disso, tente conectar novamente."
    )
    ctk.CTkLabel(box, text=text, font=FONT_NORMAL, text_color=THEME["muted"], justify="left").pack(anchor="w", padx=18, pady=(0, 18))

    buttons = ctk.CTkFrame(box, fg_color="transparent")
    buttons.pack(fill="x", padx=18, pady=(0, 18))

    def create_empty():
        try:
            profile_path.parent.mkdir(parents=True, exist_ok=True)
            profile_path.touch(exist_ok=False)
            audit_log("REALVNC_PROFILE_CREATED_EMPTY", f"file={profile_path}")
            show_info(win, "RealVNC", f"Arquivo criado:\n{profile_path}")
        except FileExistsError:
            show_info(win, "RealVNC", f"Arquivo já existe:\n{profile_path}")
        except Exception as e:
            audit_log("REALVNC_PROFILE_CREATE_ERROR", f"file={profile_path}; error={e}")
            show_error(win, "RealVNC", f"Falha ao criar arquivo:\n{e}")

    def copy_name():
        try:
            win.clipboard_clear()
            win.clipboard_append(profile_name)
            show_info(win, "RealVNC", "Nome copiado para a área de transferência.")
        except Exception as e:
            show_error(win, "RealVNC", f"Falha ao copiar nome:\n{e}")

    ctk.CTkButton(buttons, text="Fechar", command=win.destroy, fg_color=THEME["surface_3"], hover_color=THEME["accent_soft"]).pack(side="right", padx=(8, 0))
    ctk.CTkButton(buttons, text="Copiar nome", command=copy_name, fg_color=THEME["surface_3"], hover_color=THEME["accent_soft"]).pack(side="right", padx=(8, 0))
    ctk.CTkButton(buttons, text="Criar arquivo", command=create_empty, fg_color=THEME["accent"], hover_color=THEME["accent_hover"]).pack(side="right")

    remember_window_geometry(win, "dialog_hosts_source_select", 620, 335)
    modal_window(win, parent)
    return result["value"]


# =========================
# Windows DPAPI
# =========================
class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


try:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
except Exception:
    crypt32 = None
    kernel32 = None

CRYPTPROTECT_UI_FORBIDDEN = 0x01


def _bytes_to_blob(data: bytes) -> DATA_BLOB:
    buf = ctypes.create_string_buffer(data)
    blob = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob._buffer = buf  # mantém o buffer vivo durante a chamada DPAPI
    return blob


def _blob_to_bytes(blob: DATA_BLOB) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        if kernel32:
            kernel32.LocalFree(blob.pbData)


def dpapi_encrypt(plaintext: str) -> str:
    if crypt32 is None:
        raise RuntimeError("DPAPI disponível apenas no Windows.")
    data = plaintext.encode("utf-8")
    in_blob = _bytes_to_blob(data)
    out_blob = DATA_BLOB()
    if not crypt32.CryptProtectData(ctypes.byref(in_blob), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob)):
        raise ctypes.WinError()
    return base64.b64encode(_blob_to_bytes(out_blob)).decode("ascii")


def dpapi_decrypt(ciphertext_b64: str) -> str:
    if crypt32 is None:
        raise RuntimeError("DPAPI disponível apenas no Windows.")
    data = base64.b64decode(ciphertext_b64.encode("ascii"))
    in_blob = _bytes_to_blob(data)
    out_blob = DATA_BLOB()
    if not crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob)):
        raise ctypes.WinError()
    return _blob_to_bytes(out_blob).decode("utf-8")


# =========================
# JSON e dados da aplicação
# =========================
def save_json(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)

    try:
        path.write_text(payload, encoding="utf-8")
        return True
    except PermissionError:
        # Common Windows case: settings.json was created as read-only or inherited
        # restrictive attributes. Try to clear the read-only bit once.
        try:
            if path.exists():
                path.chmod(0o666)
            path.write_text(payload, encoding="utf-8")
            return True
        except PermissionError:
            raise


def sanitize_viewer(value) -> str:
    value = str(value or "").strip().lower()
    if value not in VIEWER_OPTIONS:
        return DEFAULT_VIEWER
    return value


def viewer_display_name(viewer: str) -> str:
    viewer = sanitize_viewer(viewer)
    if viewer == VIEWER_REALVNC:
        return "RealVNC"
    return "UltraVNC"


def sanitize_host_list(data):
    hosts = []
    if not isinstance(data, list):
        return hosts
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or f"Host {i + 1}").strip()
        host = str(item.get("host") or item.get("ip") or "").strip()
        viewer = sanitize_viewer(item.get("viewer"))
        if host:
            hosts.append({"name": name or host, "host": host, "viewer": viewer})
    return hosts


def sanitize_sector_list(data):
    sectors = []
    if not isinstance(data, list):
        return sectors
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or f"Setor {i + 1}").strip()
        hosts = sanitize_host_list(item.get("hosts", []))
        sectors.append({"name": name or f"Setor {i + 1}", "hosts": hosts})
    return sectors


def normalize_hosts_data(data):
    if not isinstance(data, dict):
        return DEFAULT_HOSTS.copy()

    # Novo formato: units > sectors > hosts
    if isinstance(data.get("units"), list):
        units = []
        for i, unit in enumerate(data.get("units", [])):
            if not isinstance(unit, dict):
                continue
            name = str(unit.get("name") or f"Unidade {i + 1}").strip()
            sectors = sanitize_sector_list(unit.get("sectors", []))
            if not sectors:
                sectors = [{"name": "Geral", "hosts": []}]
            units.append({"name": name or f"Unidade {i + 1}", "sectors": sectors})
        if units:
            return {"units": units}

    # Compatibilidade com formato antigo baseado em groups.
    if isinstance(data.get("groups"), list):
        sectors = []
        for group in data.get("groups", []):
            if not isinstance(group, dict):
                continue
            sectors.append({
                "name": str(group.get("name") or "Geral"),
                "hosts": sanitize_host_list(group.get("hosts", [])),
            })
        return {"units": [{"name": "Geral", "sectors": sectors or [{"name": "Geral", "hosts": []}]}]}

    # Compatibilidade com formato plano {"Nome": "host"}.
    hosts = []
    for name, host in data.items():
        if isinstance(host, str):
            hosts.append({"name": str(name), "host": host, "viewer": DEFAULT_VIEWER})
    if hosts:
        return {"units": [{"name": "Geral", "sectors": [{"name": "Geral", "hosts": hosts}]}]}

    return DEFAULT_HOSTS.copy()


def load_hosts_data(path=SHARED_HOSTS_JSON, defaults=DEFAULT_HOSTS):
    path = Path(path)
    if not path.exists():
        save_json(defaults, path)
        return normalize_hosts_data(defaults)
    try:
        return normalize_hosts_data(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        log_exception()
        return normalize_hosts_data(defaults)


def get_unit_names(hosts_data):
    return [u.get("name", "Geral") for u in hosts_data.get("units", [])]


def get_unit_by_name(hosts_data, unit_name):
    for unit in hosts_data.get("units", []):
        if unit.get("name") == unit_name:
            return unit
    return None


def get_sector_names(hosts_data, unit_name):
    unit = get_unit_by_name(hosts_data, unit_name)
    if not unit:
        return []
    return [s.get("name", "Geral") for s in unit.get("sectors", [])]


def get_sector_by_name(hosts_data, unit_name, sector_name):
    unit = get_unit_by_name(hosts_data, unit_name)
    if not unit:
        return None
    for sector in unit.get("sectors", []):
        if sector.get("name") == sector_name:
            return sector
    return None


def get_sector_hosts(hosts_data, unit_name, sector_name):
    sector = get_sector_by_name(hosts_data, unit_name, sector_name)
    return sector.get("hosts", []) if sector else []


def load_creds() -> tuple[str, str]:
    if not CREDS_JSON.exists():
        return "", ""
    try:
        data = json.loads(CREDS_JSON.read_text(encoding="utf-8"))
        user = data.get("user", "")
        enc_pwd = data.get("password", "")
        pwd = dpapi_decrypt(enc_pwd) if enc_pwd else ""
        return user, pwd
    except Exception:
        log_exception()
        return "", ""


def save_creds(user: str, pwd: str) -> None:
    CREDS_JSON.parent.mkdir(parents=True, exist_ok=True)
    CREDS_JSON.write_text(json.dumps({"user": user, "password": dpapi_encrypt(pwd)}, indent=2), encoding="utf-8")


def _read_settings_file(path: Path) -> dict | None:
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            merged = DEFAULT_SETTINGS.copy()
            merged.update(data)
            return merged
    except Exception as e:
        log_exception(e)
    return None


def _write_settings_file(path: Path, settings: dict) -> bool:
    try:
        save_json(settings, path)
        return True
    except Exception as e:
        log_exception(e)
        return False


def load_settings():
    # Prefer the fallback if it exists, because it means the primary Documents
    # settings path was not writable on a previous run.
    fallback_settings = _read_settings_file(FALLBACK_SETTINGS_JSON)
    if fallback_settings is not None:
        return fallback_settings

    primary_settings = _read_settings_file(SETTINGS_JSON)
    if primary_settings is not None:
        return primary_settings

    settings = DEFAULT_SETTINGS.copy()
    if not _write_settings_file(SETTINGS_JSON, settings):
        _write_settings_file(FALLBACK_SETTINGS_JSON, settings)
    return settings


def save_settings(settings):
    # Try the original Documents location first. If Windows denies it, save to
    # AppData instead so the app keeps working and settings still persist.
    if _write_settings_file(SETTINGS_JSON, settings):
        return True
    return _write_settings_file(FALLBACK_SETTINGS_JSON, settings)


def _settings_path_value(settings: dict, key: str, default_path: str) -> str:
    value = str(settings.get(key) or "").strip()
    return value or default_path


def get_ultravnc_exe() -> str:
    return _settings_path_value(load_settings(), "ultravnc_exe", ULTRAVNC_EXE)


def get_realvnc_exe() -> str:
    return _settings_path_value(load_settings(), "realvnc_exe", REALVNC_EXE)


def resolve_existing_exe(configured_path: str, default_path: str) -> str | None:
    """Return a valid executable path, trying the configured path first."""
    configured_path = str(configured_path or "").strip()
    if configured_path and Path(configured_path).exists():
        return configured_path
    if Path(default_path).exists():
        return default_path
    return None


def get_host_columns(settings: dict) -> int:
    try:
        value = int(settings.get("host_columns", 3))
    except Exception:
        value = 3
    return max(1, min(value, 6))


def normalize_hosts_source(value) -> str:
    value = str(value or "").strip().lower()
    return value if value in HOSTS_SOURCE_OPTIONS else ""


def hosts_source_display_name(source: str) -> str:
    source = normalize_hosts_source(source)
    if source == HOSTS_SOURCE_CUSTOM:
        return "Personalizada"
    if source == HOSTS_SOURCE_EMPTY:
        return "Vazia"
    return "Padrão"


def get_hosts_path_for_source(source: str) -> Path:
    source = normalize_hosts_source(source) or HOSTS_SOURCE_SHARED
    if source in {HOSTS_SOURCE_CUSTOM, HOSTS_SOURCE_EMPTY}:
        return USER_HOSTS_JSON
    return SHARED_HOSTS_JSON


def update_hosts_file_setting(settings):
    source = normalize_hosts_source(settings.get("hosts_source")) or HOSTS_SOURCE_SHARED
    settings["hosts_source"] = source
    settings["hosts_file"] = str(get_hosts_path_for_source(source))
    save_settings(settings)


def copy_shared_hosts_to_user(overwrite=True):
    USER_HOSTS_JSON.parent.mkdir(parents=True, exist_ok=True)
    if USER_HOSTS_JSON.exists() and not overwrite:
        return
    if SHARED_HOSTS_JSON.exists():
        shutil.copy2(SHARED_HOSTS_JSON, USER_HOSTS_JSON)
    else:
        save_json(DEFAULT_HOSTS, USER_HOSTS_JSON)


def create_empty_user_hosts(overwrite=True):
    USER_HOSTS_JSON.parent.mkdir(parents=True, exist_ok=True)
    if USER_HOSTS_JSON.exists() and not overwrite:
        return
    save_json(DEFAULT_HOSTS, USER_HOSTS_JSON)


def set_hosts_source(settings, source: str, overwrite_user_file=True):
    source = normalize_hosts_source(source) or HOSTS_SOURCE_SHARED
    if source == HOSTS_SOURCE_CUSTOM:
        copy_shared_hosts_to_user(overwrite=overwrite_user_file)
    elif source == HOSTS_SOURCE_EMPTY:
        create_empty_user_hosts(overwrite=overwrite_user_file)
    settings["hosts_source"] = source
    settings["hosts_file"] = str(get_hosts_path_for_source(source))
    save_settings(settings)


# =========================
# Seleção da lista de hosts
# =========================
def choose_hosts_source_dialog(parent, required=False):
    result = {"value": None}
    win = ctk.CTkToplevel(parent)
    win.title("Selecionar lista de hosts")
    win.resizable(False, False)
    win.protocol("WM_DELETE_WINDOW", lambda: None if required else win.destroy())
    win.configure(fg_color=THEME["bg"])

    box = ctk.CTkFrame(win, fg_color=THEME["surface"], corner_radius=18)
    box.pack(fill="both", expand=True, padx=18, pady=18)

    ctk.CTkLabel(box, text="Lista de hosts", font=FONT_SUBTITLE, text_color=THEME["text"]).pack(anchor="w", padx=18, pady=(18, 8))
    msg = (
        "Escolha como esta instalação deve carregar os hosts.\n\n"
        "Padrão: lista compartilhada da pasta do aplicativo.\n"
        "Personalizada: cópia pessoal em Documents\\VNC-Menu.\n"
        "Vazia: lista pessoal limpa para este usuário."
    )
    ctk.CTkLabel(box, text=msg, font=FONT_NORMAL, text_color=THEME["muted"], justify="left").pack(anchor="w", padx=18, pady=(0, 16))

    buttons = ctk.CTkFrame(box, fg_color="transparent")
    buttons.pack(fill="x", padx=18, pady=(0, 18))

    def choose(value):
        result["value"] = value
        win.destroy()

    ctk.CTkButton(buttons, text="Padrão", command=lambda: choose(HOSTS_SOURCE_SHARED), fg_color=THEME["accent"], hover_color=THEME["accent_hover"]).pack(side="left", padx=(0, 8))
    ctk.CTkButton(buttons, text="Personalizada", command=lambda: choose(HOSTS_SOURCE_CUSTOM), fg_color=THEME["surface_3"], hover_color=THEME["accent_soft"]).pack(side="left", padx=(0, 8))
    ctk.CTkButton(buttons, text="Vazia", command=lambda: choose(HOSTS_SOURCE_EMPTY), fg_color=THEME["surface_3"], hover_color=THEME["accent_soft"]).pack(side="left", padx=(0, 8))
    if not required:
        ctk.CTkButton(buttons, text="Cancelar", command=win.destroy, fg_color=THEME["surface_3"], hover_color=THEME["accent_soft"]).pack(side="right")

    remember_window_geometry(win, "dialog_hosts_source_select", 620)
    modal_window(win, parent)
    return result["value"]


def ensure_hosts_source_selected(parent, settings):
    source = normalize_hosts_source(settings.get("hosts_source"))
    if not source:
        source = choose_hosts_source_dialog(parent, required=True) or HOSTS_SOURCE_SHARED
        set_hosts_source(settings, source, overwrite_user_file=True)
        audit_log("HOSTS_SOURCE_SELECTED", f"source={hosts_source_display_name(source)}; file={settings.get('hosts_file', '')}")
    else:
        update_hosts_file_setting(settings)
    return normalize_hosts_source(settings.get("hosts_source")) or HOSTS_SOURCE_SHARED


def shared_hosts_edit_warning(parent):
    result = {"value": "cancel"}
    win = ctk.CTkToplevel(parent)
    win.title("Editar lista padrão")
    win.resizable(False, False)
    win.configure(fg_color=THEME["bg"])

    box = ctk.CTkFrame(win, fg_color=THEME["surface"], corner_radius=18)
    box.pack(fill="both", expand=True, padx=18, pady=18)

    ctk.CTkLabel(box, text="Lista compartilhada", font=FONT_SUBTITLE, text_color=THEME["text"]).pack(anchor="w", padx=18, pady=(18, 8))
    msg = (
        "A lista Padrão é compartilhada.\n"
        "Qualquer alteração pode afetar outros usuários desta instalação.\n\n"
        "Editar padrão: altera o arquivo compartilhado.\n"
        "Criar cópia: muda para uma lista pessoal deste usuário."
    )
    ctk.CTkLabel(box, text=msg, font=FONT_NORMAL, text_color=THEME["muted"], justify="left").pack(anchor="w", padx=18, pady=(0, 16))

    buttons = ctk.CTkFrame(box, fg_color="transparent")
    buttons.pack(fill="x", padx=18, pady=(0, 18))

    def choose(value):
        result["value"] = value
        win.destroy()

    ctk.CTkButton(buttons, text="Cancelar", command=lambda: choose("cancel"), fg_color=THEME["surface_3"], hover_color=THEME["accent_soft"]).pack(side="right", padx=(8, 0))
    ctk.CTkButton(buttons, text="Criar cópia", command=lambda: choose("copy"), fg_color=THEME["surface_3"], hover_color=THEME["accent_soft"]).pack(side="right", padx=(8, 0))
    ctk.CTkButton(buttons, text="Editar padrão", command=lambda: choose("continue"), fg_color=THEME["accent"], hover_color=THEME["accent_hover"]).pack(side="right")

    remember_window_geometry(win, "dialog_shared_hosts_warning", 610)
    modal_window(win, parent)
    return result["value"]

# =========================
# Conexões e operações remotas
# =========================
def auto_enter_uvnc_credentials(timeout=AUTH_TIMEOUT) -> bool:
    user, pwd = load_creds()
    if not user and not pwd:
        return False

    deadline = time.time() + timeout
    dlg = None

    while time.time() < deadline:
        try:
            candidate = Desktop(backend="win32").window(title_re=AUTH_TITLE_RE)
            if candidate.exists(timeout=0.2):
                dlg = candidate
                break
        except Exception:
            pass
        time.sleep(0.1)

    if dlg is None:
        return False

    try:
        dlg.wait("visible", timeout=2)
        dlg.set_focus()
        edits = dlg.descendants(control_type="Edit")

        if len(edits) == 1:
            edits[0].set_text(pwd)
            send_keys("{ENTER}")
            return True

        if len(edits) >= 2:
            if user:
                edits[0].set_text(user)
            edits[1].set_text(pwd)
            send_keys("{ENTER}")
            return True

        if user:
            send_keys(user + "{TAB}" + pwd + "{ENTER}", with_spaces=True)
        else:
            send_keys(pwd + "{ENTER}", with_spaces=True)
        return True

    except Exception:
        return False


def launch_vnc(
    host: str,
    viewer: str = DEFAULT_VIEWER,
    display_name: str | None = None,
    sector_name: str | None = None,
    parent=None,
    auto_credentials: bool = True,
):
    viewer = sanitize_viewer(viewer)
    host = str(host or "").strip()
    target_name = str(display_name or host or "Host").strip()

    if not host:
        show_error(parent, "VNC", "Host/IP vazio.")
        audit_log("CONNECTION_BLOCKED", f"viewer={viewer}; reason=empty_host; name={target_name}")
        return

    audit_log(
        "CONNECTION_ATTEMPT",
        f"viewer={viewer_display_name(viewer)}; name={target_name}; host={host}; setor={sector_name or '-'}",
    )

    try:
        if viewer == VIEWER_REALVNC:
            configured_realvnc = get_realvnc_exe()
            realvnc_exe = resolve_existing_exe(configured_realvnc, REALVNC_EXE)

            if not realvnc_exe:
                audit_log("CONNECTION_ERROR", f"viewer=RealVNC; host={host}; reason=viewer_not_found; path={configured_realvnc}")
                show_error(parent, "Erro", f"RealVNC Viewer não encontrado:\n{configured_realvnc}")
                return

            profile_name = realvnc_profile_name(sector_name, target_name)
            profile_path = REALVNC_DIR / profile_name

            if profile_path.exists() and profile_path.stat().st_size > 0:
                subprocess.Popen(
                    [realvnc_exe, str(profile_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                audit_log("CONNECTION_STARTED", f"viewer=RealVNC; name={target_name}; host={host}; profile={profile_path}")
                return

            audit_log("CONNECTION_BLOCKED", f"viewer=RealVNC; name={target_name}; host={host}; reason=profile_missing_or_empty; profile={profile_path}")
            if parent is not None:
                show_realvnc_profile_dialog(parent, profile_path, profile_name)
            else:
                show_info(None, "Perfil RealVNC", f"Perfil RealVNC não encontrado ou vazio:\n\n{profile_path}")
            return

        configured_ultravnc = get_ultravnc_exe()
        ultravnc_exe = resolve_existing_exe(configured_ultravnc, ULTRAVNC_EXE)

        if not ultravnc_exe:
            audit_log("CONNECTION_ERROR", f"viewer=UltraVNC; host={host}; reason=viewer_not_found; path={configured_ultravnc}")
            show_error(parent, "Erro", f"UltraVNC Viewer não encontrado:\n{configured_ultravnc}")
            return

        if not TEMPLATE_VNC.exists():
            audit_log("CONNECTION_ERROR", f"viewer=UltraVNC; host={host}; reason=template_not_found; path={TEMPLATE_VNC}")
            show_error(parent, "Erro", "template.vnc não encontrado.\nVerifique se ele está na pasta _internal.")
            return

        # This is the launch behavior from the old working Tkinter version:
        # copy the template unchanged and pass the target as host::port.
        tmp_vnc = Path(tempfile.gettempdir()) / f"uvnc_{safe_filename(host)}.vnc"
        shutil.copyfile(TEMPLATE_VNC, tmp_vnc)

        cmd = [ultravnc_exe, "-config", str(tmp_vnc), f"{host}::{PORT}"]
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(Path(ultravnc_exe).parent),
        )
        audit_log("CONNECTION_STARTED", f"viewer=UltraVNC; name={target_name}; host={host}; template={TEMPLATE_VNC}")

        if auto_credentials:
            auto_enter_uvnc_credentials()

    except Exception as e:
        audit_log("CONNECTION_ERROR", f"viewer={viewer_display_name(viewer)}; host={host}; error={e}")
        log_exception(e)
        show_error(parent, "Erro", f"Falha ao iniciar viewer VNC:\n{e}\n\nLog: {ERROR_LOG}")

def restart_host(host: str):
    audit_log("RESTART_ATTEMPT", f"host={host}")
    try:
        subprocess.run(["shutdown", "/r", "/m", f"\\\\{host}", "/t", "0", "/f"], check=True, capture_output=True, text=True)
        audit_log("RESTART_SENT", f"host={host}")
    except Exception as e:
        log_exception(e)
        audit_log("RESTART_ERROR", f"host={host}; error={e}")
        raise


def query_all_logged_users(hosts):
    rows = []

    for item in hosts:
        name = str(item.get("name") or "Host")
        host = str(item.get("host") or "").strip()

        if not host:
            rows.append((name, "SEM HOST"))
            continue

        try:
            ping = subprocess.run(
                ["ping", "-n", "1", "-w", "800", host],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            if ping.returncode != 0:
                rows.append((name, "OFFLINE"))
                continue

            result = subprocess.run(
                ["qwinsta", f"/server:{host}"],
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            output = result.stdout.strip()
            error = result.stderr.strip()

            if result.returncode != 0:
                rows.append((name, error or output or "ERRO"))
                continue

            users = []
            for line in output.splitlines()[1:]:
                parts = line.split()

                # Old working behavior: in Portuguese Windows output, the username
                # appears in this position for disconnected user sessions.
                if len(parts) >= 4:
                    username = parts[1]
                    if username.lower() not in ("services", "console", "rdp-tcp"):
                        users.append(username)

            rows.append((name, ", ".join(users) if users else "VAZIO"))

        except Exception as e:
            rows.append((name, f"ERRO: {e}"))

    return format_users_output(rows)


def format_users_output(rows):
    if not rows:
        return "Nenhum host encontrado."

    host_w = max(len("HOST"), *(len(str(r[0])) for r in rows))
    lines = []
    lines.append(f"{'HOST':<{host_w}}  USUÁRIO")
    lines.append("-" * (host_w + 35))

    for host, user in rows:
        lines.append(f"{host:<{host_w}}  {user}")

    return "\n".join(lines)

def show_text_window(parent, title, content):
    lines = content.splitlines()
    max_len = max((len(line) for line in lines), default=40)
    line_count = max(len(lines), 1)

    # Auto-size the output window to avoid large empty areas for short reports.
    width = min(max((max_len * 8) + 110, 460), 760)
    height = min(max((line_count * 18) + 135, 300), 540)
    textbox_height = max(height - 150, 150)

    win = ctk.CTkToplevel(parent)
    win.title(title)
    win.geometry(f"{width}x{height}")
    win.minsize(420, 260)
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
        text="Fechar",
        width=140,
        height=36,
        command=win.destroy,
        fg_color=THEME["surface_3"],
        hover_color=THEME["accent_soft"],
        text_color=THEME["secondary_button_text"],
    ).pack(anchor="e", padx=18, pady=(0, 18))

    remember_window_geometry(win, "window_text_output", width, height)

    # Keep the result window visible without making it modal.
    # Do not use grab_set() here, because the user still needs normal access
    # to the rest of Windows while this report is open.
    win.transient(parent)
    win.lift()
    win.focus()

    try:
        win.attributes("-topmost", True)
        win.after(250, lambda: win.attributes("-topmost", False))
    except Exception:
        pass


class QwinstaProgressWindow(ctk.CTkToplevel):
    def __init__(self, parent, label: str, host_count: int):
        super().__init__(parent)
        self.title("Consultando usuários")
        self.geometry("430x190")
        self.resizable(False, False)
        self.configure(fg_color=THEME["bg"])

        box = ctk.CTkFrame(self, fg_color=THEME["surface"], corner_radius=18)
        box.pack(fill="both", expand=True, padx=18, pady=18)

        ctk.CTkLabel(
            box,
            text="Consultando usuários logados",
            font=FONT_SUBTITLE,
            text_color=THEME["text"],
        ).pack(anchor="w", padx=18, pady=(18, 8))

        ctk.CTkLabel(
            box,
            text=f"Executando qwinsta em {host_count} host(s): {label}",
            font=FONT_NORMAL,
            text_color=THEME["muted"],
            wraplength=360,
            justify="left",
        ).pack(anchor="w", padx=18, pady=(0, 14))

        self.progress = ctk.CTkProgressBar(box, mode="indeterminate")
        self.progress.pack(fill="x", padx=18, pady=(0, 14))
        self.progress.start()

        ctk.CTkLabel(
            box,
            text="Aguarde. A janela de resultado abrirá automaticamente.",
            font=FONT_SMALL,
            text_color=THEME["muted"],
        ).pack(anchor="w", padx=18, pady=(0, 18))

        center_window(self, 430, 190)
        self.transient(parent)
        self.lift()
        self.focus()

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
        self.destroy()


# =========================
# Janela de credenciais
# =========================
class CredsWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Credenciais")
        self.geometry("500x390")
        self.resizable(False, False)
        self.configure(fg_color=THEME["bg"])

        user, pwd = load_creds()
        box = ctk.CTkFrame(self, fg_color=THEME["surface"], corner_radius=18)
        box.pack(fill="both", expand=True, padx=18, pady=18)

        ctk.CTkLabel(box, text="Credenciais UltraVNC", font=FONT_SUBTITLE, text_color=THEME["text"]).pack(anchor="w", padx=18, pady=(18, 8))
        ctk.CTkLabel(box, text="Salvas por usuário usando Windows DPAPI.", font=FONT_NORMAL, text_color=THEME["muted"]).pack(anchor="w", padx=18, pady=(0, 18))

        ctk.CTkLabel(box, text="Usuário", font=FONT_NORMAL, text_color=THEME["muted"]).pack(anchor="w", padx=18, pady=(0, 6))
        self.user_entry = ctk.CTkEntry(box, height=36)
        self.user_entry.pack(fill="x", padx=18, pady=(0, 14))
        self.user_entry.insert(0, user)

        ctk.CTkLabel(box, text="Senha", font=FONT_NORMAL, text_color=THEME["muted"]).pack(anchor="w", padx=18, pady=(0, 6))
        self.pwd_entry = ctk.CTkEntry(box, height=36, show="*")
        self.pwd_entry.pack(fill="x", padx=18, pady=(0, 18))
        self.pwd_entry.insert(0, pwd)

        buttons = ctk.CTkFrame(box, fg_color="transparent")
        buttons.pack(fill="x", padx=18, pady=(8, 18))
        ctk.CTkButton(
            buttons,
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
            text="Salvar",
            width=130,
            height=42,
            command=self.save,
            fg_color=THEME["accent"],
            hover_color=THEME["accent_hover"],
            text_color=THEME["button_text"],
        ).pack(side="right")

        remember_window_geometry(self, "window_credentials", 500, 390)
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


# =========================
# Janelas de edição de unidades e setores
# =========================
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
            ctk.CTkButton(actions, text=text, command=cmd, width=70, fg_color=THEME["surface_3"], hover_color=THEME["accent_soft"]).pack(side="left", padx=(0, 8))

        ctk.CTkButton(actions, text="Fechar", command=self.destroy, width=80, fg_color=THEME["accent"], hover_color=THEME["accent_hover"]).pack(side="right")

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
                text=self.get_item_name(item),
                anchor="w",
                height=38,
                fg_color=THEME["accent_soft"] if selected else THEME["surface_2"],
                hover_color=THEME["accent_soft"],
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
        name = ask_text(self, "Adicionar", "Nome:")
        if not name:
            return
        self.items.append({"name": name, "sectors": [{"name": "Geral", "hosts": []}]})
        self.selected_index = len(self.items) - 1
        self.notify("add", name=name)
        self.render_items()

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
        if not confirm_action(self, "Remover", f"Remover:\n{name}?"):
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

# =========================
# Editor completo da lista de hosts
# =========================
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

        self.title("Configurar Hosts VNC")
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
                "Existem alterações não salvas.\n\nFechar sem salvar?"
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
        self.unit_menu = ctk.CTkOptionMenu(self.left, values=get_unit_names(self.data) or ["Geral"], variable=self.selected_unit, command=lambda _v: self.on_unit_changed())
        self.unit_menu.pack(fill="x", padx=18, pady=(0, 12))

        ctk.CTkButton(
            self.left,
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
                text=name,
                anchor="w",
                height=38,
                fg_color=THEME["accent_soft"] if selected else THEME["surface_2"],
                hover_color=THEME["accent_soft"],
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
                str(item.get("host") or ""),
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
        if not confirm_action(self, "Remover host", f"Remover:\n{item.get('name')}?"):
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
        save_json(normalized, self._hosts_path)
        self._initial_snapshot = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
        self._audit("LIST_SAVE", f"units={len(normalized.get('units', []))}")
        self._on_save(normalized)
        self.destroy()



# =========================
# Caminhos dos viewers VNC
# =========================
class ViewerPathsWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.settings = parent.settings
        self.title("Caminhos dos Viewers")
        self.geometry("720x360")
        self.resizable(False, False)
        self.configure(fg_color=THEME["bg"])

        box = ctk.CTkFrame(self, fg_color=THEME["surface"], corner_radius=18)
        box.pack(fill="both", expand=True, padx=18, pady=18)
        box.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(box, text="Caminhos dos Viewers", font=FONT_SUBTITLE, text_color=THEME["text"]).grid(row=0, column=0, columnspan=3, sticky="w", padx=18, pady=(18, 6))
        ctk.CTkLabel(
            box,
            text="Use esta tela se o UltraVNC ou RealVNC estiverem instalados fora do caminho padrão.",
            font=FONT_NORMAL,
            text_color=THEME["muted"],
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=18, pady=(0, 18))

        self.ultravnc_var = tk.StringVar(value=str(self.settings.get("ultravnc_exe") or ULTRAVNC_EXE))
        self.realvnc_var = tk.StringVar(value=str(self.settings.get("realvnc_exe") or REALVNC_EXE))

        self._path_row(box, 2, "UltraVNC Viewer", self.ultravnc_var)
        self._path_row(box, 4, "RealVNC Viewer", self.realvnc_var)

        buttons = ctk.CTkFrame(box, fg_color="transparent")
        buttons.grid(row=6, column=0, columnspan=3, sticky="ew", padx=18, pady=(18, 18))

        ctk.CTkButton(
            buttons,
            text="Restaurar padrão",
            width=150,
            height=40,
            command=self.restore_defaults,
            fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"],
        ).pack(side="left")

        ctk.CTkButton(
            buttons,
            text="Cancelar",
            width=120,
            height=40,
            command=self.destroy,
            fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"],
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            buttons,
            text="Salvar",
            width=120,
            height=40,
            command=self.save,
            fg_color=THEME["accent"],
            hover_color=THEME["accent_hover"],
            text_color=THEME["button_text"],
        ).pack(side="right")

        remember_window_geometry(self, "window_viewer_paths", 720, 360)
        self.transient(parent)
        self.grab_set()

    def _path_row(self, parent, row: int, label: str, variable: tk.StringVar):
        ctk.CTkLabel(parent, text=label, font=FONT_SMALL_BOLD, text_color=THEME["muted"]).grid(row=row, column=0, columnspan=3, sticky="w", padx=18, pady=(0, 6))
        entry = ctk.CTkEntry(parent, textvariable=variable, height=38)
        entry.grid(row=row + 1, column=0, sticky="ew", padx=(18, 8), pady=(0, 12))
        ctk.CTkButton(
            parent,
            text="Selecionar",
            width=110,
            height=38,
            command=lambda v=variable, l=label: self.browse(v, l),
            fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"],
        ).grid(row=row + 1, column=1, sticky="e", padx=(0, 8), pady=(0, 12))

    def browse(self, variable: tk.StringVar, title: str):
        current = variable.get().strip()
        initial_dir = str(Path(current).parent) if current and Path(current).parent.exists() else r"C:\Program Files"
        selected = filedialog.askopenfilename(
            parent=self,
            title=f"Selecionar {title}",
            initialdir=initial_dir,
            filetypes=[("Executáveis", "*.exe"), ("Todos os arquivos", "*.*")],
        )
        if selected:
            variable.set(selected)

    def restore_defaults(self):
        self.ultravnc_var.set(ULTRAVNC_EXE)
        self.realvnc_var.set(REALVNC_EXE)

    def save(self):
        self.settings["ultravnc_exe"] = self.ultravnc_var.get().strip() or ULTRAVNC_EXE
        self.settings["realvnc_exe"] = self.realvnc_var.get().strip() or REALVNC_EXE
        save_settings(self.settings)
        audit_log("VIEWER_PATHS_UPDATED", f"ultravnc={self.settings['ultravnc_exe']}; realvnc={self.settings['realvnc_exe']}")
        self.destroy()


# =========================
# Janela Sobre
# =========================
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
            "Uma central de acesso remoto criada para transformar tarefas "
            "repetitivas de suporte em um fluxo mais rápido, organizado e direto. "
            "O VNC-Menu reúne conexões UltraVNC e RealVNC, gerenciamento de hosts "
            "e ferramentas operacionais em uma única interface."
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
            text="Pasta de logs",
            width=145,
            height=38,
            command=self.open_logs_folder,
            fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"],
        ).pack(side="left")

        ctk.CTkButton(
            buttons,
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

        # New geometry key prevents an older oversized About window geometry
        # from overriding this compact layout.
        remember_window_geometry(self, "window_about_v3", 610, 430)

        self.transient(parent)
        self.grab_set()
        self.focus_force()

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


# =========================
# Janela de configurações
# =========================
class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Configurações")
        self.geometry("420x540")
        self.resizable(False, False)
        self.configure(fg_color=THEME["bg"])

        box = ctk.CTkFrame(self, fg_color=THEME["surface"], corner_radius=18)
        box.pack(fill="both", expand=True, padx=18, pady=18)

        ctk.CTkLabel(box, text="Configurações", font=FONT_SUBTITLE, text_color=THEME["text"]).pack(anchor="w", padx=18, pady=(18, 8))
        ctk.CTkLabel(box, text="Acesse as opções principais do VNC-Menu.", font=FONT_NORMAL, text_color=THEME["muted"]).pack(anchor="w", padx=18, pady=(0, 18))

        actions = [
            ("Credenciais", parent.open_creds),
            ("Hosts VNC", parent.open_config),
            ("Lista de Hosts", parent.open_hosts_source_config),
            ("Caminhos dos Viewers", parent.open_viewer_paths),
            ("Colunas dos Hosts", parent.open_host_columns_config),
            ("Alternar modo escuro", parent.toggle_dark_mode),
            ("Sobre o VNC-Menu", parent.open_about),
        ]
        for text, cmd in actions:
            ctk.CTkButton(
                box,
                text=text,
                command=lambda c=cmd: self.run_and_close(c),
                height=40,
                fg_color=THEME["surface_3"],
                hover_color=THEME["accent_soft"],
                text_color=THEME["text"],
            ).pack(fill="x", padx=18, pady=(0, 10))

        ctk.CTkButton(
            box,
            text="Fechar",
            command=self.destroy,
            fg_color=THEME["accent"],
            hover_color=THEME["accent_hover"],
            text_color=THEME["button_text"],
            height=40,
        ).pack(fill="x", padx=18, pady=(8, 18))
        remember_window_geometry(self, "window_settings", 420, 540)
        self.transient(parent)
        self.grab_set()

    def run_and_close(self, command):
        try:
            save_window_geometry(self, "window_settings")
            self.grab_release()
        except Exception:
            pass
        self.destroy()
        self.parent.after(80, command)


# =========================
# Janela principal
# =========================
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("VNC-Menu")
        self.minsize(900, 560)

        self.settings = load_settings()
        initial_width, initial_height = self.get_saved_main_window_size()
        self.geometry(f"{initial_width}x{initial_height}")
        self._main_geometry_save_after = None

        self.dark_mode = bool(self.settings.get("dark_mode", True))
        apply_color_theme(self.dark_mode)
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
        self.mode = tk.StringVar(value="connect")

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.build_sidebar()
        self.build_main_panel()
        self.update_window_title()
        self.refresh_all()
        self.set_mode("connect")
        restore_window_geometry(self, "main", initial_width, initial_height)

        self.bind("<Configure>", self.schedule_main_window_size_save)
        self.protocol("WM_DELETE_WINDOW", self.on_main_close)

    def get_saved_main_window_size(self):
        geometry = get_window_geometries(self.settings).get("main")
        if geometry and is_valid_geometry(str(geometry)):
            width, height = get_geometry_size(str(geometry), 980, 610)
            return max(900, width), max(560, height)

        raw = str(self.settings.get("main_window_size") or "980x610").lower().strip()
        try:
            width_text, height_text = raw.split("x", 1)
            width = max(900, int(width_text))
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
            values=self.unit_names,
            variable=self.selected_unit,
            command=lambda _v: self.on_main_unit_changed(),
            fg_color=THEME["surface_3"],
            button_color=THEME["accent_soft"],
            button_hover_color=THEME["accent_hover"],
            text_color=THEME["button_text"],
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
            text="Configurações",
            height=42,
            command=self.open_settings,
            fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"],
        ).pack(fill="x", padx=20, pady=(0, 20))

    def build_main_panel(self):
        self.main = ctk.CTkFrame(self, fg_color=THEME["surface"], corner_radius=22)
        self.main.grid(row=0, column=1, sticky="nsew", padx=(0, 18), pady=18)
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(self.main, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=22, pady=(22, 16))
        top.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(top, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(title_box, text="Acesso remoto", font=FONT_SUBTITLE, text_color=THEME["text"]).pack(anchor="w")
        self.context_label = ctk.CTkLabel(title_box, text="", font=FONT_NORMAL, text_color=THEME["muted"])
        self.context_label.pack(anchor="w", pady=(2, 0))

        actions = ctk.CTkFrame(top, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e")

        self.btn_connect = ctk.CTkButton(
            actions,
            text="Conectar",
            width=110,
            height=38,
            command=lambda: self.set_mode("connect"),
            text_color=THEME["button_text"],
        )
        self.btn_connect.pack(side="left", padx=(0, 8))
        self.btn_connect.bind("<Double-Button-1>", lambda _event: self.connect_custom_host())

        self.btn_restart = ctk.CTkButton(
            actions,
            text="Reiniciar",
            width=110,
            height=38,
            command=lambda: self.set_mode("restart"),
            text_color=THEME["button_text"],
        )
        self.btn_restart.pack(side="left", padx=(0, 8))
        self.btn_restart.bind("<Double-Button-1>", lambda _event: self.restart_custom_host())

        self.btn_users = ctk.CTkButton(
            actions,
            text="Usuários",
            width=110,
            height=38,
            command=self.show_qwinsta_users,
            fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"],
        )
        self.btn_users.pack(side="left")

        hint = ctk.CTkFrame(self.main, fg_color=THEME["surface_2"], corner_radius=16)
        hint.grid(row=1, column=0, sticky="ew", padx=22, pady=(0, 16))
        hint.grid_columnconfigure(0, weight=1)
        self.mode_label = ctk.CTkLabel(hint, text="", font=FONT_NORMAL, text_color=THEME["muted"], anchor="w")
        self.mode_label.grid(row=0, column=0, sticky="ew", padx=16, pady=12)
        ctk.CTkButton(
            hint,
            text="Host manual",
            width=120,
            height=32,
            command=self.run_custom_host_action,
            fg_color=THEME["surface_3"],
            hover_color=THEME["accent_soft"],
            text_color=THEME["secondary_button_text"],
        ).grid(row=0, column=1, padx=12, pady=10)

        self.host_grid = ctk.CTkScrollableFrame(self.main, fg_color=THEME["bg"], corner_radius=18)
        self.host_grid.grid(row=2, column=0, sticky="nsew", padx=22, pady=(0, 18))

        self.footer = ctk.CTkFrame(self.main, fg_color="transparent")
        self.footer.grid(row=3, column=0, sticky="ew", padx=22, pady=(0, 18))

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

    def set_mode(self, mode):
        self.mode.set(mode)
        if mode == "connect":
            self.btn_connect.configure(fg_color=THEME["accent"], hover_color=THEME["accent_hover"], text_color=THEME["button_text"])
            self.btn_restart.configure(fg_color=THEME["surface_3"], hover_color=THEME["accent_soft"], text_color=THEME["secondary_button_text"])
            self.mode_label.configure(text="Modo atual: conectar ao host selecionado.")
        else:
            self.btn_connect.configure(fg_color=THEME["surface_3"], hover_color=THEME["accent_soft"], text_color=THEME["secondary_button_text"])
            self.btn_restart.configure(fg_color=THEME["warning"], hover_color=THEME["warning_hover"], text_color=THEME["button_text"])
            self.mode_label.configure(text="Modo atual: reiniciar o host selecionado. A confirmação será solicitada.")

    def toggle_dark_mode(self):
        self.dark_mode = not self.dark_mode
        self.settings["dark_mode"] = self.dark_mode
        save_settings(self.settings)
        audit_log("DARK_MODE_CHANGED", f"enabled={self.dark_mode}")

        # Repaint after the current callback returns. This avoids freezing when the
        # command was triggered from a modal settings window.
        self.after(80, self.apply_theme_repaint)

    def apply_theme_repaint(self):
        apply_color_theme(self.dark_mode)
        self.configure(fg_color=THEME["bg"])

        current_mode = self.mode.get()
        try:
            self.sidebar.destroy()
            self.main.destroy()
        except Exception:
            pass

        self.build_sidebar()
        self.build_main_panel()
        self.refresh_all()
        self.set_mode(current_mode)

    def refresh_all(self):
        self.refresh_unit_menu()
        self.refresh_sectors()
        self.render_hosts()
        self.update_window_title()

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
            selected = name == self.selected_sector.get()
            btn = ctk.CTkButton(
                self.sector_frame,
                text=name,
                anchor="w",
                height=38,
                fg_color=THEME["accent_soft"] if selected else THEME["surface_2"],
                hover_color=THEME["accent_soft"],
                text_color=THEME["text"],
                command=lambda n=name: self.set_sector(n),
            )
            btn.pack(fill="x", padx=8, pady=5)

    def render_hosts(self):
        for child in self.host_grid.winfo_children():
            child.destroy()

        hosts = get_sector_hosts(self.hosts_data, self.selected_unit.get(), self.selected_sector.get())
        self.context_label.configure(text=f"{self.selected_unit.get()} > {self.selected_sector.get()}")
        self.count_label.configure(text=f"{len(hosts)} host(s) encontrado(s)")
        self.source_label.configure(text=f"Lista: {hosts_source_display_name(self.hosts_source)}")

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
                    command=lambda n=item.get("name"), h=item.get("host"), v=item.get("viewer", DEFAULT_VIEWER): self.run_host_action(n, h, v),
                )
                card.pack(fill="both", expand=True)
                card.bind(
                    "<Button-3>",
                    lambda event, h=item.get("host"): self.show_host_context_menu(event, h),
                    add="+",
                )

            missing = cols - len(row_hosts)
            for _ in range(missing):
                spacer = ctk.CTkFrame(row_frame, fg_color="transparent", height=44)
                spacer.pack(side="left", fill="x", expand=True, padx=6)
                spacer.pack_propagate(False)


    def on_main_unit_changed(self):
        sector_names = get_sector_names(self.hosts_data, self.selected_unit.get()) or ["Geral"]
        self.selected_sector.set(sector_names[0])
        self.save_main_selection()
        self.refresh_sectors()
        self.render_hosts()

    def set_sector(self, sector_name):
        self.selected_sector.set(sector_name)
        self.save_main_selection()
        self.refresh_sectors()
        self.render_hosts()

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
        host = str(host or "").strip().lstrip("\\\\")
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

    def show_host_context_menu(self, event, host):
        host = str(host or "").strip()
        if not host:
            return

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

        def open_folder():
            close_menu()
            self.open_host_admin_share(host)

        menu.add_command(label="Copiar IP", command=copy_ip)
        menu.add_command(label="Abrir pasta", command=open_folder)

        # post() leaves the menu active until the user selects an item or clicks
        # elsewhere. Do not destroy it in a finally block.
        menu.post(event.x_root, event.y_root)
        menu.focus_set()

    def run_host_action(self, name, host, viewer=DEFAULT_VIEWER):
        if self.mode.get() == "connect":
            launch_vnc(host, viewer, name, self.selected_sector.get(), self)
            return

        if confirm_action(self, "Confirmar reinício", f"Reiniciar:\n{name}?"):
            try:
                restart_host(host)
            except Exception as e:
                show_error(self, "Erro", f"Falha ao reiniciar host:\n{e}\n\nLog: {ERROR_LOG}")

    def run_custom_host_action(self):
        if self.mode.get() == "restart":
            self.restart_custom_host()
            return
        self.connect_custom_host()

    def connect_custom_host(self):
        result = ask_custom_connection(self)
        if not result:
            return
        host, viewer = result
        launch_vnc(host, viewer, parent=self, auto_credentials=False)

    def restart_custom_host(self):
        target = ask_text(self, "Reiniciar host", "Digite o hostname ou IP:")
        if not target:
            return
        if confirm_action(self, "Confirmar reinício", f"Reiniciar:\n{target}?"):
            try:
                restart_host(target)
            except Exception as e:
                show_error(self, "Erro", f"Falha ao reiniciar host:\n{e}\n\nLog: {ERROR_LOG}")

    def reload_hosts_from_current_source(self):
        self.hosts_source = normalize_hosts_source(self.settings.get("hosts_source")) or HOSTS_SOURCE_SHARED
        self.hosts_path = get_hosts_path_for_source(self.hosts_source)
        self.hosts_data = load_hosts_data(self.hosts_path)
        self.refresh_all()

    def update_window_title(self):
        self.title(f"VNC-Menu [{hosts_source_display_name(self.hosts_source)}]")

    def open_settings(self):
        SettingsWindow(self)

    def open_about(self):
        AboutWindow(self)

    def open_hosts_source_config(self):
        source = choose_hosts_source_dialog(self, required=False)
        if not source:
            return
        set_hosts_source(self.settings, source, overwrite_user_file=True)
        audit_log("HOSTS_SOURCE_CHANGED_BY_USER", f"source={hosts_source_display_name(source)}; file={self.settings.get('hosts_file', '')}")
        self.reload_hosts_from_current_source()

    def open_config(self):
        if normalize_hosts_source(self.settings.get("hosts_source")) == HOSTS_SOURCE_SHARED:
            choice = shared_hosts_edit_warning(self)
            audit_log("SHARED_HOSTS_EDIT_PROMPT", f"choice={choice}; file={self.hosts_path}")
            if choice == "cancel":
                return
            if choice == "copy":
                set_hosts_source(self.settings, HOSTS_SOURCE_CUSTOM, overwrite_user_file=True)
                self.reload_hosts_from_current_source()

        HostUnitsConfigWindow(self, self.hosts_data, self.on_hosts_saved, self.hosts_path)

    def open_creds(self):
        CredsWindow(self)

    def open_viewer_paths(self):
        ViewerPathsWindow(self)

    def open_host_columns_config(self):
        current = str(self.host_columns)
        value = ask_text(
            self,
            "Colunas dos Hosts",
            "Digite quantas colunas deseja mostrar na tela principal.\nValor permitido: 1 a 6.",
            current,
        )
        if value is None:
            return

        try:
            columns = int(value.strip())
        except Exception:
            show_warning(self, "Colunas dos Hosts", "Digite um número válido entre 1 e 6.")
            return

        if columns < 1 or columns > 6:
            show_warning(self, "Colunas dos Hosts", "Use um valor entre 1 e 6.")
            return

        self.host_columns = columns
        self.settings["host_columns"] = columns
        save_settings(self.settings)
        audit_log("HOST_COLUMNS_CHANGED", f"columns={columns}")
        self.render_hosts()

    def on_hosts_saved(self, hosts_data):
        self.hosts_data = hosts_data
        self.refresh_all()

    def show_qwinsta_users(self):
        unit_name = self.selected_unit.get()
        sector_name = self.selected_sector.get()
        hosts = [dict(item) for item in get_sector_hosts(self.hosts_data, unit_name, sector_name)]
        label = f"{unit_name} > {sector_name}"

        if not hosts:
            show_text_window(self, "Usuários logados", f"Setor sem hosts ou inexistente: {label}")
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

                show_text_window(self, f"Usuários logados - {label}", result)

            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    try:
        App().mainloop()
    except Exception as e:
        log_exception(e)
        messagebox.showerror("Erro", f"O app falhou ao iniciar:\n{e}\n\nLog: {ERROR_LOG}")
