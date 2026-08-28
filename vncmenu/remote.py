"""Operacoes remotas.

Conexao UltraVNC/RealVNC, reinicio, ping, qwinsta e consulta de
impressoras via PsExec. Tudo aqui bloqueia: chame de uma thread
trabalhadora e volte para o Tk com after(0, ...).

Depende de config, applog, storage, helpers e ui.dialogs.
"""

from pywinauto import Desktop
from pathlib import Path
import base64
import ctypes
import json
import os
import re
from pywinauto.keyboard import send_keys
import shutil
import subprocess
import tempfile
import threading
import time
from ctypes import wintypes

from concurrent.futures import ThreadPoolExecutor

from .config import QWINSTA_MAX_WORKERS, AUTH_TIMEOUT, AUTH_TITLE_RE, DEFAULT_VIEWER, ERROR_LOG, ERROR_LOG_MAX_BYTES, HOST_PING_PROCESS_TIMEOUT_SECONDS, HOST_PING_TIMEOUT_MS, PSEXEC_TIMEOUT_SECONDS, REALVNC_DIR, REALVNC_EXE, RESTART_TIMEOUT_SECONDS, TEMPLATE_VNC, ULTRAVNC_EXE, VIEWER_REALVNC
from .applog import audit_log, log_exception, rotate_log_if_needed
from .storage import format_host_port, sanitize_port, split_host_port, get_realvnc_exe, get_ultravnc_exe, load_creds, resolve_existing_exe, sanitize_viewer, viewer_display_name
from .helpers import realvnc_profile_name, safe_filename, show_error, show_info
from .ui.dialogs import show_realvnc_profile_dialog

# Separate handle: used only to confirm which window is in the foreground before
# the UltraVNC auto-login types a password. A failure here must not disable DPAPI.
try:
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
except Exception:
    user32 = None


def dialog_owns_foreground(dlg) -> bool:
    """True while the VNC authentication dialog is still the foreground window.

    GetForegroundWindow() returns the top-level window, so comparing it with the
    dialog handle is enough: focused child controls do not become foreground
    windows themselves.
    """
    if user32 is None:
        return False
    try:
        foreground = user32.GetForegroundWindow()
        if not foreground:
            return False
        try:
            handle = dlg.wrapper_object().handle
        except Exception:
            handle = dlg.handle
        return int(foreground) == int(handle)
    except Exception:
        return False


def _auth_dialog_candidates(process_id):
    """Search criteria for the auth dialog, most trustworthy first.

    AUTH_TITLE_RE is deliberately broad, so a window belonging to some other
    application can match it. Scoping the search to the viewer process we just
    started removes that ambiguity; the title-only search stays as a fallback
    because some UltraVNC builds relaunch themselves under a new PID.
    """
    candidates = []
    if process_id:
        candidates.append(({"title_re": AUTH_TITLE_RE, "process": int(process_id)}, "process"))
    candidates.append(({"title_re": AUTH_TITLE_RE}, "title"))
    return candidates


def auto_enter_uvnc_credentials(timeout=AUTH_TIMEOUT, process_id=None) -> bool:
    user, pwd = load_creds()
    if not user and not pwd:
        return False

    deadline = time.time() + timeout
    # Give the process-scoped match the first half of the window before allowing
    # the weaker title-only match.
    title_fallback_at = time.time() + (timeout / 2) if process_id else 0
    dlg = None
    matched_by = ""

    while time.time() < deadline and dlg is None:
        for criteria, label in _auth_dialog_candidates(process_id):
            if label == "title" and time.time() < title_fallback_at:
                continue
            try:
                candidate = Desktop(backend="win32").window(**criteria)
                if candidate.exists(timeout=0.2):
                    dlg = candidate
                    matched_by = label
                    break
            except Exception:
                pass
        if dlg is None:
            time.sleep(0.1)

    if dlg is None:
        return False

    if matched_by == "title":
        audit_log("VNC_AUTO_LOGIN_TITLE_FALLBACK", f"process_id={process_id or '-'}")

    try:
        dlg.wait("visible", timeout=2)
        dlg.set_focus()

        # A title-only match is not proof that this window belongs to the viewer,
        # so it must also be the window in front before anything is typed.
        if matched_by != "process" and not dialog_owns_foreground(dlg):
            audit_log("VNC_AUTO_LOGIN_ABORTED", "reason=untrusted_match_not_foreground")
            return False

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

        # Blind fallback: send_keys() types into whatever window currently holds
        # the foreground. Only type the password while the auth dialog is still
        # in front, otherwise it would leak into another application.
        if not dialog_owns_foreground(dlg):
            audit_log("VNC_AUTO_LOGIN_ABORTED", "reason=foreground_changed")
            return False

        if user:
            send_keys(user + "{TAB}" + pwd + "{ENTER}", with_spaces=True)
        else:
            send_keys(pwd + "{ENTER}", with_spaces=True)
        return True

    except Exception:
        return False


