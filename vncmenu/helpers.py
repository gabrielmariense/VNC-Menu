"""Utilidades de janela, geometria e arquivos usadas pela interface.

Centralizacao de janelas, persistencia de geometria (so para janelas
redimensionaveis), perfis RealVNC e atalhos de messagebox.

Depende de config, applog e storage.
"""

from pathlib import Path
from tkinter import messagebox
import re

from .config import REALVNC_DIR, VIEWER_REALVNC
from .applog import audit_log, log_exception
from .storage import load_settings, sanitize_viewer, save_settings

def center_window(win, width: int | None = None, height: int | None = None):
    """Centraliza a janela na tela."""
    win.update_idletasks()
    w = width or max(win.winfo_width(), win.winfo_reqwidth(), 1)
    h = height or max(win.winfo_height(), win.winfo_reqheight(), 1)
    x = max((win.winfo_screenwidth() - w) // 2, 0)
    y = max((win.winfo_screenheight() - h) // 2, 0)
    win.geometry(f"{w}x{h}+{x}+{y}")


def fit_dialog_to_content(
    win,
    parent=None,
    width: int = 560,
    min_height: int = 170,
):
    """Size compact dialogs to their actual content and center them near the parent."""
    win.update_idletasks()
    req_height = max(win.winfo_reqheight(), min_height)
    max_height = max(win.winfo_screenheight() - 120, min_height)
    height = min(req_height, max_height)

    if parent is not None:
        try:
            parent.update_idletasks()
            if parent.winfo_exists() and parent.winfo_ismapped():
                x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
                y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 2, 0)
                x = max(0, min(x, win.winfo_screenwidth() - width))
                y = max(0, min(y, win.winfo_screenheight() - height))
                win.geometry(f"{width}x{height}+{x}+{y}")
                return
        except Exception:
            pass

    center_window(win, width, height)


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


# Only windows the user can actually resize persist their geometry. Fixed-size
# dialogs used to save it too, and whenever their layout changed the stale saved
# size clipped the content. The workaround was to bump the key (_v2, _v3, _v4),
# which left the previous key in settings.json forever.
PERSISTED_GEOMETRY_KEYS = {"main", "window_hosts_config", "window_text_output"}


PERSISTED_GEOMETRY_PREFIXES = ("window_list_editor_",)


def is_persisted_geometry_key(key: str) -> bool:
    key = str(key or "")
    return key in PERSISTED_GEOMETRY_KEYS or key.startswith(PERSISTED_GEOMETRY_PREFIXES)


def prune_window_geometries(settings: dict) -> int:
    """Drop geometry entries for windows that no longer persist their size.

    Removes the orphaned keys left behind by the old _v2/_v3/_v4 workaround.
    Returns how many entries were removed.
    """
    geometries = get_window_geometries(settings)
    kept = {key: value for key, value in geometries.items() if is_persisted_geometry_key(key)}
    removed = len(geometries) - len(kept)
    if removed:
        settings["window_geometries"] = kept
        save_settings(settings)
    return removed


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
        if not is_persisted_geometry_key(key):
            # Guard, so a future window cannot start accumulating keys again.
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


def reset_scrollable_frame_position(frame) -> None:
    """Reset a CTkScrollableFrame after its contents have been rebuilt."""

    def reset_after_layout():
        try:
            frame.update_idletasks()
            canvas = getattr(frame, "_parent_canvas", None)
            if canvas is None or not canvas.winfo_exists():
                return

            scroll_region = canvas.bbox("all")
            if scroll_region:
                canvas.configure(scrollregion=scroll_region)
            canvas.yview_moveto(0.0)
        except Exception:
            pass

    try:
        frame.after_idle(reset_after_layout)
    except Exception:
        pass


def modal_window(win, parent=None):
    previous_grab = None
    try:
        previous_grab = win.grab_current()
    except Exception:
        pass

    if parent:
        win.transient(parent)
    win.grab_set()
    win.focus_force()
    win.wait_window()

    # Restore a parent modal grab after closing a nested dialog.
    if previous_grab is not None:
        try:
            if previous_grab.winfo_exists():
                previous_grab.grab_set()
                previous_grab.focus_force()
        except Exception:
            pass


def bind_clickable_row(row, labels, on_click, on_context, normal_color, hover_color):
    """Faz um frame cheio de labels se comportar como uma linha clicavel.

    Usado pela lista da busca de hosts e pela do inventario OCS. Fica aqui
    porque a parte chata nao e o clique, e o hover: entrar num label filho
    dispara <Leave> no proprio frame, entao a cor so pode voltar quando o
    ponteiro tiver saido da linha INTEIRA, nao de um pedaco dela.
    """

    def enter(_event=None):
        try:
            row.configure(fg_color=hover_color)
        except Exception:
            pass

    def leave(event=None):
        try:
            under = row.winfo_containing(event.x_root, event.y_root) if event else None
            widget = under
            while widget is not None:
                if widget is row:
                    return
                widget = getattr(widget, "master", None)
        except Exception:
            pass
        try:
            row.configure(fg_color=normal_color)
        except Exception:
            pass

    for widget in (row, *labels):
        widget.bind("<Enter>", enter, add="+")
        widget.bind("<Leave>", leave, add="+")
        if on_click is not None:
            widget.bind("<Button-1>", on_click, add="+")
        if on_context is not None:
            widget.bind("<Button-3>", on_context, add="+")
