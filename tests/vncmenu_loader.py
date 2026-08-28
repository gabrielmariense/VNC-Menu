"""Load the VNC-Menu package for testing, without a GUI.

The application imports customtkinter, pywinauto and tkinter at module level.
None of that is needed to exercise its logic, so those are replaced by inert
stubs before the package is imported.

Each load gets its own temporary sandbox: HOME/USERPROFILE and APPDATA are
redirected and the whole project is copied in, so SCRIPT_DIR (and with it
data/ and logs/) resolves inside the sandbox. Tests never touch real user data.

`load_app()` returns a facade module carrying every public name from every
module in the package, so tests can reach `app.save_json` without caring which
file it ended up in. That is deliberate: the tests describe behaviour, not
layout, and stayed unchanged when the monolith was split.
"""

import importlib
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MAIN_SCRIPT = REPO_ROOT / "VNC-Menu.pyw"
UPDATER_SCRIPT = REPO_ROOT / "VNC-Menu-Updater.pyw"
PACKAGE_DIR = REPO_ROOT / "vncmenu"
DIALOGS_MODULE = PACKAGE_DIR / "ui" / "dialogs.py"
WINDOWS_MODULE = PACKAGE_DIR / "ui" / "windows.py"
# The dialog functions are split across these two modules.
UI_MODULES = (DIALOGS_MODULE, WINDOWS_MODULE)

# Import order matters: it is the package's own dependency order.
PACKAGE_MODULES = [
    "vncmenu.config",
    "vncmenu.applog",
    "vncmenu.dpapi",
    "vncmenu.storage",
    "vncmenu.theme",
    "vncmenu.helpers",
    "vncmenu.updates",
    "vncmenu.ocs",
    "vncmenu.ui.dialogs",
    "vncmenu.remote",
    "vncmenu.ui.windows",
    "vncmenu.ui.app",
]


class _Inert:
    """Accepts any construction, call or attribute access and does nothing."""

    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return _Inert()

    def __getattr__(self, name):
        return _Inert()


def _register(name, attributes=None):
    module = types.ModuleType(name)
    for key, value in (attributes or {}).items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def install_gui_stubs():
    """Replace the GUI dependencies with stubs. Safe to call more than once."""
    tkinter = _register(
        "tkinter",
        {
            "StringVar": _Inert,
            "BooleanVar": _Inert,
            "Menu": _Inert,
            "END": "end",
            "TclError": type("TclError", (Exception,), {}),
        },
    )
    _register(
        "tkinter.messagebox",
        {
            "showerror": lambda *a, **k: None,
            "showinfo": lambda *a, **k: None,
            "showwarning": lambda *a, **k: None,
        },
    )
    _register("tkinter.filedialog", {"askopenfilename": lambda *a, **k: ""})
    tkinter.messagebox = sys.modules["tkinter.messagebox"]
    tkinter.filedialog = sys.modules["tkinter.filedialog"]

    _register(
        "customtkinter",
        {
            "set_appearance_mode": lambda *a, **k: None,
            "set_default_color_theme": lambda *a, **k: None,
            "set_widget_scaling": lambda *a, **k: None,
            "CTk": _Inert,
            "CTkToplevel": _Inert,
            "CTkFrame": _Inert,
            "CTkLabel": _Inert,
            "CTkButton": _Inert,
            "CTkEntry": _Inert,
            "CTkOptionMenu": _Inert,
            "CTkScrollableFrame": _Inert,
            "CTkTextbox": _Inert,
            "CTkProgressBar": _Inert,
            "CTkSwitch": _Inert,
        },
    )
    _register("pywinauto", {"Desktop": _Inert})
    _register("pywinauto.keyboard", {"send_keys": lambda *a, **k: None})


def _purge_package():
    for name in [n for n in sys.modules if n == "vncmenu" or n.startswith("vncmenu.")]:
        del sys.modules[name]