def start_uvnc_credential_autofill(process_id=None) -> None:
    """Wait for the UltraVNC authentication dialog without blocking Tkinter."""

    def worker():
        try:
            auto_enter_uvnc_credentials(process_id=process_id)
        except Exception as exc:
            log_exception(exc)
            audit_log("VNC_AUTO_LOGIN_ERROR", f"error={exc}")

    threading.Thread(
        target=worker,
        name="VNC-Credential-Autofill",
        daemon=True,
    ).start()


def launch_vnc(
    host: str,
    viewer: str = DEFAULT_VIEWER,
    display_name: str | None = None,
    sector_name: str | None = None,
    parent=None,
    automatic_login: bool = True,
    port: int | None = None,
):
    viewer = sanitize_viewer(viewer)

    # A port written into the host itself wins only when none was passed, so
    # "10.0.0.5::5901" typed by hand no longer gets a second port appended.
    host, embedded_port = split_host_port(host)
    port = sanitize_port(port, embedded_port) if port is not None else embedded_port
    target_name = str(display_name or host or "Host").strip()

    if not host:
        show_error(parent, "VNC", "Host/IP vazio.")
        audit_log("CONNECTION_BLOCKED", f"viewer={viewer}; reason=empty_host; name={target_name}")
        return

    audit_log(
        "CONNECTION_ATTEMPT",
        (
            f"viewer={viewer_display_name(viewer)}; name={target_name}; "
            f"host={format_host_port(host, port)}; setor={sector_name or '-'}; "
            f"login_mode={'automatico' if automatic_login else 'manual'}"
        ),
    )

    try:
        if viewer == VIEWER_REALVNC:
            configured_realvnc = get_realvnc_exe()
            realvnc_exe = resolve_existing_exe(configured_realvnc, REALVNC_EXE)

            if not realvnc_exe:
                audit_log("CONNECTION_ERROR", f"viewer=RealVNC; host={host}; reason=viewer_not_found; path={configured_realvnc}")
                show_error(parent, "Erro", f"RealVNC Viewer não encontrado:\n{configured_realvnc}")
                return

            if not automatic_login:
                subprocess.Popen(
                    # Bare host on 5900 keeps the previous command exactly.
                    [realvnc_exe, format_host_port(host, port)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=str(Path(realvnc_exe).parent),
                )
                audit_log(
                    "CONNECTION_STARTED",
                    (
                        f"viewer=RealVNC; name={target_name}; host={host}; "
                        "login_mode=manual; profile=bypassed"
                    ),
                )
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
            show_error(
                parent,
                "Erro",
                "O arquivo template.vnc não foi encontrado.\n\n"
                f"Esperado em:\n{TEMPLATE_VNC}\n\n"
                "Normalmente ele é criado automaticamente a partir de "
                "template.vnc.example na primeira execução. Se os dois estiverem "
                "faltando, copie o example para template.vnc, ou gere o seu no "
                "UltraVNC Viewer com \"Save connection settings as...\".\n\n"
                f"Veja: {TEMPLATE_VNC.parent / 'LEIA-ME-template-vnc.txt'}",
            )
            return

        # This is the launch behavior from the old working Tkinter version:
        # copy the template unchanged and pass the target as host::port.
        tmp_vnc = Path(tempfile.gettempdir()) / f"uvnc_{safe_filename(host)}.vnc"
        shutil.copyfile(TEMPLATE_VNC, tmp_vnc)

        cmd = [ultravnc_exe, "-config", str(tmp_vnc), f"{host}::{port}"]
        viewer_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(Path(ultravnc_exe).parent),
        )
        audit_log("CONNECTION_STARTED", f"viewer=UltraVNC; name={target_name}; host={host}; porta={port}; template={TEMPLATE_VNC}")

        if automatic_login:
            # The PID scopes the auth-dialog search to this viewer instance.
            start_uvnc_credential_autofill(viewer_process.pid)

    except Exception as e:
        audit_log("CONNECTION_ERROR", f"viewer={viewer_display_name(viewer)}; host={host}; error={e}")
        log_exception(e)
        show_error(parent, "Erro", f"Falha ao iniciar viewer VNC:\n{e}\n\nLog: {ERROR_LOG}")


