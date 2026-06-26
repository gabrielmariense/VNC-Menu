import base64
import getpass
import ctypes
import json
import shutil
import subprocess
import tempfile
import time
import traceback
from ctypes import wintypes
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from pywinauto import Desktop
from pywinauto.keyboard import send_keys


# =========================
# Static config
# =========================
ULTRAVNC_EXE = r"C:\Program Files\uvnc bvba\UltraVNC\vncviewer.exe"
REALVNC_EXE = r"C:\Program Files\RealVNC\VNC Viewer\vncviewer.exe"
PORT = 5900

VIEWER_ULTRAVNC = "ultravnc"
VIEWER_REALVNC = "realvnc"
VIEWER_OPTIONS = [VIEWER_ULTRAVNC, VIEWER_REALVNC]
DEFAULT_VIEWER = VIEWER_ULTRAVNC

AUTH_TIMEOUT = 12
AUTH_TITLE_RE = r".*(UltraVNC|VNC).*(Auth|Authentication).*"

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "_internal" if (SCRIPT_DIR / "_internal").exists() else SCRIPT_DIR
DATA_DIR.mkdir(exist_ok=True)

# Shared application data stays beside the program.
SHARED_HOSTS_JSON = DATA_DIR / "hosts.json"
TEMPLATE_VNC = DATA_DIR / "template.vnc"
REALVNC_DIR = DATA_DIR / "realvnc"
REALVNC_DIR.mkdir(exist_ok=True)

# Per-user data is stored in Documents\VNC-Menu so multiple Windows users can
# use the same installation while keeping separate settings and credentials.
USER_DATA_DIR = Path.home() / "Documents" / "VNC-Menu"
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

USER_HOSTS_JSON = USER_DATA_DIR / "hosts.json"
CREDS_JSON = USER_DATA_DIR / "creds.json"
SETTINGS_JSON = USER_DATA_DIR / "settings.json"

# Logs are stored beside the app/exe, one file per Windows user.
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


# Small placeholder list used when no hosts.json exists or when the user chooses a blank list.
DEFAULT_HOSTS = {
    "units": [
        {
            "name": "Geral",
            "sectors": [
                {
                    "name": "Geral",
                    "hosts": [
                        {"name": "Example Host 01", "host": "demo-host.local"},
                        {"name": "Example Host 02", "host": "192.0.2.10"},
                    ],
                }
            ],
        }
    ]
}

DEFAULT_SETTINGS = {
    "dark_mode": False,
    "hosts_source": "",
    "hosts_file": "",
    "selected_unit": "Geral",
    "selected_sector": "Geral",
    "window_positions": {},
}

HOSTS_SOURCE_SHARED = "padrao"
HOSTS_SOURCE_CUSTOM = "personalizada"
HOSTS_SOURCE_EMPTY = "vazia"
HOSTS_SOURCE_OPTIONS = {HOSTS_SOURCE_SHARED, HOSTS_SOURCE_CUSTOM, HOSTS_SOURCE_EMPTY}


# =========================
# UI style
# =========================
UI_FONT = ("Segoe UI", 10, "bold")
UI_FONT_TABLE = ("Segoe UI", 10, "bold")

UI_BUTTON_PADX = 8
UI_BUTTON_PADY = 4

UI_STYLE = {
    "dark": {
        "bg": "#101820",
        "fg": "#eef7ff",
        "button_bg": "#243447",
        "button_hover": "#35506a",
        "button_active": "#4b6f91",
        "selected_bg": "#3f6382",
        "entry_bg": "#172331",
        "table_bg": "#172331",
        "table_heading": "#203247",
        "table_selected": "#41627f",
        "border": "#5b7f9d",
    },
    "light": {
        "bg": "#f2f6fa",
        "fg": "#14202b",
        "button_bg": "#d7e5f2",
        "button_hover": "#c2d8ec",
        "button_active": "#accae4",
        "selected_bg": "#a6c8e8",
        "entry_bg": "#ffffff",
        "table_bg": "#ffffff",
        "table_heading": "#d7e5f2",
        "table_selected": "#6ea8dc",
        "border": "#7fa6c6",
    },
}


def get_ui_palette(dark_mode: bool) -> dict[str, str]:
    return UI_STYLE["dark"] if dark_mode else UI_STYLE["light"]


def bind_hover(widget, normal_bg: str, hover_bg: str):
    setattr(widget, "_hover_normal_bg", normal_bg)
    setattr(widget, "_hover_bg", hover_bg)

    if getattr(widget, "_hover_bound", False):
        return

    def on_enter(_event):
        try:
            widget.configure(bg=getattr(widget, "_hover_bg", hover_bg))
        except Exception:
            pass

    def on_leave(_event):
        try:
            widget.configure(bg=getattr(widget, "_hover_normal_bg", normal_bg))
        except Exception:
            pass

    widget.bind("<Enter>", on_enter, add="+")
    widget.bind("<Leave>", on_leave, add="+")
    setattr(widget, "_hover_bound", True)


def set_button_normal_bg(widget, bg: str):
    setattr(widget, "_hover_normal_bg", bg)


# =========================
# General helpers
# =========================
def log_exception(_: Exception | None = None):
    try:
        ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        ERROR_LOG.write_text(traceback.format_exc(), encoding="utf-8")
    except Exception:
        pass


# Append a per-user audit line to the app logs folder.
def audit_log(action: str, details: str = ""):
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


# Resize window to requested content size and keep/restore its last position.
def center_window(win):
    win.update_idletasks()

    w = max(win.winfo_reqwidth(), 1)
    h = max(win.winfo_reqheight(), 1)

    x = 0
    y = 0

    key = None
    try:
        key = win.title() or win.__class__.__name__
    except Exception:
        key = win.__class__.__name__

    if getattr(win, "_position_managed", False):
        x = max(0, win.winfo_x())
        y = max(0, win.winfo_y())
    else:
        settings = load_settings()
        positions = settings.get("window_positions", {})
        saved = positions.get(key) if isinstance(positions, dict) else None

        if isinstance(saved, dict) and "x" in saved and "y" in saved:
            try:
                x = int(saved["x"])
                y = int(saved["y"])
            except Exception:
                saved = None

        if not isinstance(saved, dict):
            sw = win.winfo_screenwidth()
            sh = win.winfo_screenheight()
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 2)

        def save_position(event=None):
            try:
                if event is not None and event.widget is not win:
                    return

                settings = load_settings()
                positions = settings.get("window_positions", {})
                if not isinstance(positions, dict):
                    positions = {}

                positions[key] = {
                    "x": int(win.winfo_x()),
                    "y": int(win.winfo_y()),
                }

                settings["window_positions"] = positions
                save_settings(settings)
            except Exception:
                pass

        win.bind("<Destroy>", save_position, add="+")
        win._position_managed = True

    win.geometry(f"{w}x{h}+{x}+{y}")


def safe_filename(s: str) -> str:
    for ch in ["\\", "/", ":", "*", "?", '"', "<", ">", "|"]:
        s = s.replace(ch, "_")
    return s


def realvnc_profile_name(sector_name: str | None, host_name: str) -> str:
    if sector_name:
        return safe_filename(f"{sector_name}_{host_name}") + ".vnc"
    return safe_filename(host_name) + ".vnc"


def realvnc_profile_path(sector_name: str | None, host_name: str) -> Path:
    return REALVNC_DIR / realvnc_profile_name(sector_name, host_name)


def rename_realvnc_profile(old_sector: str | None, old_name: str, new_sector: str | None, new_name: str, parent=None):
    old_path = realvnc_profile_path(old_sector, old_name)
    new_path = realvnc_profile_path(new_sector, new_name)

    if old_path == new_path or not old_path.exists():
        return

    try:
        if new_path.exists():
            audit_log("REALVNC_PROFILE_RENAME_BLOCKED", f"from={old_path}; to={new_path}; reason=destination_exists")
            if parent is not None:
                messagebox.showwarning(
                    "Perfil RealVNC",
                    f"Não foi possível renomear o perfil RealVNC porque o destino já existe:\n\n{new_path}",
                )
            return

        new_path.parent.mkdir(exist_ok=True)
        old_path.rename(new_path)
        audit_log("REALVNC_PROFILE_RENAME", f"from={old_path}; to={new_path}")

    except Exception as e:
        if parent is not None:
            messagebox.showerror("Erro", f"Falha ao renomear perfil RealVNC:\n{e}")


def rename_realvnc_profiles_for_sector(old_sector: str, new_sector: str, hosts, parent=None):
    for host in hosts:
        if not isinstance(host, dict):
            continue

        if sanitize_viewer(host.get("viewer", DEFAULT_VIEWER)) != VIEWER_REALVNC:
            continue

        name = str(host.get("name", "")).strip()
        if not name:
            continue

        rename_realvnc_profile(old_sector, name, new_sector, name, parent)


def get_dark_mode(widget) -> bool:
    current = widget
    while current is not None:
        if hasattr(current, "dark_mode"):
            return bool(current.dark_mode)
        try:
            current = current.master
        except Exception:
            break
    return False


