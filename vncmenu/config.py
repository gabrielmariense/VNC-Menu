"""Constantes, caminhos e ancoragem da instalacao.

Base do pacote: nao importa nenhum outro modulo daqui. SCRIPT_DIR e
calculado a partir do script de entrada, nunca deste arquivo.
"""

from pathlib import Path
import getpass
import os
import sys
import tempfile


ULTRAVNC_EXE = r"C:\Program Files\uvnc bvba\UltraVNC\vncviewer.exe"


REALVNC_EXE = r"C:\Program Files\RealVNC\VNC Viewer\vncviewer.exe"


PORT = 5900


APP_NAME = "VNC-Menu"


APP_VERSION = "2.1.0"


APP_AUTHOR = 'Gabriel "GMErebos" Mariense'


GITHUB_PROFILE_URL = "https://github.com/gabrielmariense"


GITHUB_URL = "https://github.com/gabrielmariense/VNC-Menu"


LICENSE_URL = "https://github.com/gabrielmariense/VNC-Menu/blob/main/LICENSE"


GITHUB_RELEASES_URL = f"{GITHUB_URL}/releases"


GITHUB_LATEST_RELEASE_API = "https://api.github.com/repos/gabrielmariense/VNC-Menu/releases/latest"


UPDATER_SCRIPT_NAME = "VNC-Menu-Updater.pyw"


UPDATER_EXE_NAME = "VNC-Menu-Updater.exe"


UPDATE_DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "VNC-Menu-Update"


PSEXEC_DOWNLOAD_URL = "https://learn.microsoft.com/sysinternals/downloads/psexec"


PSEXEC_TIMEOUT_SECONDS = 35


HOST_PING_TIMEOUT_MS = 1000


HOST_PING_PROCESS_TIMEOUT_SECONDS = 4


RESTART_TIMEOUT_SECONDS = 25
# Consultas qwinsta simultaneas. Conservador de proposito: 30 de uma vez
# contra a mesma rede e bem diferente de 8.
QWINSTA_MAX_WORKERS = 8


# Espera antes de refazer a lista da busca. Cada tecla destroi e recria os
# widgets do resultado, entao redesenhar a cada tecla trava a digitacao em
# listas grandes. 150ms nao e percebido como atraso.
SEARCH_DEBOUNCE_MS = 150


# Larguras das colunas de IP/hostname e de setor no resultado da busca. Fixas
# de proposito: sao elas que mantem enderecos e setores alinhados um embaixo do
# outro, para conferir contra o chamado. Se o setor variasse de largura, a
# coluna de IP entortaria a cada linha. O nome fica com a largura que sobrar,
# entao alargar a janela alarga a coluna do nome, que e a que corta.
SEARCH_HOST_COLUMN_WIDTH = 150


SEARCH_SECTOR_COLUMN_WIDTH = 130


VIEWER_ULTRAVNC = "ultravnc"


VIEWER_REALVNC = "realvnc"


VIEWER_OPTIONS = [VIEWER_ULTRAVNC, VIEWER_REALVNC]


DEFAULT_VIEWER = VIEWER_ULTRAVNC


LOGIN_MODE_AUTO = "auto"


LOGIN_MODE_MANUAL = "manual"


LOGIN_MODE_OPTIONS = {LOGIN_MODE_AUTO, LOGIN_MODE_MANUAL}


COLOR_SCHEME_PURPLE = "purple"


COLOR_SCHEME_BLUE = "blue"


COLOR_SCHEME_OPTIONS = {COLOR_SCHEME_PURPLE, COLOR_SCHEME_BLUE}


AUTH_TIMEOUT = 12


AUTH_TITLE_RE = r".*(UltraVNC|VNC).*(Auth|Authentication).*"