def _make_sandbox():
    # .resolve() matters on Windows: TEMP is often the 8.3 short form
    # (C:\Users\GABRIE~1.MAR\...), while the application resolves its own
    # paths to the long form. Comparing the two spellings fails even though
    # they are the same directory, so canonicalise here, once.
    sandbox = Path(tempfile.mkdtemp(prefix="vncmenu-test-")).resolve()
    home = sandbox / "home"
    home.mkdir(parents=True, exist_ok=True)

    # Path.home() reads USERPROFILE on Windows and HOME elsewhere.
    os.environ["HOME"] = str(home)
    os.environ["USERPROFILE"] = str(home)
    os.environ["APPDATA"] = str(sandbox / "appdata")
    os.environ["LOCALAPPDATA"] = str(sandbox / "localappdata")

    app_dir = sandbox / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(MAIN_SCRIPT, app_dir / MAIN_SCRIPT.name)
    if UPDATER_SCRIPT.is_file():
        shutil.copy(UPDATER_SCRIPT, app_dir / UPDATER_SCRIPT.name)
    shutil.copytree(PACKAGE_DIR, app_dir / "vncmenu")
    return sandbox, app_dir


def load_app():
    """Return (facade_module, sandbox_path). Call release_sandbox() when done."""
    install_gui_stubs()
    sandbox, app_dir = _make_sandbox()
    entry = app_dir / MAIN_SCRIPT.name

    # The package anchors data/ and logs/ on sys.modules["__main__"].__file__.
    # Under a test runner that is unittest's own __main__, which would point
    # SCRIPT_DIR at the stdlib, so stand in a fake __main__ during the import.
    real_main = sys.modules.get("__main__")
    fake_main = types.ModuleType("__main__")
    fake_main.__file__ = str(entry)
    sys.modules["__main__"] = fake_main

    _purge_package()
    sys.path.insert(0, str(app_dir))
    try:
        loaded = [importlib.import_module(name) for name in PACKAGE_MODULES]
    finally:
        sys.path.remove(str(app_dir))
        if real_main is not None:
            sys.modules["__main__"] = real_main
        else:
            sys.modules.pop("__main__", None)

    facade = types.ModuleType("vncmenu_facade")
    facade.__modules__ = {m.__name__: m for m in loaded}
    for module in loaded:
        for key, value in vars(module).items():
            if not key.startswith("__"):
                setattr(facade, key, value)
    return facade, sandbox


def load_updater():
    """Load VNC-Menu-Updater.pyw, which is still a standalone script."""
    import importlib.machinery
    import importlib.util

    install_gui_stubs()
    sandbox = Path(tempfile.mkdtemp(prefix="vncmenu-updater-test-")).resolve()
    target = sandbox / UPDATER_SCRIPT.name
    shutil.copy(UPDATER_SCRIPT, target)

    loader = importlib.machinery.SourceFileLoader("vncmenu_updater_under_test", str(target))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module, sandbox


class patched_global:
    """Temporarily rebind a module-level name across the whole package.

    `from .config import LOGS_DIR` copies the value into each importing module,
    so setting it on one module (or on the facade) leaves every other binding
    pointing at the old value. This rebinds all of them and restores them.
    """

    def __init__(self, facade, name, value):
        self.facade = facade
        self.name = name
        self.value = value
        self.previous = {}

    def __enter__(self):
        for mod_name, module in self.facade.__modules__.items():
            if hasattr(module, self.name):
                self.previous[mod_name] = getattr(module, self.name)
                setattr(module, self.name, self.value)
        self.previous["__facade__"] = getattr(self.facade, self.name, None)
        setattr(self.facade, self.name, self.value)
        return self.value

    def __exit__(self, *exc):
        for mod_name, old in self.previous.items():
            target = self.facade if mod_name == "__facade__" else self.facade.__modules__[mod_name]
            setattr(target, self.name, old)
        return False


def release_sandbox(sandbox):
    if sandbox is None:
        return
    shutil.rmtree(sandbox, ignore_errors=True)
