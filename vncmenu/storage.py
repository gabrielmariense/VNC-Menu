"""Tudo que le e grava em disco.

hosts.json (compartilhado e pessoal), settings.json, paths.json,
creds.json e o modelo de dados dos hosts. Toda gravacao passa por
save_json(), que e atomica.

Depende de config, applog e dpapi.
"""

from pathlib import Path
import copy
import json
import os
import shutil
import unicodedata

from .config import CREDS_JSON, DATA_DIR, DEFAULT_HOSTS, DEFAULT_SETTINGS, DEFAULT_VIEWER, EMPTY_HOSTS, FALLBACK_SETTINGS_JSON, GLOBAL_PATHS_JSON, HOSTS_SOURCE_CUSTOM, HOSTS_SOURCE_EMPTY, HOSTS_SOURCE_OPTIONS, HOSTS_SOURCE_SHARED, LEGACY_PSEXEC_CONFIG_JSON, LOGIN_MODE_AUTO, LOGIN_MODE_OPTIONS, LOGS_DIR, PORT, REALVNC_DIR, REALVNC_EXE, SETTINGS_JSON, SHARED_HOSTS_JSON, TEMPLATE_VNC, TEMPLATE_VNC_EXAMPLE, ULTRAVNC_EXE, USER_DATA_DIR, USER_HOSTS_JSON, VIEWER_OPTIONS, VIEWER_REALVNC
from .applog import audit_log, log_exception
from .dpapi import dpapi_decrypt, dpapi_encrypt

def bootstrap_directories() -> list[str]:
    """Create the directories the application writes to, without ever raising.

    Replaces the old import-time initialize_data_files(). It returns a list of
    readable problems instead of propagating, because a failure here must not
    stop startup: audit_log(), log_exception() and save_json() all recreate
    their own parent directory on demand, so the application still runs with
    the logs folder or the shared data folder unavailable.
    """
    problems: list[str] = []

    for label, directory in (
        ("Dados do usuário", USER_DATA_DIR),
        ("Logs", LOGS_DIR),
        ("Dados compartilhados", DATA_DIR),
        ("Perfis RealVNC", REALVNC_DIR),
    ):
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            problems.append(f"{label}: {directory}\n    {exc}")

    try:
        if not SHARED_HOSTS_JSON.exists():
            save_json(DEFAULT_HOSTS, SHARED_HOSTS_JSON)
    except Exception as exc:
        problems.append(f"Lista padrão de hosts: {SHARED_HOSTS_JSON}\n    {exc}")

    # Seed template.vnc on a fresh install so UltraVNC connections work without
    # any manual step. An existing template.vnc is never touched: it belongs to
    # this installation and may carry tuned options.
    try:
        if not TEMPLATE_VNC.exists() and TEMPLATE_VNC_EXAMPLE.exists():
            shutil.copy2(TEMPLATE_VNC_EXAMPLE, TEMPLATE_VNC)
            audit_log("TEMPLATE_VNC_SEEDED", f"from={TEMPLATE_VNC_EXAMPLE}; to={TEMPLATE_VNC}")
    except Exception as exc:
        problems.append(f"Modelo UltraVNC: {TEMPLATE_VNC}\n    {exc}")

    return problems