def apply_theme_to_window(win, dark_mode):
    p = get_ui_palette(dark_mode)

    bg = p["bg"]
    fg = p["fg"]
    btn_bg = p["button_bg"]
    hover_bg = p["button_hover"]
    active_bg = p["button_active"]
    entry_bg = p["entry_bg"]
    select_bg = p["table_selected"]
    border = p["border"]

    def apply_recursive(widget):
        try:
            if isinstance(widget, (tk.Tk, tk.Toplevel, tk.Frame, tk.LabelFrame)):
                widget.configure(bg=bg)

            elif isinstance(widget, tk.Label):
                widget.configure(bg=bg, fg=fg, font=UI_FONT)

            elif isinstance(widget, (tk.Button, tk.Menubutton, tk.OptionMenu)):
                widget.configure(
                    bg=btn_bg,
                    fg=fg,
                    activebackground=active_bg,
                    activeforeground=fg,
                    highlightbackground=border,
                    highlightcolor=border,
                    highlightthickness=1,
                    relief="raised",
                    bd=1,
                    font=UI_FONT,
                    padx=UI_BUTTON_PADX,
                    pady=UI_BUTTON_PADY,
                )
                bind_hover(widget, btn_bg, hover_bg)

                if isinstance(widget, tk.OptionMenu):
                    try:
                        menu = widget["menu"]
                        menu.configure(
                            bg=btn_bg,
                            fg=fg,
                            activebackground=hover_bg,
                            activeforeground=fg,
                            font=UI_FONT,
                            relief="flat",
                            bd=0,
                        )
                    except Exception:
                        pass

            elif isinstance(widget, tk.Entry):
                widget.configure(
                    bg=entry_bg,
                    fg=fg,
                    insertbackground=fg,
                    font=UI_FONT,
                    relief="solid",
                    bd=1,
                    highlightbackground=border,
                    highlightcolor=border,
                    highlightthickness=1,
                )

            elif isinstance(widget, tk.Text):
                widget.configure(
                    bg=entry_bg,
                    fg=fg,
                    insertbackground=fg,
                    font=("Consolas", 10, "bold"),
                    relief="solid",
                    bd=1,
                    highlightbackground=border,
                    highlightcolor=border,
                    highlightthickness=1,
                )

            elif isinstance(widget, tk.Listbox):
                widget.configure(
                    bg=entry_bg,
                    fg=fg,
                    selectbackground=select_bg,
                    selectforeground="#ffffff",
                    font=UI_FONT,
                    relief="solid",
                    bd=1,
                    highlightbackground=border,
                    highlightcolor=border,
                    highlightthickness=1,
                )

            elif isinstance(widget, (tk.Checkbutton, tk.Radiobutton)):
                widget.configure(
                    bg=bg,
                    fg=fg,
                    activebackground=bg,
                    activeforeground=fg,
                    selectcolor=entry_bg,
                    font=UI_FONT,
                    highlightbackground=bg,
                )
        except Exception:
            pass

        for child in widget.winfo_children():
            apply_recursive(child)

    apply_recursive(win)


def apply_treeview_theme(tree, dark_mode):
    style = ttk.Style(tree)
    p = get_ui_palette(dark_mode)

    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure(
        "HostTable.Treeview",
        background=p["table_bg"],
        fieldbackground=p["table_bg"],
        foreground=p["fg"],
        bordercolor=p["border"],
        lightcolor=p["border"],
        darkcolor=p["border"],
        rowheight=24,
        font=UI_FONT_TABLE,
        relief="solid",
        bd=1,
    )
    style.configure(
        "HostTable.Treeview.Heading",
        background=p["table_heading"],
        foreground=p["fg"],
        relief="solid",
        borderwidth=1,
        font=UI_FONT_TABLE,
    )
    style.map(
        "HostTable.Treeview",
        background=[("selected", p["table_selected"])],
        foreground=[("selected", "#ffffff")],
    )

    tree.configure(style="HostTable.Treeview")


def confirm_action(parent, title, message):
    result = tk.BooleanVar(value=False)

    win = tk.Toplevel(parent)
    win.title(title)
    win.resizable(False, False)
    win.transient(parent)
    win.grab_set()

    frame = tk.Frame(win, padx=18, pady=16)
    frame.pack()

    tk.Label(frame, text=message, font=UI_FONT, justify="left").pack(anchor="w", pady=(0, 14))

    btns = tk.Frame(frame)
    btns.pack()

    def yes():
        result.set(True)
        win.destroy()

    def no():
        win.destroy()

    tk.Button(btns, text="Sim", width=12, command=yes).pack(side="left", padx=6)
    tk.Button(btns, text="Não", width=12, command=no).pack(side="left", padx=6)

    apply_theme_to_window(win, get_dark_mode(parent))
    center_window(win)

    parent.wait_window(win)
    return result.get()


def ask_text(parent, title, label, initial=""):
    result = tk.StringVar(value="")

    win = tk.Toplevel(parent)
    win.title(title)
    win.resizable(False, False)
    win.transient(parent)
    win.grab_set()

    frame = tk.Frame(win, padx=18, pady=16)
    frame.pack()

    tk.Label(frame, text=label, font=UI_FONT).pack(anchor="w", pady=(0, 8))
    entry = tk.Entry(frame, width=38)
    entry.pack()
    entry.insert(0, initial)
    entry.select_range(0, tk.END)
    entry.focus_set()

    btns = tk.Frame(frame)
    btns.pack(pady=(14, 0))

    def ok():
        result.set(entry.get().strip())
        win.destroy()

    def cancel():
        result.set("")
        win.destroy()

    entry.bind("<Return>", lambda _event: ok())
    entry.bind("<Escape>", lambda _event: cancel())

    tk.Button(btns, text="OK", width=12, command=ok).pack(side="left", padx=6)
    tk.Button(btns, text="Cancelar", width=12, command=cancel).pack(side="left", padx=6)

    apply_theme_to_window(win, get_dark_mode(parent))
    center_window(win)

    parent.wait_window(win)
    value = result.get().strip()
    return value if value else None


def ask_host_details(parent, title, initial=None) -> dict[str, str] | None:
    initial = initial or {}
    result: dict[str, dict[str, str] | None] = {"value": None}

    win = tk.Toplevel(parent)
    win.title(title)
    win.resizable(False, False)
    win.transient(parent)
    win.grab_set()

    frame = tk.Frame(win, padx=16, pady=14)
    frame.pack()

    tk.Label(frame, text="Nome:", font=("Segoe UI", 10)).grid(row=0, column=0, sticky="w", pady=(0, 6))
    e_name = tk.Entry(frame, width=38)
    e_name.grid(row=0, column=1, pady=(0, 6))
    e_name.insert(0, str(initial.get("name", "")))

    tk.Label(frame, text="Host/IP:", font=("Segoe UI", 10)).grid(row=1, column=0, sticky="w", pady=(0, 6))
    e_host = tk.Entry(frame, width=38)
    e_host.grid(row=1, column=1, pady=(0, 6))
    e_host.insert(0, str(initial.get("host", "")))

    tk.Label(frame, text="Viewer:", font=("Segoe UI", 10)).grid(row=2, column=0, sticky="w", pady=(0, 6))
    selected_viewer = tk.StringVar(value=sanitize_viewer(initial.get("viewer", DEFAULT_VIEWER)))
    viewer_menu = tk.OptionMenu(frame, selected_viewer, *VIEWER_OPTIONS)
    viewer_menu.config(width=34)
    viewer_menu.grid(row=2, column=1, sticky="we", pady=(0, 6))

    btns = tk.Frame(frame)
    btns.grid(row=3, column=0, columnspan=2, pady=(12, 0))

    def ok():
        name = e_name.get().strip()
        host = e_host.get().strip()
        if not name or not host:
            result["value"] = None
        else:
            result["value"] = {
                "name": name,
                "host": host,
                "viewer": sanitize_viewer(selected_viewer.get()),
            }
        win.destroy()

    def cancel():
        result["value"] = None
        win.destroy()

    e_name.bind("<Return>", lambda _event: ok())
    e_host.bind("<Return>", lambda _event: ok())
    e_name.bind("<Escape>", lambda _event: cancel())
    e_host.bind("<Escape>", lambda _event: cancel())

    tk.Button(btns, text="OK", width=10, command=ok).pack(side="left", padx=4)
    tk.Button(btns, text="Cancelar", width=10, command=cancel).pack(side="left", padx=4)

    e_name.focus_set()
    e_name.select_range(0, tk.END)

    apply_theme_to_window(win, get_dark_mode(parent))
    center_window(win)

    parent.wait_window(win)
    return result["value"]


def ask_custom_connection(parent) -> tuple[str, str] | None:
    result: dict[str, tuple[str, str] | None] = {"value": None}

    win = tk.Toplevel(parent)
    win.title("Conectar host customizado")
    win.resizable(False, False)
    win.transient(parent)
    win.grab_set()

    frame = tk.Frame(win, padx=16, pady=14)
    frame.pack()

    tk.Label(frame, text="Host/IP:", font=("Segoe UI", 10)).grid(row=0, column=0, sticky="w", pady=(0, 6))
    e_host = tk.Entry(frame, width=38)
    e_host.grid(row=0, column=1, pady=(0, 6))

    tk.Label(frame, text="Viewer:", font=("Segoe UI", 10)).grid(row=1, column=0, sticky="w", pady=(0, 6))
    selected_viewer = tk.StringVar(value=DEFAULT_VIEWER)
    viewer_menu = tk.OptionMenu(frame, selected_viewer, *VIEWER_OPTIONS)
    viewer_menu.config(width=34)
    viewer_menu.grid(row=1, column=1, sticky="we", pady=(0, 6))

    btns = tk.Frame(frame)
    btns.grid(row=2, column=0, columnspan=2, pady=(12, 0))

    def ok():
        host = e_host.get().strip()
        if host:
            result["value"] = (host, sanitize_viewer(selected_viewer.get()))
        win.destroy()

    def cancel():
        result["value"] = None
        win.destroy()

    e_host.bind("<Return>", lambda _event: ok())
    e_host.bind("<Escape>", lambda _event: cancel())

    tk.Button(btns, text="Conectar", width=10, command=ok).pack(side="left", padx=4)
    tk.Button(btns, text="Cancelar", width=10, command=cancel).pack(side="left", padx=4)

    e_host.focus_set()

    apply_theme_to_window(win, get_dark_mode(parent))
    center_window(win)

    parent.wait_window(win)
    return result["value"]