def restart_host(host: str):
    """Send a remote restart. Blocking: call it from a worker thread."""
    host = str(host or "").strip().lstrip("\\")
    if not host:
        raise ValueError("Hostname ou IP não informado.")

    audit_log("RESTART_ATTEMPT", f"host={host}")

    try:
        completed = subprocess.run(
            ["shutdown", "/r", "/m", rf"\\{host}", "/t", "0", "/f"],
            capture_output=True,
            timeout=RESTART_TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        log_exception(exc)
        audit_log("RESTART_ERROR", f"host={host}; error=timeout_{RESTART_TIMEOUT_SECONDS}s")
        raise RuntimeError(
            f"O comando não respondeu em {RESTART_TIMEOUT_SECONDS} segundos.\n"
            "O computador pode estar inacessível ou bloqueando o acesso administrativo."
        ) from exc
    except Exception as exc:
        log_exception(exc)
        audit_log("RESTART_ERROR", f"host={host}; error={exc}")
        raise

    if completed.returncode != 0:
        # shutdown.exe explains the real cause (acesso negado, host não
        # encontrado). CalledProcessError would hide it behind an exit code.
        message = (
            _decode_process_output(completed.stderr).strip()
            or _decode_process_output(completed.stdout).strip()
            or f"O comando shutdown retornou o código {completed.returncode}."
        )
        audit_log("RESTART_ERROR", f"host={host}; code={completed.returncode}; error={message}")
        raise RuntimeError(message)

    audit_log("RESTART_SENT", f"host={host}")


def host_responds_to_ping(host: str) -> bool:
    host = str(host or "").strip().lstrip("\\")
    if not host:
        return False

    try:
        completed = subprocess.run(
            ["ping", "-n", "1", "-w", str(HOST_PING_TIMEOUT_MS), host],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=HOST_PING_PROCESS_TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        audit_log("HOST_PING_ERROR", f"host={host}; error={exc}")
        return False


class PsExecQueryError(RuntimeError):
    """Structured PsExec failure for remote printer queries."""

    def __init__(self, summary, hint, details="", returncode=None, category="unknown"):
        super().__init__(summary)
        self.summary = str(summary or "Falha ao executar o PsExec.")
        self.hint = str(hint or "Verifique os detalhes técnicos e tente novamente.")
        self.details = str(details or "")
        self.returncode = returncode
        self.category = str(category or "unknown")


def _decode_process_output(data) -> str:
    if not data:
        return ""
    if isinstance(data, str):
        return data
    encodings = ["utf-8"]
    if os.name == "nt":
        encodings.append("mbcs")
    encodings.extend(["cp850", "cp1252"])
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


# Windows system error codes that PsExec returns as its own exit code when the
# connection itself fails. Only codes that cannot plausibly be a PowerShell exit
# code are listed, since PsExec otherwise forwards the remote program's code.
# Consulted only after the message text yields nothing, and the raw STDOUT and
# STDERR are always shown in the details pane either way.
PSEXEC_RETURNCODE_DIAGNOSIS = {
    53: (  # ERROR_BAD_NETPATH
        "O PsExec não conseguiu acessar o computador remoto.",
        "Verifique o nome/IP, SMB, compartilhamento ADMIN$ e se a porta 445 está acessível.",
        "network_path",
    ),
    67: (  # ERROR_BAD_NET_NAME
        "O compartilhamento administrativo não foi encontrado.",
        "Confirme se o ADMIN$ está habilitado e acessível no computador remoto.",
        "admin_share",
    ),
    1326: (  # ERROR_LOGON_FAILURE
        "Falha de autenticação no computador remoto.",
        "Verifique as credenciais e se a conta pode executar tarefas administrativas remotamente.",
        "logon_failure",
    ),
    1460: (  # ERROR_TIMEOUT
        "Tempo esgotado ao conectar no computador remoto.",
        "O host respondeu ao ping, mas não à conexão administrativa. Verifique firewall, "
        "porta 445/SMB e se o compartilhamento ADMIN$ está acessível.",
        "connect_timeout",
    ),
    1722: (  # RPC_S_SERVER_UNAVAILABLE
        "O serviço RPC do computador remoto não respondeu.",
        "Verifique conectividade, firewall e os serviços RPC do Windows no destino.",
        "rpc_unavailable",
    ),
}


def _diagnose_psexec_failure(output: str, returncode: int | None = None):
    low = str(output or "").casefold()
    checks = [
        (("access is denied", "acesso negado", "error code 5", "erro 5"),
         "Acesso negado pelo PsExec.",
         "Confirme que sua conta possui administrador no computador remoto e acesso ao ADMIN$.",
         "access_denied"),
        (("logon failure", "falha de logon", "user name or password is incorrect"),
         "Falha de autenticação no computador remoto.",
         "Verifique as credenciais e se a conta pode executar tarefas administrativas remotamente.",
         "logon_failure"),
        (("network path was not found", "caminho da rede não foi encontrado", "error code 53", "erro 53"),
         "O PsExec não conseguiu acessar o computador remoto.",
         "Verifique o nome/IP, SMB, compartilhamento ADMIN$ e se a porta 445 está acessível.",
         "network_path"),
        (("network name cannot be found", "nome da rede não foi encontrado", "error code 67", "erro 67"),
         "O compartilhamento administrativo não foi encontrado.",
         "Confirme se o ADMIN$ está habilitado e acessível no computador remoto.",
         "admin_share"),
        (("timeout accessing", "timeout connecting", "tempo limite de acesso"),
         "Tempo esgotado ao conectar no computador remoto.",
         "O host respondeu ao ping, mas não à conexão administrativa. Verifique firewall, "
         "porta 445/SMB e se o compartilhamento ADMIN$ está acessível.",
         "connect_timeout"),
        (("rpc server is unavailable", "servidor rpc não está disponível", "servidor rpc não esta disponível"),
         "O serviço RPC do computador remoto não respondeu.",
         "Verifique conectividade, firewall e os serviços RPC do Windows no destino.",
         "rpc_unavailable"),
        (("could not start psexesvc", "failed to install psexesvc", "psexesvc service"),
         "O serviço temporário do PsExec não iniciou.",
         "Verifique permissões administrativas, antivírus/EDR e se a criação de serviços remotos está permitida.",
         "psexesvc"),
        (("error establishing communication", "erro ao estabelecer comunicação"),
         "O PsExec perdeu a comunicação com o serviço remoto.",
         "Tente novamente e verifique firewall, SMB e se algum antivírus/EDR bloqueou o PsExec.",
         "communication"),
        (("the system cannot find the file specified", "o sistema não pode encontrar o arquivo especificado"),
         "Um arquivo necessário não foi encontrado no computador remoto.",
         "Confira os detalhes técnicos. O PowerShell ou algum componente usado pela consulta pode estar indisponível.",
         "remote_file_missing"),
        (("the handle is invalid", "identificador é inválido", "identificador e invalido"),
         "O PsExec retornou um identificador inválido.",
         "Tente novamente. Se persistir, verifique bloqueios do PsExec por segurança/antivírus no destino.",
         "invalid_handle"),
    ]
    for needles, summary, hint, category in checks:
        if any(needle in low for needle in needles):
            return summary, hint, category
    # A tabela e indexada por int; None nunca deve chegar ao get().
    if returncode is not None:
        known = PSEXEC_RETURNCODE_DIAGNOSIS.get(returncode)
        if known:
            return known

    if returncode not in (None, 0):
        return (
            f"O PsExec terminou com código {returncode}.",
            "Abra os detalhes técnicos para ver a mensagem retornada pelo PsExec.",
            "exit_code",
        )
    return (
        "O PsExec não retornou o resultado esperado.",
        "Abra os detalhes técnicos para identificar a mensagem retornada pelo computador remoto.",
        "invalid_output",
    )


def _build_psexec_details(host, psexec_path, returncode, stdout="", stderr="") -> str:
    code_text = "não disponível" if returncode is None else str(returncode)
    stdout = str(stdout or "").strip() or "(vazio)"
    stderr = str(stderr or "").strip() or "(vazio)"
    return (
        f"Host: {host}\n"
        f"PsExec: {psexec_path}\n"
        f"Código de saída: {code_text}\n\n"
        f"STDOUT:\n{stdout}\n\n"
        f"STDERR:\n{stderr}"
    )


def log_psexec_failure(host, psexec_path, error: PsExecQueryError):
    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        rotate_log_if_needed(ERROR_LOG, ERROR_LOG_MAX_BYTES)
        with ERROR_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"\n[{timestamp}] PSEXEC PRINTER QUERY ERROR\n")
            handle.write(f"Category: {error.category}\n")
            handle.write(f"Summary: {error.summary}\n")
            handle.write(f"Hint: {error.hint}\n")
            handle.write(error.details or _build_psexec_details(host, psexec_path, error.returncode))
            handle.write("\n" + ("-" * 72) + "\n")
    except Exception:
        pass


def query_remote_printers(host: str, psexec_path: Path) -> str:
    host = str(host or "").strip().lstrip("\\")
    if not host:
        raise ValueError("Hostname ou IP não informado.")

    collector = r'''$ErrorActionPreference='SilentlyContinue'
$m1='__VNC_MENU_PRINTERS_BEGIN__';$m2='__VNC_MENU_PRINTERS_END__';$r=@();$ports=@{}
function Get-IP($value){
 $value=[string]$value
 if([string]::IsNullOrWhiteSpace($value)){return ''}
 if($value-match'(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)'){return $Matches[0]}
 try{return ([Net.Dns]::GetHostAddresses($value)|Where-Object{$_.AddressFamily-eq'InterNetwork'}|Select-Object -First 1).IPAddressToString}catch{return ''}
}
function Get-Address($port){
 if(!$port){return ''};$name=[string]$port.Name
 if($name-match'(?i)^USB'){return 'USB'}
 $ip=Get-IP $port.PrinterHostAddress;if(!$ip){$ip=Get-IP $name};return $ip
}
function Get-SharedAddress($server,$queue){
 if(!$server-or!$queue){return ''}
 $printer=Get-Printer -ComputerName $server -Name $queue
 if(!$printer){return ''}
 return (Get-Address (Get-PrinterPort -ComputerName $server -Name ([string]$printer.PortName)))
}
Get-PrinterPort|ForEach-Object{$ports[$_.Name]=$_}
Get-Printer|ForEach-Object{
 $name=[string]$_.Name;$port=$ports[[string]$_.PortName];$address=Get-Address $port;$connection=[string]$_.ConnectionName
 if(!$address-and$connection-match'^\\\\([^\\]+)\\(.+)$'){$address=Get-SharedAddress $Matches[1] $Matches[2]}
 if(!$address-and$name-match'^\\\\([^\\]+)\\(.+)$'){$address=Get-SharedAddress $Matches[1] $Matches[2]}
 if(!$address){$address='NÃO IDENTIFICADO'}
 if($name){$r+=[pscustomobject]@{Name=$name;IP=$address}}
}
if(!(Get-PSDrive HKU -ErrorAction SilentlyContinue)){New-PSDrive HKU Registry HKEY_USERS|Out-Null;$newHku=$true}
Get-ChildItem HKU:\|Where-Object{$_.PSChildName-match'^S-1-5-21-(?:\d+-){3}\d+$'}|ForEach-Object{
 Get-ChildItem "HKU:\$($_.PSChildName)\Printers\Connections"|ForEach-Object{
  $parts=@(($_.PSChildName-replace'^,,','')-split',')
  if($parts.Count-ge2){$server=[string]$parts[0];$queue=[string]($parts[1..($parts.Count-1)]-join',');$address=Get-SharedAddress $server $queue;if(!$address){$address='NÃO IDENTIFICADO'};$r+=[pscustomobject]@{Name="\\$server\$queue";IP=$address}}
 }
}
if($newHku){Remove-PSDrive HKU}
$json=ConvertTo-Json -InputObject @($r|Sort-Object Name,IP -Unique)-Compress
$payload=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
[Console]::Out.WriteLine($m1+$payload+$m2)'''

    encoded_command = base64.b64encode(collector.encode("utf-16-le")).decode("ascii")

    command = [
        str(psexec_path),
        rf"\\{host}",
        "-s",
        "-h",
        "-accepteula",
        "-nobanner",
        "-n",
        "5",
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        encoded_command,
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=PSEXEC_TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError as exc:
        details = _build_psexec_details(host, psexec_path, None, stderr=str(exc))
        raise PsExecQueryError(
            "PsExec não foi encontrado.",
            "Confira o caminho configurado em Configurações > PsExec.",
            details,
            category="local_not_found",
        ) from exc
    except PermissionError as exc:
        details = _build_psexec_details(host, psexec_path, None, stderr=str(exc))
        raise PsExecQueryError(
            "O Windows bloqueou a execução do PsExec.",
            "Verifique permissões do arquivo, antivírus/EDR e tente novamente.",
            details,
            category="local_permission",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        stdout = _decode_process_output(exc.stdout)
        stderr = _decode_process_output(exc.stderr)
        details = _build_psexec_details(host, psexec_path, None, stdout, stderr)
        raise PsExecQueryError(
            f"A consulta excedeu {PSEXEC_TIMEOUT_SECONDS} segundos.",
            "O host pode estar lento, o PsExec pode estar bloqueado ou a comunicação SMB pode ter travado.",
            details,
            category="timeout",
        ) from exc
    except OSError as exc:
        details = _build_psexec_details(host, psexec_path, None, stderr=str(exc))
        raise PsExecQueryError(
            "Não foi possível iniciar o PsExec.",
            "Confira o executável configurado e as permissões locais do arquivo.",
            details,
            category="local_launch",
        ) from exc

    stdout = _decode_process_output(completed.stdout)
    stderr = _decode_process_output(completed.stderr)
    combined_output = f"{stdout}\n{stderr}"

    start_marker = "__VNC_MENU_PRINTERS_BEGIN__"
    end_marker = "__VNC_MENU_PRINTERS_END__"
    match = re.search(
        re.escape(start_marker) + r"\s*([A-Za-z0-9+/=\r\n]+?)\s*" + re.escape(end_marker),
        combined_output,
    )

    if not match:
        summary, hint, category = _diagnose_psexec_failure(combined_output, completed.returncode)
        details = _build_psexec_details(
            host,
            psexec_path,
            completed.returncode,
            stdout,
            stderr,
        )
        raise PsExecQueryError(
            summary,
            hint,
            details,
            returncode=completed.returncode,
            category=category,
        )

    try:
        payload = re.sub(r"\s+", "", match.group(1))
        decoded_json = base64.b64decode(payload).decode("utf-8-sig")
        raw_rows = json.loads(decoded_json)
    except Exception as exc:
        details = _build_psexec_details(
            host,
            psexec_path,
            completed.returncode,
            stdout,
            stderr,
        )
        raise PsExecQueryError(
            "O resultado das impressoras chegou corrompido ou incompleto.",
            "Tente novamente. Se persistir, abra os detalhes para verificar a saída do PsExec.",
            details,
            returncode=completed.returncode,
            category="invalid_payload",
        ) from exc

    if isinstance(raw_rows, dict):
        raw_rows = [raw_rows]
    if not isinstance(raw_rows, list):
        raw_rows = []

    rows = []
    seen = set()
    for item in raw_rows:
        if not isinstance(item, dict):
            continue

        name = str(item.get("Name") or "").strip()
        ip = str(item.get("IP") or "").strip()

        if not ip:
            ip = "NÃO IDENTIFICADO"
        if not name:
            continue

        key = (name.casefold(), ip.casefold())
        if key in seen:
            continue
        seen.add(key)
        rows.append((name, ip))

    rows.sort(key=lambda row: (row[0].casefold(), row[1].casefold()))
    return format_printers_output(rows)


def format_printers_output(rows) -> str:
    if not rows:
        return "Nenhuma impressora encontrada."

    name_width = max(len("NOME"), *(len(name) for name, _ip in rows))
    lines = [
        f"{'NOME':<{name_width}}  IP",
        "-" * (name_width + 23),
    ]

    for name, ip in rows:
        lines.append(f"{name:<{name_width}}  {ip}")

    return "\n".join(lines)


def _query_logged_user(item):
    """Consulta um host. Devolve (nome, resultado) e nunca levanta."""
    name = str(item.get("name") or "Host")
    host = str(item.get("host") or "").strip()

    if not host:
        return (name, "SEM HOST")

    try:
        ping = subprocess.run(
            ["ping", "-n", "1", "-w", "800", host],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        if ping.returncode != 0:
            return (name, "OFFLINE")

        result = subprocess.run(
            ["qwinsta", f"/server:{host}"],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        output = result.stdout.strip()
        error = result.stderr.strip()

        if result.returncode != 0:
            return (name, error or output or "ERRO")

        users = []
        for line in output.splitlines()[1:]:
            parts = line.split()

            # Old working behavior: in Portuguese Windows output, the username
            # appears in this position for disconnected user sessions.
            if len(parts) >= 4:
                username = parts[1]
                if username.lower() not in ("services", "console", "rdp-tcp"):
                    users.append(username)

        return (name, ", ".join(users) if users else "VAZIO")

    except Exception as e:
        return (name, f"ERRO: {e}")


def query_all_logged_users(hosts, max_workers=QWINSTA_MAX_WORKERS):
    """Consulta os hosts em paralelo, preservando a ordem do setor.

    Era serial: ping (ate 3s) + qwinsta (ate 8s) por host, um de cada vez.
    Um setor com 30 maquinas, metade delas desligadas, chegava a vários
    minutos com a barra de progresso parada. Os hosts sao independentes,
    entao rodam juntos; pool.map devolve na ordem de entrada.
    """
    return format_users_output(query_logged_users_raw(hosts, max_workers))


def query_logged_users_raw(hosts, max_workers=QWINSTA_MAX_WORKERS):
    """Mesma consulta, devolvendo os pares (nome, resultado) sem formatar.

    A janela do OCS precisa comparar o usuario de cada maquina, nao exibir um
    relatorio de texto, entao consome esta versao. format_users_output() fica
    para quem quer o texto pronto.
    """
    items = list(hosts)
    if not items:
        return []

    workers = max(1, min(int(max_workers), len(items)))
    with ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix="VNC-Menu-Qwinsta",
    ) as pool:
        return list(pool.map(_query_logged_user, items))


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