def _load_legacy_psexec_path() -> str:
    """Read the pre-1.5.6 PsExec path file, if it exists."""
    try:
        if not LEGACY_PSEXEC_CONFIG_JSON.exists():
            return ""
        data = json.loads(LEGACY_PSEXEC_CONFIG_JSON.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return ""
        return str(data.get("psexec_exe") or "").strip()
    except Exception as exc:
        log_exception(exc)
        return ""


def _normalize_global_paths(data: dict | None, legacy_settings: dict | None = None) -> dict:
    data = data if isinstance(data, dict) else {}
    legacy_settings = legacy_settings if isinstance(legacy_settings, dict) else {}

    # An explicit empty PsExec value means "use PATH", so preserve it when
    # paths.json already contains the key instead of falling back to psexec.json.
    psexec_value = (
        data.get("psexec_exe")
        if "psexec_exe" in data
        else _load_legacy_psexec_path()
    )

    return {
        "ultravnc_exe": str(
            data.get("ultravnc_exe")
            or legacy_settings.get("ultravnc_exe")
            or ULTRAVNC_EXE
        ).strip(),
        "realvnc_exe": str(
            data.get("realvnc_exe")
            or legacy_settings.get("realvnc_exe")
            or REALVNC_EXE
        ).strip(),
        "psexec_exe": str(psexec_value or "").strip(),
    }


def load_global_paths(legacy_settings: dict | None = None) -> dict:
    """Load machine-wide executable paths shared by all users of this install."""
    if GLOBAL_PATHS_JSON.exists():
        try:
            data = json.loads(GLOBAL_PATHS_JSON.read_text(encoding="utf-8"))
            return _normalize_global_paths(data)
        except Exception as exc:
            # The file exists but could not be read: corrupt, or simply locked by
            # another instance on this machine. Never rewrite it here. A
            # transient read error must not erase the viewer and PsExec paths
            # configured for every user of this installation.
            log_exception(exc)
            audit_log("GLOBAL_PATHS_READ_ERROR", f"file={GLOBAL_PATHS_JSON}; error={exc}")

            backup = GLOBAL_PATHS_JSON.with_name(GLOBAL_PATHS_JSON.name + ".bak")
            try:
                if not backup.exists():
                    shutil.copy2(GLOBAL_PATHS_JSON, backup)
                    audit_log("GLOBAL_PATHS_BACKUP_CREATED", f"file={backup}")
            except Exception:
                pass

            return _normalize_global_paths({}, legacy_settings)

    # First run of 1.5.6: migrate the current user's old viewer paths and
    # the legacy psexec.json into one global paths.json file.
    if legacy_settings is None:
        try:
            legacy_settings = load_settings()
        except Exception:
            legacy_settings = {}

    paths = _normalize_global_paths({}, legacy_settings)
    try:
        save_json(paths, GLOBAL_PATHS_JSON)
    except Exception as exc:
        # Reading still works with defaults/legacy values even if this folder
        # is temporarily not writable. The settings UI will report save errors.
        log_exception(exc)
    return paths


def save_global_paths(paths: dict) -> bool:
    try:
        normalized = _normalize_global_paths(paths)
        return bool(save_json(normalized, GLOBAL_PATHS_JSON))
    except Exception as exc:
        log_exception(exc)
        return False


def load_psexec_path() -> str:
    return str(load_global_paths().get("psexec_exe") or "").strip()


def save_psexec_path(path: Path | str | None) -> bool:
    paths = load_global_paths()
    paths["psexec_exe"] = str(path or "").strip()
    return save_global_paths(paths)


def find_psexec() -> Path | None:
    # A configured global path takes priority over PATH.
    configured_path = load_psexec_path().strip().strip('"')
    if configured_path:
        candidate = Path(configured_path).expanduser()
        if candidate.is_file() and candidate.suffix.casefold() == ".exe":
            return candidate

    for executable in ("PsExec64.exe", "PsExec.exe", "psexec64", "psexec"):
        resolved = shutil.which(executable)
        if resolved:
            return Path(resolved)

    return None


def _atomic_write_text(path: Path, payload: str) -> None:
    """Write a file so a crash or a concurrent writer cannot leave it truncated.

    write_text() truncates the destination before writing, which can destroy
    hosts.json, settings.json, creds.json or the machine-wide paths.json if the
    process dies mid-write or two instances of the application write at the same
    time. The temporary file lives in the same directory so os.replace() stays
    atomic, and the PID keeps concurrent instances from colliding on it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        # No newline= argument: keep the platform line endings the previous
        # write_text() implementation produced.
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def save_json(data, path):
    path = Path(path)
    payload = json.dumps(data, ensure_ascii=False, indent=2)

    try:
        _atomic_write_text(path, payload)
        return True
    except PermissionError:
        # Common Windows case: settings.json was created as read-only or inherited
        # restrictive attributes. Try to clear the read-only bit once.
        if path.exists():
            path.chmod(0o666)
        _atomic_write_text(path, payload)
        return True


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


def normalize_login_mode(value) -> str:
    value = str(value or "").strip().lower()
    if value not in LOGIN_MODE_OPTIONS:
        return LOGIN_MODE_AUTO
    return value


def sanitize_port(value, default=PORT):
    """Return a valid TCP port, or the default when the value makes no sense."""
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return port if 1 <= port <= 65535 else default


def split_host_port(value, default=PORT):
    """Split "host::5901" or "host:1" into (host, port).

    Both spellings are the standard VNC convention and support types them into
    the host field out of habit:
      host::5901  -> porta 5901 explicita
      host:1      -> display 1, ou seja porta 5900 + 1
    Without this the port was appended a second time and the viewer received
    "host::5901::5900", which simply fails.
    """
    text = str(value or "").strip()
    if not text:
        return "", default

    if "::" in text:
        host, _, port_text = text.rpartition("::")
        if host and port_text.isdigit():
            return host.strip(), sanitize_port(port_text, default)
        return text, default

    host, sep, tail = text.rpartition(":")
    if sep and host and tail.isdigit():
        number = int(tail)
        # Under 100 it is a display number, exactly as vncviewer reads it.
        port = PORT + number if number < 100 else number
        return host.strip(), sanitize_port(port, default)

    return text, default


def format_host_port(host, port=PORT) -> str:
    """Display form: bare host on the default port, host::porta otherwise."""
    host = str(host or "").strip()
    port = sanitize_port(port)
    return host if port == PORT else f"{host}::{port}"


def sanitize_host_list(data):
    hosts = []
    if not isinstance(data, list):
        return hosts
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or f"Host {i + 1}").strip()
        raw_host = str(item.get("host") or item.get("ip") or "").strip()
        viewer = sanitize_viewer(item.get("viewer"))

        # An explicit "port" key wins; otherwise a port written into the host
        # itself is honoured, so older lists keep working either way.
        host, embedded_port = split_host_port(raw_host)
        port = sanitize_port(item.get("port"), embedded_port) if "port" in item else embedded_port

        if host:
            # Anotado porque "port" e int: sem isso o dict e inferido
            # como dict[str, str] e a atribuicao abaixo vira erro de tipo.
            entry: dict[str, str | int] = {"name": name or host, "host": host, "viewer": viewer}
            # Only stored when it differs, so existing hosts.json files are
            # untouched and diffs stay readable.
            if port != PORT:
                entry["port"] = port
            hosts.append(entry)
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
    # deepcopy, not dict.copy(): a shallow copy shares the "units" list with the
    # module-level DEFAULT_HOSTS, so any later in-place edit of the returned
    # structure would corrupt the defaults for the rest of the session.
    if not isinstance(data, dict):
        return copy.deepcopy(DEFAULT_HOSTS)

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

    return copy.deepcopy(DEFAULT_HOSTS)


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


def normalize_search_text(value) -> str:
    """Lowercase without accents, so "recepcao" finds "Recepção".

    Support types the machine name the way it appears in the ticket, which
    rarely carries the accents used in the host list.
    """
    text = str(value or "").strip().lower()
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def filter_unit_hosts(hosts_data, unit_name, query) -> list[tuple[str, dict]]:
    """Hosts of ONE unit matching the query, paired with their sector name.

    Scoped to a single unit on purpose: each site works inside its own unit,
    and whoever needs another one switches the unit selector.

    Matches name and host separately rather than against a joined string, so
    a query cannot straddle the boundary between the two fields. Returns
    (sector_name, host) in file order, which keeps the result list stable
    between identical searches. An empty query returns nothing; deciding what
    "no search" looks like belongs to the caller.
    """
    needle = normalize_search_text(query)
    if not needle:
        return []

    unit = get_unit_by_name(hosts_data, unit_name)
    if not unit:
        return []

    results: list[tuple[str, dict]] = []
    for sector in unit.get("sectors", []):
        if not isinstance(sector, dict):
            continue
        sector_name = str(sector.get("name") or "Geral")
        for item in sector.get("hosts", []):
            if not isinstance(item, dict):
                continue
            if (
                needle in normalize_search_text(item.get("name"))
                or needle in normalize_search_text(item.get("host"))
            ):
                results.append((sector_name, item))
    return results


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
    # Goes through save_json() so the credentials file is written atomically too.
    save_json({"user": user, "password": dpapi_encrypt(pwd)}, CREDS_JSON)


def _read_settings_file(path: Path) -> dict | None:
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            merged = DEFAULT_SETTINGS.copy()
            merged.update({key: data[key] for key in DEFAULT_SETTINGS if key in data})
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


def _settings_file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def load_settings():
    """
    Load the newest valid settings file.

    An old fallback file in AppData must not permanently override a newer
    settings.json in Documents, otherwise the previously selected host list
    can appear to reset when the application starts.
    """
    primary_settings = _read_settings_file(SETTINGS_JSON)
    fallback_settings = _read_settings_file(FALLBACK_SETTINGS_JSON)

    if primary_settings is not None and fallback_settings is not None:
        if _settings_file_mtime(FALLBACK_SETTINGS_JSON) > _settings_file_mtime(SETTINGS_JSON):
            return fallback_settings
        return primary_settings

    if primary_settings is not None:
        return primary_settings

    if fallback_settings is not None:
        return fallback_settings

    settings = DEFAULT_SETTINGS.copy()
    if not _write_settings_file(SETTINGS_JSON, settings):
        _write_settings_file(FALLBACK_SETTINGS_JSON, settings)
    return settings


def save_settings(settings):
    """
    Save to Documents when possible and use AppData only as a real fallback.

    When the primary save succeeds, remove a stale fallback file so future
    startups cannot load outdated values such as hosts_source.
    """
    if _write_settings_file(SETTINGS_JSON, settings):
        try:
            FALLBACK_SETTINGS_JSON.unlink(missing_ok=True)
        except OSError:
            pass
        return True

    return _write_settings_file(FALLBACK_SETTINGS_JSON, settings)


def get_ultravnc_exe() -> str:
    return str(load_global_paths().get("ultravnc_exe") or ULTRAVNC_EXE).strip()


def get_realvnc_exe() -> str:
    return str(load_global_paths().get("realvnc_exe") or REALVNC_EXE).strip()


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


def update_hosts_file_setting(settings) -> bool:
    source = normalize_hosts_source(settings.get("hosts_source")) or HOSTS_SOURCE_SHARED
    settings["hosts_source"] = source
    settings["hosts_file"] = str(get_hosts_path_for_source(source))
    return bool(save_settings(settings))


def copy_shared_hosts_to_user(overwrite=False):
    """
    Create the personal hosts file only when it does not already exist.

    A previously configured personal list must never be replaced merely because
    the user switched to the shared list and later selected Personalizada again.
    """
    USER_HOSTS_JSON.parent.mkdir(parents=True, exist_ok=True)

    if USER_HOSTS_JSON.exists() and not overwrite:
        return "existing"

    if SHARED_HOSTS_JSON.exists():
        shutil.copy2(SHARED_HOSTS_JSON, USER_HOSTS_JSON)
        return "copied"

    save_json(DEFAULT_HOSTS, USER_HOSTS_JSON)
    return "created_default"


def create_empty_user_hosts(overwrite=True):
    # EMPTY_HOSTS, not DEFAULT_HOSTS: the "Vazia" option promises a personal list
    # with no hosts, and the confirmation dialog already warned the user that the
    # existing personal list would be replaced.
    USER_HOSTS_JSON.parent.mkdir(parents=True, exist_ok=True)
    if USER_HOSTS_JSON.exists() and not overwrite:
        return "existing"
    save_json(EMPTY_HOSTS, USER_HOSTS_JSON)
    return "created_empty"


def set_hosts_source(settings, source: str, overwrite_user_file=True) -> bool:
    """Switch the active hosts list.

    Propagates OSError/PermissionError from preparing the personal file so the
    caller can report it. Returns False when the list was prepared but the
    preference itself could not be persisted.
    """
    source = normalize_hosts_source(source) or HOSTS_SOURCE_SHARED

    if source == HOSTS_SOURCE_CUSTOM:
        # Selecting Personalizada only changes the active source when a
        # personal hosts.json already exists. The shared list is copied only
        # on the first use, preventing accidental loss of custom hosts.
        personal_state = copy_shared_hosts_to_user(overwrite=False)
        audit_log(
            "PERSONAL_HOSTS_SOURCE_PREPARED",
            f"state={personal_state}; file={USER_HOSTS_JSON}",
        )

    elif source == HOSTS_SOURCE_EMPTY:
        create_empty_user_hosts(overwrite=overwrite_user_file)

    settings["hosts_source"] = source
    settings["hosts_file"] = str(get_hosts_path_for_source(source))
    return bool(save_settings(settings))