def show_realvnc_profile_dialog(parent, profile_path: Path, profile_name: str):
    win = tk.Toplevel(parent)
    win.title("Perfil RealVNC")
    win.resizable(False, False)
    win.transient(parent)
    win.grab_set()

    frame = tk.Frame(win, padx=16, pady=14)
    frame.pack()

    msg = (
        "Perfil RealVNC não encontrado ou vazio.\n\n"
        "Nome esperado:\n"
        f"{profile_name}\n\n"
        "Caminho:\n"
        f"{profile_path}"
    )

    tk.Label(frame, text=msg, font=UI_FONT, justify="left").pack(anchor="w", pady=(0, 12))

    btns = tk.Frame(frame)
    btns.pack(pady=(4, 0))

    def create_file():
        try:
            profile_path.parent.mkdir(exist_ok=True)
            profile_path.touch(exist_ok=True)
            win.destroy()
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao criar arquivo:\n{e}")

    def copy_name():
        try:
            parent.clipboard_clear()
            parent.clipboard_append(Path(profile_name).stem)
            parent.update()
        except Exception:
            pass
        win.destroy()

    tk.Button(btns, text="Criar arquivo", width=14, command=create_file).pack(side="left", padx=4)
    tk.Button(btns, text="Copiar nome", width=14, command=copy_name).pack(side="left", padx=4)

    apply_theme_to_window(win, get_dark_mode(parent))
    center_window(win)

    parent.wait_window(win)


# =========================
# DPAPI helpers
# =========================
class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


crypt32 = ctypes.windll.crypt32
kernel32 = ctypes.windll.kernel32

crypt32.CryptProtectData.argtypes = [
    ctypes.POINTER(DATA_BLOB),
    wintypes.LPCWSTR,
    ctypes.POINTER(DATA_BLOB),
    wintypes.LPVOID,
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(DATA_BLOB),
]
crypt32.CryptProtectData.restype = wintypes.BOOL

crypt32.CryptUnprotectData.argtypes = [
    ctypes.POINTER(DATA_BLOB),
    ctypes.POINTER(wintypes.LPWSTR),
    ctypes.POINTER(DATA_BLOB),
    wintypes.LPVOID,
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(DATA_BLOB),
]
crypt32.CryptUnprotectData.restype = wintypes.BOOL

kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
kernel32.LocalFree.restype = wintypes.HLOCAL


def _bytes_to_blob(data: bytes) -> DATA_BLOB:
    buf = (ctypes.c_byte * len(data)).from_buffer_copy(data)
    return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))


def _blob_to_bytes(blob: DATA_BLOB) -> bytes:
    cb = int(blob.cbData)
    if cb <= 0 or not blob.pbData:
        return b""
    out = ctypes.string_at(blob.pbData, cb)
    kernel32.LocalFree(ctypes.cast(blob.pbData, wintypes.HLOCAL))
    return out


def dpapi_encrypt(plaintext: str) -> str:
    data_in = _bytes_to_blob(plaintext.encode("utf-8"))
    data_out = DATA_BLOB()

    ok = crypt32.CryptProtectData(
        ctypes.byref(data_in), None, None, None, None, 0, ctypes.byref(data_out)
    )
    if not ok:
        raise ctypes.WinError()

    enc = _blob_to_bytes(data_out)
    return base64.b64encode(enc).decode("ascii")


def dpapi_decrypt(ciphertext_b64: str) -> str:
    enc = base64.b64decode(ciphertext_b64.encode("ascii"))
    data_in = _bytes_to_blob(enc)
    data_out = DATA_BLOB()

    ok = crypt32.CryptUnprotectData(
        ctypes.byref(data_in), None, None, None, None, 0, ctypes.byref(data_out)
    )
    if not ok:
        raise ctypes.WinError()

    plain = _blob_to_bytes(data_out)
    return plain.decode("utf-8")