def _detect_install_root() -> Path:
    """Folder that holds data/ and logs/ — the application's install directory.

    Anchored on the ENTRY POINT, never on this module. Path(__file__).parent
    resolves to whatever file the line is written in, so the moment this code
    moves into a package it would point inside the package and data/ would
    follow it: bootstrap_directories() would then create a fresh empty data/
    there, seed the demo hosts.json into it and open a working application with
    the real host list orphaned on disk. Nothing raises, nothing is logged.

    VNC-Menu.pyw stays at the install root no matter how the code below it is
    arranged, so the entry script is the stable anchor.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    entry = getattr(sys.modules.get("__main__"), "__file__", None)
    if entry:
        return Path(entry).resolve().parent

    # Last resort (embedded interpreter, or __main__ without a file).
    return Path(sys.argv[0]).resolve().parent


SCRIPT_DIR = _detect_install_root()


DATA_DIR = SCRIPT_DIR / "data"


SHARED_HOSTS_JSON = DATA_DIR / "hosts.json"


TEMPLATE_VNC = DATA_DIR / "template.vnc"


# Shipped in the repository. template.vnc itself stays out of version control
# because an exported UltraVNC profile can carry a saved password.
TEMPLATE_VNC_EXAMPLE = DATA_DIR / "template.vnc.example"


REALVNC_DIR = DATA_DIR / "realvnc"


GLOBAL_PATHS_JSON = DATA_DIR / "paths.json"


LEGACY_PSEXEC_CONFIG_JSON = DATA_DIR / "psexec.json"


# Directories are created by bootstrap_directories() during startup, never at
# import time. An import-time failure in a .pyw has no console and no message
# box, so the application would simply not open.
USER_DATA_DIR = Path.home() / "Documents" / "VNC-Menu"


USER_HOSTS_JSON = USER_DATA_DIR / "hosts.json"


CREDS_JSON = USER_DATA_DIR / "creds.json"


SETTINGS_JSON = USER_DATA_DIR / "settings.json"


UPDATE_RESULT_JSON = USER_DATA_DIR / "update-result.json"


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


AUDIT_LOG = LOGS_DIR / f"{_SAFE_LOG_USERNAME}.log"


ERROR_LOG = LOGS_DIR / f"{_SAFE_LOG_USERNAME}_error.log"


# The error log is appended to, so it needs a size limit. One previous
# generation is kept as <nome>.log.1.
ERROR_LOG_MAX_BYTES = 2 * 1024 * 1024


# The audit log is append-only and lives in a shared installation folder, so
# it also needs a ceiling. One previous generation is kept as <nome>.log.1.
AUDIT_LOG_MAX_BYTES = 10 * 1024 * 1024


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


# Structure used by the "Vazia" option. DEFAULT_HOSTS carries two example hosts
# and must not be reused here: the dialog promises a list with no hosts.
EMPTY_HOSTS = {
    "units": [
        {
            "name": "Geral",
            "sectors": [
                {
                    "name": "Geral",
                    "hosts": [],
                }
            ],
        }
    ]
}


DEFAULT_SETTINGS = {
    "dark_mode": True,
    "color_scheme": COLOR_SCHEME_BLUE,
    "hosts_source": "",
    "hosts_file": "",
    "selected_unit": "Geral",
    "selected_sector": "Geral",
    "host_columns": 3,
    "main_window_size": "980x610",
    "window_geometries": {},
    # Legacy per-user keys kept only for automatic migration to data\paths.json.
    "ultravnc_exe": ULTRAVNC_EXE,
    "realvnc_exe": REALVNC_EXE,
    "login_mode": LOGIN_MODE_AUTO,
    "check_updates_on_startup": True,
    "skipped_update_version": "",
}


HOSTS_SOURCE_SHARED = "padrao"


HOSTS_SOURCE_CUSTOM = "personalizada"


HOSTS_SOURCE_EMPTY = "vazia"


HOSTS_SOURCE_OPTIONS = {HOSTS_SOURCE_SHARED, HOSTS_SOURCE_CUSTOM, HOSTS_SOURCE_EMPTY}