# =========================
# Storage helpers
# =========================
def save_json(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def sanitize_viewer(value) -> str:
    viewer = str(value or DEFAULT_VIEWER).strip().lower()
    if viewer not in VIEWER_OPTIONS:
        return DEFAULT_VIEWER
    return viewer


def viewer_display_name(viewer: str) -> str:
    viewer = sanitize_viewer(viewer)
    if viewer == VIEWER_REALVNC:
        return "RealVNC"
    return "UltraVNC"


def sanitize_host_list(data):
    out = []
    if not isinstance(data, list):
        return out

    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        host = str(item.get("host", "")).strip()
        viewer = sanitize_viewer(item.get("viewer", DEFAULT_VIEWER))
        if name and host:
            out.append({"name": name, "host": host, "viewer": viewer})
    return out


def sanitize_sector_list(data):
    out = []
    if not isinstance(data, list):
        return out

    seen = set()
    for item in data:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name", "")).strip()
        if not name:
            continue

        key = name.lower()
        if key in seen:
            continue
        seen.add(key)

        out.append({"name": name, "hosts": sanitize_host_list(item.get("hosts", []))})

    return out


# Accept older/simple JSON shapes and convert everything to the current structure.
def normalize_hosts_data(data):
    # v2 compatibility: old flat host list.
    if isinstance(data, list):
        return {
            "units": [
                {
                    "name": "Geral",
                    "sectors": [
                        {
                            "name": "Geral",
                            "hosts": sanitize_host_list(data),
                        }
                    ],
                }
            ]
        }

    # v3 compatibility: {"groups": [{"name": "...", "hosts": [...]}]}
    if isinstance(data, dict) and isinstance(data.get("groups"), list):
        sectors = []
        seen = set()

        for group in data["groups"]:
            if not isinstance(group, dict):
                continue

            name = str(group.get("name", "")).strip()
            if not name:
                continue

            key = name.lower()
            if key in seen:
                continue
            seen.add(key)

            sectors.append({"name": name, "hosts": sanitize_host_list(group.get("hosts", []))})

        if sectors:
            return {"units": [{"name": "Geral", "sectors": sectors}]}

    # v4 format: {"units": [{"name": "...", "sectors": [{"name": "...", "hosts": [...]}]}]}
    if isinstance(data, dict) and isinstance(data.get("units"), list):
        clean_units = []
        seen_units = set()

        for unit in data["units"]:
            if not isinstance(unit, dict):
                continue

            unit_name = str(unit.get("name", "")).strip()
            if not unit_name:
                continue

            unit_key = unit_name.lower()
            if unit_key in seen_units:
                continue
            seen_units.add(unit_key)

            sectors = sanitize_sector_list(unit.get("sectors", []))
            if not sectors:
                sectors = [{"name": "Geral", "hosts": []}]

            clean_units.append({"name": unit_name, "sectors": sectors})

        if clean_units:
            return {"units": clean_units}

    return DEFAULT_HOSTS


def load_hosts_data(path=SHARED_HOSTS_JSON, defaults=DEFAULT_HOSTS):
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            normalized = normalize_hosts_data(data)
            save_json(normalized, path)
            return normalized
        except Exception:
            pass

    save_json(defaults, path)
    return defaults


def get_unit_names(hosts_data):
    return [unit["name"] for unit in hosts_data.get("units", [])]


def get_unit_by_name(hosts_data, unit_name):
    for unit in hosts_data.get("units", []):
        if unit["name"] == unit_name:
            return unit
    return None


def get_sector_names(hosts_data, unit_name):
    unit = get_unit_by_name(hosts_data, unit_name)
    if not unit:
        return []
    return [sector["name"] for sector in unit.get("sectors", [])]


def get_sector_by_name(hosts_data, unit_name, sector_name):
    unit = get_unit_by_name(hosts_data, unit_name)
    if not unit:
        return None

    for sector in unit.get("sectors", []):
        if sector["name"] == sector_name:
            return sector
    return None


def get_sector_hosts(hosts_data, unit_name, sector_name):
    sector = get_sector_by_name(hosts_data, unit_name, sector_name)
    if not sector:
        return []
    return sector["hosts"]


def load_creds() -> tuple[str, str]:
    if not CREDS_JSON.exists():
        return "", ""

    try:
        data = json.loads(CREDS_JSON.read_text(encoding="utf-8"))
        user = (data.get("user") or "").strip()
        enc = (data.get("pass") or "").strip()
        pwd = dpapi_decrypt(enc) if enc else ""
        return user, pwd
    except Exception:
        return "", ""


def save_creds(user: str, pwd: str) -> None:
    payload = {"user": user.strip(), "pass": dpapi_encrypt(pwd) if pwd else ""}
    save_json(payload, CREDS_JSON)


def load_settings():
    if SETTINGS_JSON.exists():
        try:
            data = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                settings = DEFAULT_SETTINGS.copy()
                settings.update(data)

                return settings
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    save_json(settings, SETTINGS_JSON)


def normalize_hosts_source(value) -> str:
    source = str(value or "").strip().lower()
    return source if source in HOSTS_SOURCE_OPTIONS else ""


def hosts_source_display_name(source: str) -> str:
    source = normalize_hosts_source(source)
    if source == HOSTS_SOURCE_CUSTOM:
        return "Personalizada"
    if source == HOSTS_SOURCE_EMPTY:
        return "Vazia"
    if source == HOSTS_SOURCE_SHARED:
        return "Padrão"
    return "Não selecionada"


def get_hosts_path_for_source(source: str) -> Path:
    source = normalize_hosts_source(source)
    if source in (HOSTS_SOURCE_CUSTOM, HOSTS_SOURCE_EMPTY):
        return USER_HOSTS_JSON
    return SHARED_HOSTS_JSON


def update_hosts_file_setting(settings):
    source = normalize_hosts_source(settings.get("hosts_source"))
    if source:
        settings["hosts_source"] = source
        settings["hosts_file"] = str(get_hosts_path_for_source(source))
    else:
        settings["hosts_source"] = ""
        settings["hosts_file"] = ""


def copy_shared_hosts_to_user(overwrite=True):
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    if USER_HOSTS_JSON.exists() and not overwrite:
        return

    if SHARED_HOSTS_JSON.exists():
        shutil.copy2(SHARED_HOSTS_JSON, USER_HOSTS_JSON)
    else:
        save_json(DEFAULT_HOSTS, USER_HOSTS_JSON)


def create_empty_user_hosts(overwrite=True):
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    if USER_HOSTS_JSON.exists() and not overwrite:
        return
    save_json(DEFAULT_HOSTS, USER_HOSTS_JSON)


def prepare_hosts_source_file(settings, overwrite_user_file=False):
    source = normalize_hosts_source(settings.get("hosts_source"))

    if source == HOSTS_SOURCE_CUSTOM:
        copy_shared_hosts_to_user(overwrite=overwrite_user_file or not USER_HOSTS_JSON.exists())
    elif source == HOSTS_SOURCE_EMPTY:
        create_empty_user_hosts(overwrite=overwrite_user_file or not USER_HOSTS_JSON.exists())

    update_hosts_file_setting(settings)
    save_settings(settings)


def set_hosts_source(settings, source: str, overwrite_user_file=True):
    source = normalize_hosts_source(source) or HOSTS_SOURCE_SHARED
    settings["hosts_source"] = source
    prepare_hosts_source_file(settings, overwrite_user_file=overwrite_user_file)
    audit_log(
        "HOSTS_SOURCE_SET",
        f"source={hosts_source_display_name(source)}; file={settings.get('hosts_file', '')}; overwrite_user_file={overwrite_user_file}",
    )


# First-run/settings dialog used to choose between shared, personal, or blank host lists.
def choose_hosts_source_dialog(parent, required=False):
    result = tk.StringVar(value="")

    win = tk.Toplevel(parent)
    win.title("Selecionar lista de hosts")
    win.resizable(False, False)
    win.transient(parent)
    win.grab_set()

    frame = tk.Frame(win, padx=18, pady=16)
    frame.pack()

    msg = (
        "Padrão\n"
        "Usa a lista compartilhada por TODOS os usuários.\n\n"
        "Personalizada\n"
        "Cria uma cópia da lista padrão para este usuário.\n\n"
        "Vazia\n"
        "Cria uma lista em branco nova para este usuário."
    )
    tk.Label(frame, text=msg, font=UI_FONT, justify="left").pack(anchor="w", pady=(0, 14))

    btns = tk.Frame(frame)
    btns.pack()

    def select(source):
        result.set(source)
        win.destroy()

    tk.Button(btns, text="Padrão", width=14, command=lambda: select(HOSTS_SOURCE_SHARED)).pack(side="left", padx=5)
    tk.Button(btns, text="Personalizada", width=14, command=lambda: select(HOSTS_SOURCE_CUSTOM)).pack(side="left", padx=5)
    tk.Button(btns, text="Vazia", width=14, command=lambda: select(HOSTS_SOURCE_EMPTY)).pack(side="left", padx=5)

    if required:
        win.protocol("WM_DELETE_WINDOW", lambda: None)
    else:
        win.protocol("WM_DELETE_WINDOW", win.destroy)

    apply_theme_to_window(win, get_dark_mode(parent))
    center_window(win)

    parent.wait_window(win)
    return normalize_hosts_source(result.get()) or None


def ensure_hosts_source_selected(parent, settings):
    source = normalize_hosts_source(settings.get("hosts_source"))
    if source:
        prepare_hosts_source_file(settings, overwrite_user_file=False)
        return source

    source = choose_hosts_source_dialog(parent, required=True) or HOSTS_SOURCE_SHARED
    set_hosts_source(settings, source, overwrite_user_file=True)
    return source


def shared_hosts_edit_warning(parent):
    result = tk.StringVar(value="cancel")

    try:
        username = getpass.getuser()
    except Exception:
        username = "usuário atual"

    win = tk.Toplevel(parent)
    win.title("Editar lista padrão")
    win.resizable(False, False)
    win.transient(parent)
    win.grab_set()

    frame = tk.Frame(win, padx=18, pady=16)
    frame.pack()

    msg = (
        "A lista Padrão é compartilhada.\n"
        "Qualquer alteração afeta TODOS os usuários deste computador.\n\n"
        "Editar padrão\n"
        "Altera a lista compartilhada.\n\n"
        "Criar cópia\n"
        "Cria uma lista pessoal para este usuário."
    )
    tk.Label(frame, text=msg, font=UI_FONT, justify="left").pack(anchor="w", pady=(0, 14))

    btns = tk.Frame(frame)
    btns.pack()

    def select(value):
        result.set(value)
        win.destroy()

    tk.Button(btns, text="Editar padrão", width=14, command=lambda: select("continue")).pack(side="left", padx=5)
    tk.Button(btns, text="Criar cópia", width=14, command=lambda: select("copy")).pack(side="left", padx=5)
    tk.Button(btns, text="Cancelar", width=14, command=lambda: select("cancel")).pack(side="left", padx=5)

    win.protocol("WM_DELETE_WINDOW", lambda: select("cancel"))

    apply_theme_to_window(win, get_dark_mode(parent))
    center_window(win)

    parent.wait_window(win)
    return result.get()


# =========================
# Actions
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


# Start UltraVNC or RealVNC for the selected host and record the action in the audit log.
def launch_vnc(host: str, viewer: str = DEFAULT_VIEWER, display_name: str | None = None, sector_name: str | None = None, parent=None):
    viewer = sanitize_viewer(viewer)
    target_name = display_name or host
    audit_log(
        "CONNECTION_ATTEMPT",
        f"viewer={viewer_display_name(viewer)}; name={target_name}; host={host}; setor={sector_name or '-'}",
    )

    try:
        if viewer == VIEWER_REALVNC:
            if not Path(REALVNC_EXE).exists():
                audit_log("CONNECTION_ERROR", f"viewer=RealVNC; host={host}; reason=viewer_not_found; path={REALVNC_EXE}")
                messagebox.showerror("Erro", f"RealVNC Viewer não encontrado:\n{REALVNC_EXE}")
                return

            profile_name = realvnc_profile_name(sector_name, display_name or host)
            profile_path = REALVNC_DIR / profile_name

            if profile_path.exists() and profile_path.stat().st_size > 0:
                subprocess.Popen([REALVNC_EXE, str(profile_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                audit_log("CONNECTION_STARTED", f"viewer=RealVNC; name={target_name}; host={host}; profile={profile_path}")
                return

            audit_log("CONNECTION_BLOCKED", f"viewer=RealVNC; name={target_name}; host={host}; reason=profile_missing_or_empty; profile={profile_path}")
            if parent is not None:
                show_realvnc_profile_dialog(parent, profile_path, profile_name)
            else:
                messagebox.showinfo(
                    "Perfil RealVNC",
                    f"Perfil RealVNC não encontrado ou vazio:\n\n{profile_path}",
                )
            return

        if not Path(ULTRAVNC_EXE).exists():
            audit_log("CONNECTION_ERROR", f"viewer=UltraVNC; host={host}; reason=viewer_not_found; path={ULTRAVNC_EXE}")
            messagebox.showerror("Erro", f"UltraVNC Viewer não encontrado:\n{ULTRAVNC_EXE}")
            return

        if not TEMPLATE_VNC.exists():
            audit_log("CONNECTION_ERROR", f"viewer=UltraVNC; host={host}; reason=template_not_found; path={TEMPLATE_VNC}")
            messagebox.showerror("Erro", "template.vnc não encontrado.\nVerifique se ele está na pasta _internal.")
            return

        tmp_vnc = Path(tempfile.gettempdir()) / f"uvnc_{safe_filename(host)}.vnc"
        shutil.copyfile(TEMPLATE_VNC, tmp_vnc)

        cmd = [ULTRAVNC_EXE, "-config", str(tmp_vnc), f"{host}::{PORT}"]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        audit_log("CONNECTION_STARTED", f"viewer=UltraVNC; name={target_name}; host={host}; template={TEMPLATE_VNC}")

        auto_enter_uvnc_credentials()

    except Exception as e:
        audit_log("CONNECTION_ERROR", f"viewer={viewer_display_name(viewer)}; host={host}; error={e}")
        log_exception(e)
        messagebox.showerror("Erro", f"Falha ao iniciar viewer VNC:\n{e}\n\nLog: {ERROR_LOG}")


def restart_host(host: str):
    audit_log("RESTART_ATTEMPT", f"host={host}")
    try:
        subprocess.Popen(
            ["shutdown", "-r", "-f", "-t", "0", "-m", f"\\\\{host}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        audit_log("RESTART_SENT", f"host={host}")
    except Exception as e:
        audit_log("RESTART_ERROR", f"host={host}; error={e}")
        log_exception(e)
        messagebox.showerror("Erro", f"Falha ao reiniciar host:\n{e}\n\nLog: {ERROR_LOG}")


# Optional Windows helper: query logged-in sessions for every host in the current sector.
def query_all_logged_users(hosts):
    rows = []

    for item in hosts:
        name = item["name"]
        host = item["host"]

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

                if len(parts) >= 4:
                    username = parts[1]
                    state = parts[3]

                    if username.lower() not in ("services", "console", "rdp-tcp"):
                        users.append(f"{username}")

            if users:
                rows.append((name, ", ".join(users)))
            else:
                rows.append((name, "VAZIO"))

        except Exception as e:
            rows.append((name, f"ERRO: {e}"))

    return format_users_output(rows)


def format_users_output(rows):
    host_w = max(len("HOST"), *(len(r[0]) for r in rows))

    lines = []
    lines.append(f"{'HOST':<{host_w}}  USUÁRIO")
    lines.append("-" * (host_w + 35))

    for host, user in rows:
        lines.append(f"{host:<{host_w}}  {user}")

    return "\n".join(lines)


# =========================
# UI windows
# =========================
def show_text_window(parent, title, content):
    win = tk.Toplevel(parent)
    win.title(title)
    win.resizable(True, True)
    win.transient(parent)

    lines = content.splitlines()

    max_len = max((len(line) for line in lines), default=40)
    line_count = len(lines)

    # Auto-size based on content, with sane limits
    width = min(max(max_len + 2, 35), 90)
    height = min(max(line_count + 2, 8), 28)

    frame = tk.Frame(win, padx=10, pady=10)
    frame.pack(fill="both", expand=True)

    text = tk.Text(
        frame,
        width=width,
        height=height,
        font=("Consolas", 10, "bold"),
        wrap="none",
    )
    text.pack(fill="both", expand=True)

    text.insert("1.0", content)
    text.config(state="disabled")

    bottom = tk.Frame(frame)
    bottom.pack(pady=(8, 0))

    tk.Button(
        bottom,
        text="Fechar",
        width=12,
        command=win.destroy,
    ).pack()

    apply_theme_to_window(win, get_dark_mode(parent))

    win.update_idletasks()

    req_w = win.winfo_reqwidth()
    req_h = win.winfo_reqheight()

    win.geometry(f"{req_w}x{req_h}")

    center_window(win)


class CredsWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Credenciais")
        self.resizable(False, False)
        self.transient(parent)

        user0, pass0 = load_creds()

        frame = tk.Frame(self, padx=12, pady=12)
        frame.pack()

        tk.Label(frame, text="Usuário:", font=("Segoe UI", 10)).grid(row=0, column=0, sticky="w")
        self.e_user = tk.Entry(frame, width=36)
        self.e_user.grid(row=0, column=1, pady=4)
        self.e_user.insert(0, user0)

        tk.Label(frame, text="Senha:", font=("Segoe UI", 10)).grid(row=1, column=0, sticky="w")
        self.e_pass = tk.Entry(frame, width=36, show="*")
        self.e_pass.grid(row=1, column=1, pady=4)
        self.e_pass.insert(0, pass0)

        btns = tk.Frame(frame)
        btns.grid(row=2, column=0, columnspan=2, pady=(10, 0))

        tk.Button(btns, text="Salvar", width=10, command=self._save).pack(side="left", padx=4)
        tk.Button(btns, text="Fechar", width=10, command=self.destroy).pack(side="left", padx=4)

        self.grab_set()
        self.e_user.focus_set()
        apply_theme_to_window(self, get_dark_mode(parent))
        center_window(self)

    def _save(self):
        try:
            save_creds(self.e_user.get().strip(), self.e_pass.get())
            messagebox.showinfo("OK", "Credenciais salvas.")
            self.destroy()
        except Exception as e:
            log_exception(e)
            messagebox.showerror("Erro", f"Falha ao salvar credenciais:\n{e}\n\nLog: {ERROR_LOG}")


class UnitsWindow(tk.Toplevel):
    def __init__(self, parent, hosts_data, on_change):
        super().__init__(parent)
        self.title("Editar Unidades")
        self.resizable(False, False)
        self.transient(parent)

        self._data = hosts_data
        self._on_change = on_change

        frame = tk.Frame(self, padx=12, pady=12)
        frame.pack()

        tk.Label(frame, text="Unidades:", font=("Segoe UI", 10)).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 6)
        )

        self.listbox = tk.Listbox(frame, width=36, height=10)
        self.listbox.grid(row=1, column=0, columnspan=3, pady=(0, 10), sticky="nsew")

        side = tk.Frame(frame)
        side.grid(row=1, column=3, padx=(10, 0), pady=(0, 10))
        tk.Frame(side).pack(expand=True, fill="both")
        tk.Button(side, text="↑", width=4, command=self.move_up).pack(pady=(0, 6))
        tk.Button(side, text="↓", width=4, command=self.move_down).pack()
        tk.Frame(side).pack(expand=True, fill="both")

        tk.Button(frame, text="Adicionar", width=12, command=self.add_unit).grid(row=2, column=0, pady=4, sticky="w")
        tk.Button(frame, text="Renomear", width=12, command=self.rename_unit).grid(row=2, column=1, pady=4)
        tk.Button(frame, text="Remover", width=12, command=self.delete_unit).grid(row=2, column=2, pady=4, sticky="e")

        bottom = tk.Frame(frame)
        bottom.grid(row=3, column=0, columnspan=4, pady=(12, 0))
        tk.Button(bottom, text="Fechar", width=12, command=self.close).pack(side="left", padx=4)

        self._refresh()
        self.grab_set()
        self.listbox.focus_set()
        apply_theme_to_window(self, get_dark_mode(parent))
        center_window(self)

    def _refresh(self):
        self.listbox.delete(0, tk.END)
        for unit in self._data.get("units", []):
            self.listbox.insert(tk.END, unit["name"])

    def _selected_index(self):
        sel = self.listbox.curselection()
        return sel[0] if sel else None

    def _unit_exists(self, name):
        return any(u["name"].lower() == name.lower() for u in self._data.get("units", []))

    def add_unit(self):
        name = ask_text(self, "Adicionar Unidade", "Nome da unidade:")
        if not name:
            return
        if self._unit_exists(name):
            messagebox.showerror("Erro", "Já existe uma unidade com esse nome.")
            return
        self._data.setdefault("units", []).append(
            {"name": name, "sectors": [{"name": "Geral", "hosts": []}]}
        )
        audit_log("LIST_UNIT_ADD", f"unidade={name}")
        self._refresh()

    def rename_unit(self):
        idx = self._selected_index()
        if idx is None:
            messagebox.showinfo("Renomear", "Selecione uma unidade.")
            return

        current = self._data["units"][idx]["name"]
        name = ask_text(self, "Renomear Unidade", "Nome da unidade:", current)
        if not name:
            return
        if name.lower() != current.lower() and self._unit_exists(name):
            messagebox.showerror("Erro", "Já existe uma unidade com esse nome.")
            return

        self._data["units"][idx]["name"] = name
        audit_log("LIST_UNIT_RENAME", f"from={current}; to={name}")
        self._refresh()
        self.listbox.selection_set(idx)

    def delete_unit(self):
        idx = self._selected_index()
        if idx is None:
            messagebox.showinfo("Remover", "Selecione uma unidade.")
            return
        if len(self._data.get("units", [])) <= 1:
            messagebox.showerror("Erro", "É necessário manter pelo menos uma unidade.")
            return

        name = self._data["units"][idx]["name"]
        if confirm_action(self, "Confirmar", f"Remover unidade?\n\n{name}"):
            self._data["units"].pop(idx)
            audit_log("LIST_UNIT_DELETE", f"unidade={name}")
            self._refresh()

    def move_up(self):
        idx = self._selected_index()
        if idx is None or idx == 0:
            return

        units = self._data["units"]
        unit_name = units[idx]["name"]
        units[idx - 1], units[idx] = units[idx], units[idx - 1]
        audit_log("LIST_UNIT_MOVE", f"unidade={unit_name}; direction=up")
        self._refresh()
        self.listbox.selection_set(idx - 1)

    def move_down(self):
        idx = self._selected_index()
        units = self._data["units"]
        if idx is None or idx == len(units) - 1:
            return

        unit_name = units[idx]["name"]
        units[idx + 1], units[idx] = units[idx], units[idx + 1]
        audit_log("LIST_UNIT_MOVE", f"unidade={unit_name}; direction=down")
        self._refresh()
        self.listbox.selection_set(idx + 1)

    def close(self):
        self._on_change()
        self.destroy()


class SectorsWindow(tk.Toplevel):
    def __init__(self, parent, unit, on_change):
        super().__init__(parent)
        self.title("Editar Setores")
        self.resizable(False, False)
        self.transient(parent)

        self._unit = unit
        self._on_change = on_change

        frame = tk.Frame(self, padx=12, pady=12)
        frame.pack()

        tk.Label(frame, text=f'Setores de {unit["name"]}:', font=("Segoe UI", 10)).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 6)
        )

        self.listbox = tk.Listbox(frame, width=36, height=10)
        self.listbox.grid(row=1, column=0, columnspan=3, pady=(0, 10), sticky="nsew")

        side = tk.Frame(frame)
        side.grid(row=1, column=3, padx=(10, 0), pady=(0, 10))
        tk.Frame(side).pack(expand=True, fill="both")
        tk.Button(side, text="↑", width=4, command=self.move_up).pack(pady=(0, 6))
        tk.Button(side, text="↓", width=4, command=self.move_down).pack()
        tk.Frame(side).pack(expand=True, fill="both")

        tk.Button(frame, text="Adicionar", width=12, command=self.add_sector).grid(row=2, column=0, pady=4, sticky="w")
        tk.Button(frame, text="Renomear", width=12, command=self.rename_sector).grid(row=2, column=1, pady=4)
        tk.Button(frame, text="Remover", width=12, command=self.delete_sector).grid(row=2, column=2, pady=4)
        tk.Button(frame, text="Ordenar A-Z", width=12, command=self.sort_sectors_by_name).grid(row=2, column=3, pady=4, sticky="e")

        bottom = tk.Frame(frame)
        bottom.grid(row=3, column=0, columnspan=4, pady=(12, 0))
        tk.Button(bottom, text="Fechar", width=12, command=self.close).pack(side="left", padx=4)

        self._refresh()
        self.grab_set()
        self.listbox.focus_set()
        apply_theme_to_window(self, get_dark_mode(parent))
        center_window(self)

    def _refresh(self):
        self.listbox.delete(0, tk.END)
        for sector in self._unit.get("sectors", []):
            self.listbox.insert(tk.END, sector["name"])

    def _selected_index(self):
        sel = self.listbox.curselection()
        return sel[0] if sel else None

    def _sector_exists(self, name):
        return any(s["name"].lower() == name.lower() for s in self._unit.get("sectors", []))

    def add_sector(self):
        name = ask_text(self, "Adicionar Setor", "Nome do setor:")
        if not name:
            return
        if self._sector_exists(name):
            messagebox.showerror("Erro", "Já existe um setor com esse nome.")
            return

        self._unit.setdefault("sectors", []).append({"name": name, "hosts": []})
        audit_log("LIST_SECTOR_ADD", f"unidade={self._unit.get('name', '')}; setor={name}")
        self._refresh()

    def rename_sector(self):
        idx = self._selected_index()
        if idx is None:
            messagebox.showinfo("Renomear", "Selecione um setor.")
            return

        current = self._unit["sectors"][idx]["name"]
        name = ask_text(self, "Renomear Setor", "Nome do setor:", current)
        if not name:
            return
        if name.lower() != current.lower() and self._sector_exists(name):
            messagebox.showerror("Erro", "Já existe um setor com esse nome.")
            return

        rename_realvnc_profiles_for_sector(current, name, self._unit["sectors"][idx].get("hosts", []), self)

        self._unit["sectors"][idx]["name"] = name
        audit_log("LIST_SECTOR_RENAME", f"unidade={self._unit.get('name', '')}; from={current}; to={name}")
        self._refresh()
        self.listbox.selection_set(idx)

    def delete_sector(self):
        idx = self._selected_index()
        if idx is None:
            messagebox.showinfo("Remover", "Selecione um setor.")
            return
        if len(self._unit.get("sectors", [])) <= 1:
            messagebox.showerror("Erro", "É necessário manter pelo menos um setor.")
            return

        name = self._unit["sectors"][idx]["name"]
        if confirm_action(self, "Confirmar", f"Remover setor?\n\n{name}"):
            self._unit["sectors"].pop(idx)
            audit_log("LIST_SECTOR_DELETE", f"unidade={self._unit.get('name', '')}; setor={name}")
            self._refresh()

    def move_up(self):
        idx = self._selected_index()
        if idx is None or idx == 0:
            return

        sectors = self._unit["sectors"]
        sector_name = sectors[idx]["name"]
        sectors[idx - 1], sectors[idx] = sectors[idx], sectors[idx - 1]
        audit_log("LIST_SECTOR_MOVE", f"unidade={self._unit.get('name', '')}; setor={sector_name}; direction=up")
        self._refresh()
        self.listbox.selection_set(idx - 1)

    def move_down(self):
        idx = self._selected_index()
        sectors = self._unit["sectors"]
        if idx is None or idx == len(sectors) - 1:
            return

        sector_name = sectors[idx]["name"]
        sectors[idx + 1], sectors[idx] = sectors[idx], sectors[idx + 1]
        audit_log("LIST_SECTOR_MOVE", f"unidade={self._unit.get('name', '')}; setor={sector_name}; direction=down")
        self._refresh()
        self.listbox.selection_set(idx + 1)

    def sort_sectors_by_name(self):
        sectors = self._unit.get("sectors", [])
        if not sectors:
            return

        current_name = None
        idx = self._selected_index()
        if idx is not None and idx < len(sectors):
            current_name = sectors[idx].get("name")

        sectors.sort(key=lambda item: str(item.get("name", "")).casefold())
        audit_log("LIST_SECTOR_SORT", f"unidade={self._unit.get('name', '')}; order=A-Z")
        self._refresh()

        if current_name:
            for new_idx, sector in enumerate(sectors):
                if sector.get("name") == current_name:
                    self.listbox.selection_set(new_idx)
                    self.listbox.activate(new_idx)
                    self.listbox.see(new_idx)
                    break

    def close(self):
        self._on_change()
        self.destroy()


# Main host editor: manages Units -> Sectors -> Hosts.
class HostUnitsConfigWindow(tk.Toplevel):
    EDIT_UNITS_OPTION = "Editar Unidades..."
    EDIT_SECTORS_OPTION = "Editar Setores..."

    def __init__(self, parent, hosts_data, on_save, hosts_path=SHARED_HOSTS_JSON):
        super().__init__(parent)
        self.title("Configurar Hosts VNC")
        self.resizable(False, False)
        self.transient(parent)

        self._data = json.loads(json.dumps(hosts_data, ensure_ascii=False))
        self._on_save = on_save
        self._hosts_path = Path(hosts_path)

        unit_names = get_unit_names(self._data)
        first_unit = unit_names[0] if unit_names else "Geral"
        sector_names = get_sector_names(self._data, first_unit)
        first_sector = sector_names[0] if sector_names else "Geral"

        self.selected_unit = tk.StringVar(value=first_unit)
        self.selected_sector = tk.StringVar(value=first_sector)

        frame = tk.Frame(self, padx=12, pady=12)
        frame.pack()

        main_area = tk.Frame(frame)
        main_area.grid(row=0, column=0, columnspan=4, pady=(0, 10))

        # Left panel: Unidade dropdown + Setor list
        left_panel = tk.Frame(main_area)
        left_panel.grid(row=0, column=0, sticky="ns", padx=(0, 14))

        tk.Label(left_panel, text="Unidade", font=UI_FONT).pack(anchor="center", pady=(0, 4))
        self.unit_menu = tk.OptionMenu(
            left_panel,
            self.selected_unit,
            *(unit_names + [self.EDIT_UNITS_OPTION]),
            command=self.on_unit_selected,
        )
        self.unit_menu.config(width=20)
        self.unit_menu.pack(fill="x", pady=(0, 10))

        tk.Label(left_panel, text="Setores", font=UI_FONT).pack(anchor="center", pady=(0, 4))

        self.sector_listbox = tk.Listbox(
            left_panel,
            width=24,
            height=13,
            exportselection=False,
            activestyle="none",
        )
        self.sector_listbox.pack(fill="both", expand=True, pady=(0, 8))
        self.sector_listbox.bind("<<ListboxSelect>>", self.on_sector_list_selected)
        self._refreshing_sector_list = False

        tk.Button(
            left_panel,
            text="Editar Setores",
            width=16,
            command=self.open_sectors_editor,
        ).pack(fill="x")

        # Right panel: host table + host action buttons
        right_panel = tk.Frame(main_area)
        right_panel.grid(row=0, column=1, sticky="n", pady=(66, 0))

        table_box = tk.Frame(right_panel)
        table_box.grid(row=0, column=0, pady=(0, 10), sticky="nsew")

        self.host_table = ttk.Treeview(
            table_box,
            columns=("name", "host", "viewer"),
            show="headings",
            height=12,
            selectmode="browse",
        )

        self.host_scrollbar = ttk.Scrollbar(
            table_box,
            orient="vertical",
            command=self.host_table.yview,
        )
        self.host_table.configure(yscrollcommand=self.host_scrollbar.set)

        self.host_table.heading("name", text="Nome")
        self.host_table.heading("host", text="Host/IP")
        self.host_table.heading("viewer", text="Viewer")
        self.host_table.column("name", width=220, anchor="center", stretch=True)
        self.host_table.column("host", width=250, anchor="center", stretch=True)
        self.host_table.column("viewer", width=120, anchor="center", stretch=False)
        self.host_table.grid(row=0, column=0, sticky="nsew")
        self.host_scrollbar.grid(row=0, column=1, sticky="ns", padx=(4, 0))
        self.host_table.bind("<Double-Button-1>", lambda _event: self.edit_item())

        side = tk.Frame(main_area, padx=8, pady=8)
        side.grid(row=0, column=2, padx=(12, 0), pady=(66, 10), sticky="ns")

        tk.Button(side, text="↑", width=12, command=self.move_up).pack(fill="x", pady=(0, 8))
        tk.Button(side, text="↓", width=12, command=self.move_down).pack(fill="x", pady=(0, 16))

        tk.Button(side, text="+ Adicionar", width=14, command=self.add_item).pack(fill="x", pady=(0, 8))
        tk.Button(side, text="Editar", width=14, command=self.edit_item).pack(fill="x", pady=(0, 8))
        tk.Button(side, text="Remover", width=14, command=self.delete_item).pack(fill="x", pady=(0, 8))
        tk.Button(side, text="Ordenar A-Z", width=14, command=self.sort_hosts_by_name).pack(fill="x")

        tk.Frame(frame, height=1).grid(row=1, column=0, columnspan=4, pady=8)

        bottom = tk.Frame(frame)
        bottom.grid(row=2, column=0, columnspan=4, pady=(4, 0))
        tk.Button(bottom, text="Salvar", width=14, command=self.save).pack(side="left", padx=6)
        tk.Button(bottom, text="Fechar", width=14, command=self.destroy).pack(side="left", padx=6)

        self._refresh_sector_menu()
        self._refresh_list()
        self.grab_set()
        self.host_table.focus_set()
        apply_theme_to_window(self, get_dark_mode(parent))
        self._apply_host_table_theme()
        center_window(self)

    def _current_hosts(self):
        return get_sector_hosts(self._data, self.selected_unit.get(), self.selected_sector.get())

    def _current_unit(self):
        return get_unit_by_name(self._data, self.selected_unit.get())

    def _audit(self, action: str, details: str = "") -> None:
        audit_log(
            action,
            f"file={self._hosts_path}; unidade={self.selected_unit.get()}; setor={self.selected_sector.get()}; {details}",
        )

    def _refresh_unit_menu(self):
        unit_names = get_unit_names(self._data)
        if not unit_names:
            self._data = json.loads(json.dumps(DEFAULT_HOSTS, ensure_ascii=False))
            unit_names = get_unit_names(self._data)

        if self.selected_unit.get() not in unit_names:
            self.selected_unit.set(unit_names[0])

        menu = self.unit_menu["menu"]
        menu.delete(0, "end")
        for name in unit_names + [self.EDIT_UNITS_OPTION]:
            menu.add_command(label=name, command=lambda value=name: self.on_unit_selected(value))

    def _refresh_sector_menu(self):
        sector_names = get_sector_names(self._data, self.selected_unit.get())
        if not sector_names:
            unit = self._current_unit()
            if unit is not None:
                unit["sectors"] = [{"name": "Geral", "hosts": []}]
            sector_names = get_sector_names(self._data, self.selected_unit.get())

        if self.selected_sector.get() not in sector_names:
            self.selected_sector.set(sector_names[0])

        self._refreshing_sector_list = True
        try:
            self.sector_listbox.delete(0, tk.END)
            for name in sector_names:
                self.sector_listbox.insert(tk.END, name)

            self._select_current_sector_in_list()
        finally:
            self._refreshing_sector_list = False

    def _select_current_sector_in_list(self):
        sector_name = self.selected_sector.get()
        for idx in range(self.sector_listbox.size()):
            if self.sector_listbox.get(idx) == sector_name:
                self.sector_listbox.selection_clear(0, tk.END)
                self.sector_listbox.selection_set(idx)
                self.sector_listbox.activate(idx)
                self.sector_listbox.see(idx)
                return

    def on_sector_list_selected(self, _event=None):
        if getattr(self, "_refreshing_sector_list", False):
            return

        sel = self.sector_listbox.curselection()
        if not sel:
            return

        sector_name = self.sector_listbox.get(sel[0])
        if sector_name == self.selected_sector.get():
            return

        self.selected_sector.set(sector_name)
        self._refresh_list()

    def open_sectors_editor(self):
        previous = self.selected_sector.get()
        unit = self._current_unit()
        if unit is None:
            return

        audit_log("LIST_SECTORS_EDITOR_OPEN", f"unidade={unit.get('name', '')}; file={self._hosts_path}")
        SectorsWindow(self, unit, self.on_sectors_changed)
        sector_names = get_sector_names(self._data, self.selected_unit.get())
        if sector_names:
            self.selected_sector.set(previous if previous in sector_names else sector_names[0])

        self._refresh_menus()
        self._refresh_list()

    def _refresh_menus(self):
        self._refresh_unit_menu()
        self._refresh_sector_menu()
        apply_theme_to_window(self, get_dark_mode(self))
        self._apply_host_table_theme()

    def _apply_host_table_theme(self):
        apply_treeview_theme(self.host_table, get_dark_mode(self))

    def _refresh_list(self):
        for item in self.host_table.get_children():
            self.host_table.delete(item)

        for idx, h in enumerate(self._current_hosts()):
            self.host_table.insert(
                "",
                "end",
                iid=str(idx),
                values=(h["name"], h["host"], viewer_display_name(h.get("viewer", DEFAULT_VIEWER))),
            )

    def _selected_index(self):
        sel = self.host_table.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except ValueError:
            return None

    def _select_index(self, idx):
        iid = str(idx)
        if iid in self.host_table.get_children():
            self.host_table.selection_set(iid)
            self.host_table.focus(iid)

    def on_unit_selected(self, value):
        if value == self.EDIT_UNITS_OPTION:
            previous = self.selected_unit.get()
            UnitsWindow(self, self._data, self.on_units_changed)
            unit_names = get_unit_names(self._data)
            self.selected_unit.set(previous if previous in unit_names else unit_names[0])
            self._refresh_menus()
            self._refresh_list()
            return

        self.selected_unit.set(value)
        sector_names = get_sector_names(self._data, value)
        self.selected_sector.set(sector_names[0] if sector_names else "Geral")
        self._refresh_sector_menu()
        self._refresh_list()


    def on_units_changed(self):
        self._refresh_menus()
        self._refresh_list()

    def on_sectors_changed(self):
        self._refresh_menus()
        self._refresh_list()

    def add_item(self):
        host_data = ask_host_details(self, "Adicionar Host")
        if not host_data:
            return

        self._current_hosts().append(host_data)
        self._audit(
            "LIST_HOST_ADD",
            f"name={host_data.get('name', '')}; host={host_data.get('host', '')}; viewer={viewer_display_name(host_data.get('viewer', DEFAULT_VIEWER))}",
        )
        self._refresh_list()

    def edit_item(self):
        idx = self._selected_index()
        if idx is None:
            messagebox.showinfo("Editar", "Selecione um item.")
            return

        hosts = self._current_hosts()
        current = hosts[idx]

        host_data = ask_host_details(self, "Editar Host", current)
        if not host_data:
            return

        if (
            sanitize_viewer(current.get("viewer", DEFAULT_VIEWER)) == VIEWER_REALVNC
            or sanitize_viewer(host_data.get("viewer", DEFAULT_VIEWER)) == VIEWER_REALVNC
        ):
            rename_realvnc_profile(
                self.selected_sector.get(),
                current["name"],
                self.selected_sector.get(),
                host_data["name"],
                self,
            )

        hosts[idx] = host_data
        self._audit(
            "LIST_HOST_EDIT",
            f"from={current.get('name', '')} ({current.get('host', '')}, {viewer_display_name(current.get('viewer', DEFAULT_VIEWER))}); "
            f"to={host_data.get('name', '')} ({host_data.get('host', '')}, {viewer_display_name(host_data.get('viewer', DEFAULT_VIEWER))})",
        )
        self._refresh_list()
        self._select_index(idx)

    def delete_item(self):
        idx = self._selected_index()
        if idx is None:
            messagebox.showinfo("Remover", "Selecione um item.")
            return

        if confirm_action(self, "Confirmar", "Remover este host?"):
            removed = self._current_hosts().pop(idx)
            self._audit(
                "LIST_HOST_DELETE",
                f"name={removed.get('name', '')}; host={removed.get('host', '')}; viewer={viewer_display_name(removed.get('viewer', DEFAULT_VIEWER))}",
            )
            self._refresh_list()

    def sort_hosts_by_name(self):
        hosts = self._current_hosts()
        hosts.sort(key=lambda item: str(item.get("name", "")).casefold())
        self._audit("LIST_HOST_SORT", "order=A-Z")
        self._refresh_list()
        if hosts:
            self._select_index(0)

    def move_up(self):
        idx = self._selected_index()
        hosts = self._current_hosts()
        if idx is None or idx == 0:
            return

        host_name = hosts[idx].get("name", "")
        hosts[idx - 1], hosts[idx] = hosts[idx], hosts[idx - 1]
        self._audit("LIST_HOST_MOVE", f"name={host_name}; direction=up")
        self._refresh_list()
        self._select_index(idx - 1)

    def move_down(self):
        idx = self._selected_index()
        hosts = self._current_hosts()
        if idx is None or idx == len(hosts) - 1:
            return

        host_name = hosts[idx].get("name", "")
        hosts[idx + 1], hosts[idx] = hosts[idx], hosts[idx + 1]
        self._audit("LIST_HOST_MOVE", f"name={host_name}; direction=down")
        self._refresh_list()
        self._select_index(idx + 1)

    def save(self):
        normalized = normalize_hosts_data(self._data)
        if not normalized.get("units"):
            messagebox.showerror("Erro", "É necessário manter pelo menos uma unidade.")
            return

        save_json(normalized, self._hosts_path)
        self._audit("LIST_SAVE", f"units={len(normalized.get('units', []))}")
        self._on_save(normalized)
        self.destroy()


# Main application window.
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("UltraVNC - Menu de Hosts")
        self.resizable(False, False)

        self.settings = load_settings()
        self.dark_mode = bool(self.settings.get("dark_mode", False))

        self.hosts_source = ensure_hosts_source_selected(self, self.settings)
        self.hosts_path = get_hosts_path_for_source(self.hosts_source)
        audit_log("APP_START", f"hosts_source={hosts_source_display_name(self.hosts_source)}; hosts_file={self.hosts_path}")
        self.hosts_data = load_hosts_data(self.hosts_path)
        self.unit_names = get_unit_names(self.hosts_data) or ["Geral"]

        saved_unit = self.settings.get("selected_unit", self.unit_names[0])
        if saved_unit not in self.unit_names:
            saved_unit = self.unit_names[0]
        self.selected_unit = tk.StringVar(value=saved_unit)

        sector_names = get_sector_names(self.hosts_data, saved_unit) or ["Geral"]
        saved_sector = self.settings.get("selected_sector", sector_names[0])
        if saved_sector not in sector_names:
            saved_sector = sector_names[0]
        self.selected_sector = tk.StringVar(value=saved_sector)

        self.mode = tk.StringVar(value="connect")

        self.frame = tk.Frame(self, padx=12, pady=12)
        self.frame.pack()

        main_area = tk.Frame(self.frame)
        main_area.grid(row=0, column=0, pady=(0, 10))

        # Left panel: Unidade dropdown + Setor list
        left_panel = tk.Frame(main_area)
        left_panel.grid(row=0, column=0, sticky="ns", padx=(0, 14))

        tk.Label(left_panel, text="Unidade", font=UI_FONT).pack(anchor="center", pady=(0, 4))
        self.unit_menu = tk.OptionMenu(
            left_panel,
            self.selected_unit,
            *self.unit_names,
            command=lambda _value: self.on_main_unit_changed(),
        )
        self.unit_menu.config(width=20)
        self.unit_menu.pack(fill="x", pady=(0, 10))

        tk.Label(left_panel, text="Setores", font=UI_FONT).pack(anchor="center", pady=(0, 4))

        self.sector_listbox = tk.Listbox(
            left_panel,
            width=24,
            height=13,
            exportselection=False,
            activestyle="none",
        )
        self.sector_listbox.pack(fill="both", expand=True, pady=(0, 10))
        self.sector_listbox.bind("<<ListboxSelect>>", self.on_sector_list_selected)
        self._refreshing_sector_list = False

        menu_btn = tk.Menubutton(left_panel, text="Configurações", width=12, relief="raised")
        menu = tk.Menu(menu_btn, tearoff=0)
        menu.add_command(label="Credenciais", command=self.open_creds)
        menu.add_command(label="Hosts VNC", command=self.open_config)
        menu.add_command(label="Lista de Hosts", command=self.open_hosts_source_config)
        menu.add_separator()
        menu.add_command(label="Modo Escuro", command=self.toggle_dark_mode)
        menu_btn.configure(menu=menu)
        menu_btn.pack(fill="x")

        # Right panel: actions + host buttons
        right_panel = tk.Frame(main_area)
        right_panel.grid(row=0, column=1, sticky="n")

        modes = tk.Frame(right_panel)
        # Align action buttons with the Unidade dropdown and align host buttons with the Setores list.
        modes.grid(row=0, column=0, pady=(27, 28))

        self.btn_connect = tk.Button(modes, text="Conectar", width=10, command=lambda: self.set_mode("connect"))
        self.btn_connect.pack(side="left", padx=4)
        self.btn_connect.bind("<Double-Button-1>", lambda _event: self.connect_custom_host())

        self.btn_restart = tk.Button(modes, text="Reiniciar", width=10, command=lambda: self.set_mode("restart"))
        self.btn_restart.pack(side="left", padx=4)
        self.btn_restart.bind("<Double-Button-1>", lambda _event: self.restart_custom_host())

        self.btn_users = tk.Button(modes, text="Usuários", width=10, command=self.show_qwinsta_users)
        self.btn_users.pack(side="left", padx=4)

        self.buttons_frame = tk.Frame(right_panel)
        self.buttons_frame.grid(row=1, column=0, pady=(0, 10))

        self.update_window_title()
        self.refresh_sector_menu()
        self.set_mode("connect")
        self.render_buttons()
        self.apply_theme()
        self.after(0, lambda: center_window(self))

    def set_mode(self, mode):
        self.mode.set(mode)

        p = get_ui_palette(self.dark_mode)
        normal_bg = p["button_bg"]
        selected_bg = p["selected_bg"]
        fg = p["fg"]
        active_bg = p["button_active"]

        if mode == "connect":
            self.btn_connect.config(relief="sunken", bg=selected_bg, fg=fg, activebackground=active_bg, activeforeground=fg)
            self.btn_restart.config(relief="raised", bg=normal_bg, fg=fg, activebackground=active_bg, activeforeground=fg)
            set_button_normal_bg(self.btn_connect, selected_bg)
            set_button_normal_bg(self.btn_restart, normal_bg)
        else:
            self.btn_connect.config(relief="raised", bg=normal_bg, fg=fg, activebackground=active_bg, activeforeground=fg)
            self.btn_restart.config(relief="sunken", bg=selected_bg, fg=fg, activebackground=active_bg, activeforeground=fg)
            set_button_normal_bg(self.btn_connect, normal_bg)
            set_button_normal_bg(self.btn_restart, selected_bg)

        try:
            self.btn_users.config(bg=normal_bg, fg=fg, activebackground=active_bg, activeforeground=fg)
            set_button_normal_bg(self.btn_users, normal_bg)
        except Exception:
            pass

    def toggle_dark_mode(self):
        self.dark_mode = not self.dark_mode
        self.settings["dark_mode"] = self.dark_mode
        save_settings(self.settings)
        self.apply_theme()

    def apply_theme(self):
        apply_theme_to_window(self, self.dark_mode)
        self.set_mode(self.mode.get())

    def on_main_unit_changed(self):
        unit = self.selected_unit.get()
        sector_names = get_sector_names(self.hosts_data, unit) or ["Geral"]
        self.selected_sector.set(sector_names[0])
        self.refresh_sector_menu()
        self.save_main_selection()
        self.render_buttons()

    def on_main_sector_changed(self):
        self.save_main_selection()
        self.render_buttons()

    def save_main_selection(self):
        self.settings["selected_unit"] = self.selected_unit.get()
        self.settings["selected_sector"] = self.selected_sector.get()
        save_settings(self.settings)

    def run_host_action(self, name, host, viewer=DEFAULT_VIEWER):
        if self.mode.get() == "connect":
            launch_vnc(host, viewer, name, self.selected_sector.get(), self)
        elif self.mode.get() == "restart":
            if confirm_action(self, "Confirmar", f"Reiniciar:\n{name} ?"):
                restart_host(host)

    def connect_custom_host(self):
        result = ask_custom_connection(self)
        if not result:
            return

        host, viewer = result
        launch_vnc(host, viewer, parent=self)

    def restart_custom_host(self):
        target = ask_text(self, "Reiniciar host", "Digite o hostname ou IP:")
        if not target:
            return
        if confirm_action(self, "Confirmar", f"Reiniciar:\n{target} ?"):
            restart_host(target)

    def refresh_unit_menu(self):
        self.unit_names = get_unit_names(self.hosts_data) or ["Geral"]

        if self.selected_unit.get() not in self.unit_names:
            self.selected_unit.set(self.unit_names[0])

        menu = self.unit_menu["menu"]
        menu.delete(0, "end")
        for unit_name in self.unit_names:
            menu.add_command(label=unit_name, command=lambda value=unit_name: self.set_main_unit(value))

        apply_theme_to_window(self, self.dark_mode)

    def refresh_sector_menu(self):
        sector_names = get_sector_names(self.hosts_data, self.selected_unit.get()) or ["Geral"]

        if self.selected_sector.get() not in sector_names:
            self.selected_sector.set(sector_names[0])

        self._refreshing_sector_list = True
        try:
            self.sector_listbox.delete(0, tk.END)
            for sector_name in sector_names:
                self.sector_listbox.insert(tk.END, sector_name)

            self.select_current_sector_in_list()
        finally:
            self._refreshing_sector_list = False

        apply_theme_to_window(self, self.dark_mode)

    def select_current_sector_in_list(self):
        sector_name = self.selected_sector.get()
        for idx in range(self.sector_listbox.size()):
            if self.sector_listbox.get(idx) == sector_name:
                self.sector_listbox.selection_clear(0, tk.END)
                self.sector_listbox.selection_set(idx)
                self.sector_listbox.activate(idx)
                self.sector_listbox.see(idx)
                return

    def on_sector_list_selected(self, _event=None):
        if getattr(self, "_refreshing_sector_list", False):
            return

        sel = self.sector_listbox.curselection()
        if not sel:
            return

        sector_name = self.sector_listbox.get(sel[0])
        if sector_name == self.selected_sector.get():
            return

        self.selected_sector.set(sector_name)
        self.on_main_sector_changed()

    def set_main_unit(self, unit_name):
        self.selected_unit.set(unit_name)
        self.on_main_unit_changed()


    def refresh_main_selectors(self):
        self.refresh_unit_menu()
        self.refresh_sector_menu()

    def render_buttons(self):
        for widget in self.buttons_frame.winfo_children():
            widget.destroy()

        hosts = get_sector_hosts(
            self.hosts_data,
            self.selected_unit.get(),
            self.selected_sector.get(),
        )

        cols = 2

        for i, item in enumerate(hosts):
            r = i // cols
            c = i % cols
            btn = tk.Button(
                self.buttons_frame,
                text=item["name"],
                width=18,
                command=lambda n=item["name"], h=item["host"], v=item.get("viewer", DEFAULT_VIEWER): self.run_host_action(n, h, v),
            )
            btn.grid(row=r, column=c, padx=6, pady=6, sticky="we")

        self.apply_theme()
        self.after(0, lambda: center_window(self))

    def reload_hosts_from_current_source(self):
        self.hosts_source = normalize_hosts_source(self.settings.get("hosts_source")) or HOSTS_SOURCE_SHARED
        self.hosts_path = get_hosts_path_for_source(self.hosts_source)
        self.hosts_data = load_hosts_data(self.hosts_path)
        self.unit_names = get_unit_names(self.hosts_data) or ["Geral"]
        self.refresh_main_selectors()
        self.render_buttons()
        self.update_window_title()

    def update_window_title(self):
        self.title(f"UltraVNC - Menu de Hosts [{hosts_source_display_name(self.hosts_source)}]")

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

    def on_hosts_saved(self, hosts_data):
        self.hosts_data = hosts_data
        self.refresh_main_selectors()
        self.render_buttons()
        self.update_window_title()


    def show_qwinsta_users(self):
        unit_name = self.selected_unit.get()
        sector_name = self.selected_sector.get()

        hosts = get_sector_hosts(self.hosts_data, unit_name, sector_name)
        label = f"{unit_name} > {sector_name}"

        if not hosts:
            show_text_window(self, "Usuários logados", f"Setor sem hosts ou inexistente: {label}")
            return

        audit_log("USERS_QUERY", f"unidade={unit_name}; setor={sector_name}; hosts={len(hosts)}")
        output = query_all_logged_users(hosts)
        show_text_window(self, f"Usuários logados - {label}", output)


if __name__ == "__main__":
    try:
        App().mainloop()
    except Exception as e:
        log_exception(e)
        messagebox.showerror("Erro", f"O app falhou ao iniciar:\n{e}\n\nLog: {ERROR_LOG}")
