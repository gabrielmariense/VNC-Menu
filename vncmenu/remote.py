"""Operacoes remotas.

Conexao UltraVNC/RealVNC, reinicio, ping, qwinsta e consulta de
impressoras via PsExec. Tudo aqui bloqueia: chame de uma thread
trabalhadora e volte para o Tk com after(0, ...).

Depende de config, applog, storage, helpers e ui.dialogs.
"""

from pywinauto import Desktop
# send_keys NAO e importado de proposito: ele digita na janela em primeiro
# plano, nao na que encontramos. A credencial so e escrita com set_text(),
# amarrado ao handle do controle. Nao reintroduzir sem ler o comentario de
# auto_enter_uvnc_credentials().
from pathlib import Path
import base64
import ctypes
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import zlib
import time
from ctypes import wintypes

from concurrent.futures import ThreadPoolExecutor

from .config import QWINSTA_MAX_WORKERS, AUTH_TIMEOUT, AUTH_TITLE_RE, DEFAULT_VIEWER, ERROR_LOG, ERROR_LOG_MAX_BYTES, HOST_PING_PROCESS_TIMEOUT_SECONDS, HOST_PING_TIMEOUT_MS, PSEXEC_TIMEOUT_SECONDS, REALVNC_DIR, REALVNC_EXE, RESTART_TIMEOUT_SECONDS, SCRIPT_RUN_TIMEOUT_SECONDS, SCRIPT_RUN_WAIT_SECONDS, STARTUP_FOLDER, STARTUP_TASK_NAME, TEMPLATE_VNC, ULTRAVNC_EXE, VIEWER_REALVNC
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


def _describe_dialog(dlg) -> str:
    """Classes dos controles do dialogo, para o log quando nada casa.

    Sem isto, "nao achei os campos" e um beco sem saida: nao da para saber se
    o dialogo mudou, se o backend e outro ou se a janela nem era a certa.
    """
    try:
        classes = sorted({str(c.class_name()) for c in dlg.descendants()})
    except Exception:
        return "(nao foi possivel listar)"
    return ", ".join(classes)[:300] or "(sem filhos)"


def _find_credential_fields(dlg):
    """Campos de texto do dialogo. Devolve (campos, criterio_que_funcionou).

    O app usa backend="win32", onde o criterio e class_name="Edit".
    control_type e criterio de UIA e nao casa nada no win32 — era isso que a
    busca antiga usava, entao ela nunca achava campo nenhum e o preenchimento
    so acontecia pelo caminho "as cegas", que digitava no primeiro plano.
    Ou seja: o fallback inseguro era o unico que funcionava de verdade.
    """
    for criterio in ({"class_name": "Edit"}, {"control_type": "Edit"}):
        try:
            achados = list(dlg.descendants(**criterio))
        except Exception:
            continue
        if achados:
            return achados, next(iter(criterio))
    return [], ""


def _submit_auth_dialog(dlg) -> bool:
    """Confirma o dialogo sem usar o teclado global.

    send_keys() digita na janela que estiver em PRIMEIRO PLANO, nao na que
    encontramos: se o operador clicar em outro lugar no instante errado, o
    ENTER (e antes a senha) vai para la. Aqui so se usa o que e amarrado ao
    HANDLE da janela: clicar o botao pelo controle, e em ultimo caso postar
    VK_RETURN para o dialogo. Nenhum dos dois alcanca outra janela.
    """
    for titulo in ("OK", "&OK", "Conectar", "Logon", "Log On", "Entrar"):
        # class_name para o backend win32; control_type fica como segunda
        # tentativa, caso o backend mude um dia.
        for criterio in ({"class_name": "Button"}, {"control_type": "Button"}):
            try:
                botao = dlg.child_window(title=titulo, **criterio)
                if botao.exists(timeout=0.2):
                    botao.click()
                    return True
            except Exception:
                continue

    try:
        # 0x0100 WM_KEYDOWN / 0x0101 WM_KEYUP, 0x0D VK_RETURN.
        alvo = dlg.wrapper_object()
        alvo.post_message(0x0100, 0x0D, 0)
        alvo.post_message(0x0101, 0x0D, 0)
        return True
    except Exception:
        return False


def auto_enter_uvnc_credentials(timeout=AUTH_TIMEOUT, process_id=None,
                                cancel: threading.Event | None = None) -> bool:
    """Preenche o dialogo de autenticacao do UltraVNC.

    Regra que sustenta o resto: a senha e escrita SOMENTE com set_text(), que
    grava no controle pelo handle dele. Ao contrario de send_keys(), isso nao
    depende de quem esta em primeiro plano, entao a credencial nao tem como
    cair na barra de busca, num chat ou em qualquer campo que o operador
    clique enquanto o viewer abre.

    Nao existe mais caminho "as cegas": se os campos do dialogo nao forem
    encontrados, a funcao desiste e o operador digita. Perder esse fallback e
    o objetivo, nao um efeito colateral.

    `cancel` e checado no laco e imediatamente antes de cada escrita, para
    fechar o viewer realmente parar o preenchimento em vez de deixar a thread
    viva ate o timeout.
    """
    user, pwd = load_creds()
    if not user and not pwd:
        return False

    def cancelado() -> bool:
        return cancel is not None and cancel.is_set()

    deadline = time.time() + timeout
    # Give the process-scoped match the first half of the window before allowing
    # the weaker title-only match.
    title_fallback_at = time.time() + (timeout / 2) if process_id else 0
    dlg = None
    matched_by = ""

    while time.time() < deadline and dlg is None:
        if cancelado():
            audit_log("VNC_AUTO_LOGIN_ABORTED", "reason=cancelled_before_match")
            return False
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

        # Ultima checagem antes de escrever: a janela ainda existe e ninguem
        # cancelou. Fechar o viewer entre encontrar o dialogo e preencher era
        # o caso que deixava a credencial ser digitada depois do cancelamento.
        if cancelado():
            audit_log("VNC_AUTO_LOGIN_ABORTED", "reason=cancelled_before_typing")
            return False
        if not dlg.exists():
            audit_log("VNC_AUTO_LOGIN_ABORTED", "reason=dialog_closed")
            return False

        # Um match so por titulo nao prova que a janela e do viewer que
        # iniciamos, entao ela tambem precisa estar em primeiro plano.
        if matched_by != "process" and not dialog_owns_foreground(dlg):
            audit_log("VNC_AUTO_LOGIN_ABORTED", "reason=untrusted_match_not_foreground")
            return False

        edits, criterio = _find_credential_fields(dlg)

        if not edits:
            # Sem campos identificados nao ha onde escrever com seguranca. As
            # classes vao no log para o proximo diagnostico nao ser chute.
            audit_log(
                "VNC_AUTO_LOGIN_ABORTED",
                f"reason=no_edit_controls; controles={_describe_dialog(dlg)}",
            )
            return False

        audit_log(
            "VNC_AUTO_LOGIN_FIELDS",
            f"criterio={criterio}; campos={len(edits)}",
        )

        if len(edits) == 1:
            edits[0].set_text(pwd)
        else:
            if user:
                edits[0].set_text(user)
            if cancelado():
                audit_log("VNC_AUTO_LOGIN_ABORTED", "reason=cancelled_mid_fill")
                return False
            edits[1].set_text(pwd)

        if cancelado():
            audit_log("VNC_AUTO_LOGIN_ABORTED", "reason=cancelled_before_submit")
            return False

        _submit_auth_dialog(dlg)
        return True

    except Exception:
        return False


# Cancelamento do preenchimento em andamento. Uma conexao nova cancela a
# anterior: duas tentativas vivas ao mesmo tempo disputariam o mesmo dialogo.
_autofill_cancel: threading.Event | None = None
_autofill_lock = threading.Lock()


def cancel_uvnc_credential_autofill() -> None:
    """Cancela o preenchimento em andamento, se houver."""
    global _autofill_cancel
    with _autofill_lock:
        if _autofill_cancel is not None:
            _autofill_cancel.set()
            _autofill_cancel = None


def start_uvnc_credential_autofill(process_id=None):
    """Espera o dialogo de autenticacao sem travar o Tkinter.

    Devolve o Event de cancelamento, que tambem fica guardado no modulo: a
    proxima conexao cancela esta antes de comecar a sua.

    NAO existe mais vigia do processo do viewer. Ele foi tentado e quebrou o
    preenchimento: alguns builds do UltraVNC se relancam sob um PID novo (e o
    que _auth_dialog_candidates ja documentava), entao o processo original
    morre em milissegundos e "processo saiu" nao significa "o operador
    desistiu". O que protege a credencial e escrever so com set_text(), preso
    ao handle do controle, mais a checagem de dlg.exists() antes de digitar.
    """
    global _autofill_cancel

    cancel_uvnc_credential_autofill()
    cancel = threading.Event()
    with _autofill_lock:
        _autofill_cancel = cancel

    def worker():
        global _autofill_cancel
        try:
            auto_enter_uvnc_credentials(process_id=process_id, cancel=cancel)
        except Exception as exc:
            log_exception(exc)
            audit_log("VNC_AUTO_LOGIN_ERROR", f"error={exc}")
        finally:
            cancel.set()
            with _autofill_lock:
                if _autofill_cancel is cancel:
                    _autofill_cancel = None

    threading.Thread(
        target=worker,
        name="VNC-Credential-Autofill",
        daemon=True,
    ).start()
    return cancel


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
            # O PID restringe a busca do dialogo a esta instancia do viewer.
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


def _run_psexec(command, host, psexec_path, timeout_seconds):
    """Executa o PsExec e traduz as falhas locais em PsExecQueryError.

    Extraido de query_remote_printers para que a execucao de script use as
    mesmas mensagens: o que muda entre os dois e so o payload e o limite de
    tempo, nunca o diagnostico de "PsExec nao abriu".
    """
    try:
        return subprocess.run(
            command,
            capture_output=True,
            timeout=timeout_seconds,
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
            f"A operação excedeu {timeout_seconds} segundos.",
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



# Limite do CreateProcess para a linha de comando inteira. O -EncodedCommand
# do PowerShell e base64 de UTF-16LE, ou seja ~2,67 caracteres de linha para
# cada caractere de script: 12 KB de payload ja estouram 32 KB de linha. Foi
# assim que a execucao do script parou de sair do lugar com
# "[WinError 206] O nome do arquivo ou a extensao e muito grande", levantado
# pelo subprocess aqui, antes de qualquer coisa chegar na maquina remota.
COMMAND_LINE_LIMIT = 32767


def _encoded_command(script: str) -> str:
    """Comprime o script e devolve o -EncodedCommand do carregador.

    Comprimir em vez de encurtar o script: o payload cresce conforme o
    diagnostico melhora, e cortar comentario para caber de novo seria trocar
    o que explica o codigo por espaco em linha de comando. Deflate cru
    (wbits=-15) e o que o DeflateStream do .NET le.
    """
    bruto = zlib.compressobj(9, zlib.DEFLATED, -15)
    comprimido = bruto.compress(script.encode("utf-8")) + bruto.flush()
    carga = base64.b64encode(comprimido).decode("ascii")

    carregador = (
        "$d=[IO.Compression.DeflateStream]::new("
        f"[IO.MemoryStream]::new([Convert]::FromBase64String('{carga}')),"
        "[IO.Compression.CompressionMode]::Decompress);"
        "$r=[IO.StreamReader]::new($d,[Text.Encoding]::UTF8);"
        "$s=$r.ReadToEnd();$r.Dispose();"
        "Invoke-Expression $s"
    )

    codificado = base64.b64encode(carregador.encode("utf-16-le")).decode("ascii")
    if len(codificado) >= COMMAND_LINE_LIMIT - 512:
        # Folga para o resto da linha (PsExec, host, flags). Estourar aqui
        # seria o mesmo WinError 206, so que mais dificil de ler.
        raise PsExecQueryError(
            "O comando ficou grande demais para a linha de comando do Windows.",
            "Isso é um defeito do aplicativo, não da máquina remota.",
            f"Comando codificado: {len(codificado)} caracteres; "
            f"limite: {COMMAND_LINE_LIMIT}.",
            category="command_too_long",
        )
    return codificado

def _truncated_output(output, begin_marker, end_marker):
    """True quando a saida comecou a chegar e foi cortada no meio.

    O marcador de abertura presente sem o de fechamento e a assinatura de
    saida truncada: o script remoto rodou e escreveu, mas o texto nao chegou
    inteiro. Sem distinguir isso, a falha aparecia como "o PsExec nao
    retornou o resultado esperado", que manda investigar o lado errado.
    """
    texto = str(output or "")
    return begin_marker in texto and end_marker not in texto


def _truncation_error(host, psexec_path, returncode, stdout, stderr):
    """Erro especifico de saida cortada, com o diagnostico certo."""
    return PsExecQueryError(
        "A resposta do computador remoto chegou incompleta.",
        "O comando rodou e comecou a responder, mas a saida foi cortada no "
        "meio. Costuma ser a saida do PowerShell sendo fechada antes de "
        "esvaziar o buffer. Tente novamente; se repetir sempre nessa "
        "máquina, os detalhes técnicos mostram o quanto chegou.",
        _build_psexec_details(host, psexec_path, returncode, stdout, stderr),
        returncode=returncode,
        category="truncated_output",
    )


def query_remote_printers(host: str, psexec_path: Path) -> str:
    host = str(host or "").strip().lstrip("\\")
    if not host:
        raise ValueError("Hostname ou IP não informado.")

    # O coletor resolve o endereco de cada fila compartilhada consultando o
    # SERVIDOR de impressao. Antes fazia isso fila a fila: duas chamadas RPC
    # remotas por fila, repetidas para cada perfil de usuario da maquina. Numa
    # estacao com dez perfis isso passava de quarenta idas e voltas em serie.
    # Agora cada servidor e lido UMA vez para um hashtable e o resto e busca
    # local. O caminho fila a fila continua existindo como reserva, para o
    # servidor que permite consultar uma fila mas nao enumerar o conjunto.
    collector = r'''$ErrorActionPreference='SilentlyContinue';$ProgressPreference='SilentlyContinue'
$m1='__VNC_MENU_PRINTERS_BEGIN__';$m2='__VNC_MENU_PRINTERS_END__';$r=@();$ports=@{}
$dnsCache=@{};$serverCache=@{}
function Get-IP($value){
 $value=[string]$value
 if([string]::IsNullOrWhiteSpace($value)){return ''}
 if($value-match'(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)'){return $Matches[0]}
 if($dnsCache.ContainsKey($value)){return $dnsCache[$value]}
 $ip=''
 try{$ip=([Net.Dns]::GetHostAddresses($value)|Where-Object{$_.AddressFamily-eq'InterNetwork'}|Select-Object -First 1).IPAddressToString}catch{$ip=''}
 $dnsCache[$value]=$ip
 return $ip
}
function Get-Address($port){
 if(!$port){return ''};$name=[string]$port.Name
 if($name-match'(?i)^USB'){return 'USB'}
 $ip=Get-IP $port.PrinterHostAddress;if(!$ip){$ip=Get-IP $name};return $ip
}
function Get-ServerMap($server){
 if($serverCache.ContainsKey($server)){return $serverCache[$server]}
 $portas=@{};$mapa=@{}
 foreach($p in @(Get-PrinterPort -ComputerName $server)){$portas[[string]$p.Name]=$p}
 foreach($q in @(Get-Printer -ComputerName $server)){$mapa[[string]$q.Name]=$portas[[string]$q.PortName]}
 $serverCache[$server]=$mapa
 return $mapa
}
function Get-SharedAddress($server,$queue){
 if(!$server-or!$queue){return ''}
 $mapa=Get-ServerMap $server
 if($null -ne $mapa -and $mapa.ContainsKey($queue) -and $null -ne $mapa[$queue]){
  return (Get-Address $mapa[$queue])
 }
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
 # Este Get-Printer roda como SYSTEM, entao as conexoes de rede que ele
 # enxerga sao as do perfil do SYSTEM - nunca as do usuario. As do usuario
 # vem da varredura do HKEY_USERS logo abaixo. Listar as daqui misturava a
 # sobra deixada pela instalacao de drivers com as impressoras reais da
 # pessoa, e o suporte via no relatorio uma fila que a maquina nao tinha.
 if($name-and$name-notmatch'^\\\\'){$r+=[pscustomobject]@{Name=$name;IP=$address}}
}
if(!(Get-PSDrive HKU -ErrorAction SilentlyContinue)){New-PSDrive HKU Registry HKEY_USERS|Out-Null;$newHku=$true}
$conexoes=@{}
Get-ChildItem HKU:\|Where-Object{$_.PSChildName-match'^S-1-5-21-(?:\d+-){3}\d+$'}|ForEach-Object{
 Get-ChildItem "HKU:\$($_.PSChildName)\Printers\Connections"|ForEach-Object{
  $parts=@(($_.PSChildName-replace'^,,','')-split',')
  if($parts.Count-ge2){$server=[string]$parts[0];$queue=[string]($parts[1..($parts.Count-1)]-join',');$chave="\\$server\$queue";if(!$conexoes.ContainsKey($chave)){$conexoes[$chave]=@($server,$queue)}}
 }
}
if($newHku){Remove-PSDrive HKU}
foreach($chave in @($conexoes.Keys)){
 $par=$conexoes[$chave];$address=Get-SharedAddress $par[0] $par[1]
 if(!$address){$address='NÃO IDENTIFICADO'}
 $r+=[pscustomobject]@{Name=$chave;IP=$address}
}
$json=ConvertTo-Json -InputObject @($r|Sort-Object Name,IP -Unique)-Compress
$payload=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
[Console]::Out.WriteLine($m1+$payload+$m2)
[Console]::Out.Flush()'''

    encoded_command = _encoded_command(collector)

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

    completed = _run_psexec(command, host, psexec_path, PSEXEC_TIMEOUT_SECONDS)

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
        if _truncated_output(combined_output, start_marker, end_marker):
            raise _truncation_error(
                host, psexec_path, completed.returncode, stdout, stderr)
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

    A janela de sessoes precisa comparar o usuario de cada maquina, nao
    exibir um relatorio de texto, entao consome esta versao. format_users_output() fica
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



# --------------------------------------------------------------- run script

# Caracteres que o Windows nao aceita em nome de arquivo. Barra e dois-pontos
# entram aqui de proposito: o campo e um NOME, nao um caminho, para ninguem
# apontar a execucao para fora da pasta de inicializacao.
_INVALID_NAME_CHARS = set('\\/:*?"<>|')

# Cada valor de Status que o PowerShell remoto pode devolver, com o texto
# mostrado ao operador. A chave vem do script; o texto fica aqui, em um lugar
# so, para a janela nao montar mensagem por conta propria.
SCRIPT_RUN_STATUS = {
    "ok": "Script executado no contexto do usuário logado.",
    "no_folder": "A pasta de inicialização não existe no computador remoto.",
    "no_script": "O arquivo não foi encontrado na pasta de inicialização.",
    "no_user": "Nenhum usuário logado no computador remoto.",
    "user_unknown": "Não foi possível descobrir quem está logado no computador remoto.",
    "register_failed": "Não foi possível criar a tarefa agendada no computador remoto.",
    "start_failed": "A tarefa agendada foi criada, mas não iniciou.",
    "not_started": "A tarefa foi criada e disparada, mas nunca entrou em execução.",
    "timeout": "O script começou a rodar, mas não terminou dentro do tempo de espera.",
}

# Por qual caminho descobrimos quem esta logado. Aparece no relatorio porque
# cair no terceiro e o sinal de que o WMI da maquina esta ruim, mesmo quando o
# resto da execucao deu certo.
SCRIPT_USER_METHOD = {
    "cim": "via WMI",
    "explorer_cim": "via WMI, pelo explorer",
    "explorer_token": "pelo token do explorer — o WMI não respondeu",
}

SCRIPT_RUN_HINT = {
    "no_folder": "Confirme o caminho no computador remoto abrindo a pasta pelo botão ao lado.",
    "no_script": "Use o botão de abrir a pasta e confira o nome exato do arquivo.",
    "no_user": "Com a sessão vazia não há token de usuário para usar. "
               "Rodar como SYSTEM mapearia as impressoras no perfil errado, "
               "então nada foi executado.",
    # Diferente de no_user de proposito: aqui a sessao pode muito bem estar
    # ocupada. O que houve foi as consultas falharem, e o sintoma classico e
    # o repositorio WMI corrompido - o mesmo que derruba Get-Printer e
    # Add-Printer e aparece como "namespace invalido" na fase de drivers.
    "user_unknown": "As três consultas de sessão falharam, então não dá para "
                    "saber se a sessão está vazia. Nada foi executado. Se a "
                    "fase de drivers acusou \"namespace inválido\", o "
                    "repositório WMI da máquina está corrompido: nesse "
                    "computador, rode "
                    "\"winmgmt /verifyrepository\" e, se acusar problema, "
                    "\"winmgmt /salvagerepository\".",
    "register_failed": "A política de tarefas agendadas pode estar bloqueando "
                       "o logon interativo. Veja a mensagem do Windows abaixo.",
    "start_failed": "Veja a mensagem do Windows abaixo.",
    "not_started": "Normalmente é o usuário ter deslogado entre a consulta e a "
                   "execução, ou política bloqueando a tarefa.",
    "timeout": f"A espera é de {SCRIPT_RUN_WAIT_SECONDS}s. A tarefa foi removida, "
               "mas o script pode continuar rodando na máquina.",
}


def validate_script_name(name: str) -> str:
    """Valida o nome do arquivo digitado. Devolve o nome limpo ou levanta.

    So o nome, sem caminho: o script roda sempre dentro da pasta de
    inicializacao, entao aceitar "..\\..\\algo.vbs" abriria execucao remota de
    qualquer arquivo da maquina a partir de um campo de texto.
    """
    name = str(name or "").strip().strip('"')
    if not name:
        raise ValueError("Digite o nome do arquivo do script.")
    if any(char in _INVALID_NAME_CHARS for char in name):
        raise ValueError(
            "Digite apenas o nome do arquivo, sem caminho "
            "(por exemplo: IMPRESSORAS.vbs)."
        )
    if name in (".", ".."):
        raise ValueError("Nome de arquivo inválido.")
    # A lista de extensoes vem de SCRIPT_HOSTS: aceitar aqui uma extensao que
    # nao tem host definido la daria erro so na hora de montar a tarefa.
    if not name.casefold().endswith(tuple(SCRIPT_HOSTS)):
        raise ValueError("O arquivo precisa terminar em .vbs, .cmd ou .bat.")
    return name


def _powershell_single_quoted(value: str) -> str:
    """Literal PowerShell entre aspas simples (aspas simples dobram)."""
    return "'" + str(value).replace("'", "''") + "'"


# Qual host de script usar para cada extensao, e com quais chaves.
#
# wscript e o host SEM console: o .vbs roda invisivel, e o usuario nao tem
# janela para fechar no meio (fechar o console do cscript matava o script,
# possivelmente depois de apagar as impressoras e antes de remapear).
# //B e o modo batch: sem banner e sem caixa de dialogo de erro na tela dele.
#
# .cmd e .bat nao tem equivalente: o cmd.exe abre console e nao ha chave que
# esconda. Fica documentado em vez de fingir que some.
SCRIPT_HOSTS = {
    ".vbs": ("wscript.exe", "//nologo //B"),
    ".cmd": ("cmd.exe", "/c"),
    ".bat": ("cmd.exe", "/c"),
}


def script_host_command(script_name: str):
    """Devolve (executavel, argumentos) para rodar o script informado."""
    nome = str(script_name or "").strip()
    for extensao, comando in SCRIPT_HOSTS.items():
        if nome.casefold().endswith(extensao):
            return comando
    raise ValueError("O arquivo precisa terminar em .vbs, .cmd ou .bat.")


def script_runs_hidden(script_name: str) -> bool:
    """True quando a execucao nao abre janela nenhuma na tela do usuario."""
    try:
        executavel, _args = script_host_command(script_name)
    except ValueError:
        return False
    return executavel == "wscript.exe"


def _build_run_script_payload(script_name: str) -> str:
    """Monta o PowerShell que roda como SYSTEM no computador remoto.

    Ele NAO executa o script diretamente: AddWindowsPrinterConnection e
    SetDefaultPrinter gravam no HKCU de quem chama, entao rodar como SYSTEM
    mapearia as impressoras no perfil do SYSTEM e o usuario nao veria nada
    mudar. O caminho e uma tarefa agendada com LogonType Interactive, que usa
    o token da sessao ja aberta e por isso nao precisa da senha do usuario.
    """
    name = _powershell_single_quoted(script_name)
    folder = _powershell_single_quoted(STARTUP_FOLDER)
    task = _powershell_single_quoted(STARTUP_TASK_NAME)
    wait = int(SCRIPT_RUN_WAIT_SECONDS)
    executavel, argumento = script_host_command(script_name)
    exe = _powershell_single_quoted(executavel)
    # Um pouco acima da espera: se a tarefa travar, quem a mata e o Windows,
    # nao o app, que ja terá removido a tarefa e ido embora.
    limite = int(SCRIPT_RUN_WAIT_SECONDS) + 120

    return f"""$ErrorActionPreference='SilentlyContinue';$ProgressPreference='SilentlyContinue'
$m1='__VNC_MENU_RUNVBS_BEGIN__';$m2='__VNC_MENU_RUNVBS_END__'
$folder={folder};$name={name};$task={task}
$o=[ordered]@{{Status='';User='';MetodoUsuario='';MetodoTarefa='';Script='';Available=@();LastResult=$null;Detail='';Ms=0;MsPreparo=0;MsScript=0}}
$faseInicio=Get-Date
function Send($s,$d){{
 $o.Status=$s;$o.Detail=[string]$d
 $o.Ms=[int]((Get-Date)-$faseInicio).TotalMilliseconds
 $j=ConvertTo-Json -InputObject $o -Compress -Depth 4
 [Console]::Out.WriteLine($m1+[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($j))+$m2)
 [Console]::Out.Flush()
 exit
}}
if(-not (Test-Path -LiteralPath $folder -PathType Container)){{Send 'no_folder' $folder}}
$o.Available=@(Get-ChildItem -LiteralPath $folder -File | ForEach-Object{{$_.Name}})
$file=Join-Path $folder $name
$o.Script=$file
if(-not (Test-Path -LiteralPath $file -PathType Leaf)){{Send 'no_script' ''}}
# Quem esta logado, por tres caminhos independentes. O primeiro e o segundo
# passam pelo WMI; num computador com o repositorio WMI corrompido os dois
# falham, e ate a 2.5.2 isso era reportado como "ninguem logado" - conclusao
# errada, tirada de uma pergunta que nao chegou a ser respondida. O terceiro
# (Get-Process -IncludeUserName, que le o token do processo direto) nao passa
# por WMI, e $falhou separa "a sessao esta vazia" de "nao consegui perguntar".
$u='';$metodo='';$falhou=$false
try{{
 $u=[string](Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop).UserName
 if($u){{$metodo='cim'}}
}}catch{{$falhou=$true}}
if(-not $u){{
 try{{
  foreach($proc in @(Get-CimInstance -ClassName Win32_Process -Filter "Name='explorer.exe'" -ErrorAction Stop)){{
   $ow=Invoke-CimMethod -InputObject $proc -MethodName GetOwner -ErrorAction Stop
   if($ow -and $ow.User){{
    if($ow.Domain){{$u="$($ow.Domain)\\$($ow.User)"}}else{{$u=[string]$ow.User}}
    $metodo='explorer_cim'
    break
   }}
  }}
 }}catch{{$falhou=$true}}
}}
if(-not $u){{
 try{{
  foreach($proc in @(Get-Process -Name explorer -IncludeUserName -ErrorAction Stop)){{
   if($proc.UserName){{$u=[string]$proc.UserName;$metodo='explorer_token';break}}
  }}
 }}catch{{$falhou=$true}}
}}
$o.User=$u
$o.MetodoUsuario=$metodo
if(-not $u){{
 if($falhou){{Send 'user_unknown' ''}}
 Send 'no_user' ''
}}
# --- Criacao da tarefa, por dois caminhos -----------------------------------
# O modulo ScheduledTasks e CDXML: fala com o provedor WMI do agendador. Numa
# maquina com o repositorio WMI corrompido os New-ScheduledTask* devolvem nada
# e o Register reclama de InputObject nulo - foi assim que isso apareceu em
# campo. O COM Schedule.Service e a API classica do agendador, nao passa por
# WMI, e faz registro, execucao, leitura de estado e remocao. Por isso e a
# segunda tentativa, e nao a primeira: o modulo esta em producia funcionando
# no resto do parque e trocar o caminho de todo mundo seria risco sem motivo.
$viaCom=$false;$pasta=$null;$erroModulo=''
try{{Unregister-ScheduledTask -TaskName $task -Confirm:$false}}catch{{}}
$def=$null
try{{
 $act=New-ScheduledTaskAction -Execute {exe} -Argument ('{argumento} "'+$file+'"') -WorkingDirectory $folder
 $pri=New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive
 $cfg=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Seconds {limite})
 if($act -and $pri -and $cfg){{$def=New-ScheduledTask -Action $act -Principal $pri -Settings $cfg}}
 else{{$erroModulo='os cmdlets do modulo ScheduledTasks nao devolveram nada'}}
}}catch{{$def=$null;$erroModulo=[string]$_.Exception.Message}}
if($def){{
 try{{
  Register-ScheduledTask -TaskName $task -InputObject $def -Force -ErrorAction Stop|Out-Null
  $o.MetodoTarefa='modulo'
 }}catch{{$def=$null;$erroModulo=[string]$_.Exception.Message}}
}}
if(-not $def){{
 try{{
  $svc=New-Object -ComObject Schedule.Service
  $svc.Connect()
  $pasta=$svc.GetFolder('\\')
  try{{$pasta.DeleteTask($task,0)}}catch{{}}
  $cmdXml=[Security.SecurityElement]::Escape([string]{exe})
  $argXml=[Security.SecurityElement]::Escape('{argumento} "'+$file+'"')
  $dirXml=[Security.SecurityElement]::Escape([string]$folder)
  $usrXml=[Security.SecurityElement]::Escape([string]$u)
  $xml=@"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
 <Principals>
  <Principal id="Author">
   <UserId>$usrXml</UserId>
   <LogonType>InteractiveToken</LogonType>
   <RunLevel>LeastPrivilege</RunLevel>
  </Principal>
 </Principals>
 <Settings>
  <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
  <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
  <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
  <AllowHardTerminate>true</AllowHardTerminate>
  <StartWhenAvailable>false</StartWhenAvailable>
  <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
  <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
  <AllowStartOnDemand>true</AllowStartOnDemand>
  <Enabled>true</Enabled>
  <Hidden>false</Hidden>
  <RunOnlyIfIdle>false</RunOnlyIfIdle>
  <WakeToRun>false</WakeToRun>
  <ExecutionTimeLimit>PT{limite}S</ExecutionTimeLimit>
  <Priority>7</Priority>
 </Settings>
 <Actions Context="Author">
  <Exec>
   <Command>$cmdXml</Command>
   <Arguments>$argXml</Arguments>
   <WorkingDirectory>$dirXml</WorkingDirectory>
  </Exec>
 </Actions>
</Task>
"@
  # 6 = TASK_CREATE_OR_UPDATE, 3 = TASK_LOGON_INTERACTIVE_TOKEN. Mesmo
  # principal do caminho do modulo: usa o token da sessao ja aberta, sem senha.
  $pasta.RegisterTask($task,$xml,6,$null,$null,3)|Out-Null
  $viaCom=$true;$o.MetodoTarefa='com'
 }}catch{{
  $detalhe=[string]$_.Exception.Message
  if($erroModulo){{$detalhe=$erroModulo+' | COM: '+$detalhe}}
  Send 'register_failed' $detalhe
 }}
}}
$o.MsPreparo=[int]((Get-Date)-$faseInicio).TotalMilliseconds

# Dali para baixo o codigo nao pode mais chamar o modulo: nas maquinas que
# caem no COM ele nao responde a nada. Estas quatro funcoes sao o unico ponto
# que conhece a diferenca.
function Tarefa-Rodar(){{
 if($viaCom){{$pasta.GetTask($task).Run($null)|Out-Null}}
 else{{Start-ScheduledTask -TaskName $task -ErrorAction Stop}}
}}
function Tarefa-Rodando(){{
 if($viaCom){{return ([int]$pasta.GetTask($task).State -eq 4)}}
 return ([string](Get-ScheduledTask -TaskName $task).State -eq 'Running')
}}
function Tarefa-Resultado(){{
 if($viaCom){{return [int]$pasta.GetTask($task).LastTaskResult}}
 $info=Get-ScheduledTaskInfo -TaskName $task
 if($info){{return [int]$info.LastTaskResult}}
 return $null
}}
function Tarefa-Remover(){{
 if($viaCom){{try{{$pasta.DeleteTask($task,0)}}catch{{}}}}
 else{{Unregister-ScheduledTask -TaskName $task -Confirm:$false}}
}}

$scriptInicio=Get-Date
try{{Tarefa-Rodar}}
catch{{
 Tarefa-Remover
 Send 'start_failed' $_.Exception.Message
}}
$ran=$false
$end=(Get-Date).AddSeconds(20)
while((Get-Date) -lt $end){{
 if(Tarefa-Rodando){{$ran=$true;break}}
 Start-Sleep -Milliseconds 250
}}
$end=(Get-Date).AddSeconds({wait})
while($ran -and (Get-Date) -lt $end){{
 if(-not (Tarefa-Rodando)){{break}}
 Start-Sleep -Milliseconds 250
}}
$o.MsScript=[int]((Get-Date)-$scriptInicio).TotalMilliseconds
$res=Tarefa-Resultado
if($null -ne $res){{$o.LastResult=[int]$res}}
$aindaRodando=Tarefa-Rodando
Tarefa-Remover
if(-not $ran){{Send 'not_started' ''}}
if($aindaRodando){{Send 'timeout' ''}}
Send 'ok' ''"""


def parse_run_script_payload(output: str) -> dict:
    """Extrai o JSON marcado da saida do PsExec. Devolve {} se nao achar."""
    match = re.search(
        r"__VNC_MENU_RUNVBS_BEGIN__\s*([A-Za-z0-9+/=\r\n]+?)\s*__VNC_MENU_RUNVBS_END__",
        str(output or ""),
    )
    if not match:
        return {}
    try:
        payload = re.sub(r"\s+", "", match.group(1))
        data = json.loads(base64.b64decode(payload).decode("utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def format_script_run_report(host: str, data: dict) -> str:
    """Relatorio em texto do que aconteceu na maquina."""
    status = str((data or {}).get("Status") or "")
    lines = [
        SCRIPT_RUN_STATUS.get(status, f"Resultado não reconhecido: {status or '(vazio)'}"),
        "",
        f"Computador: {host}",
    ]

    user = str((data or {}).get("User") or "").strip()
    metodo = SCRIPT_USER_METHOD.get(str((data or {}).get("MetodoUsuario") or ""), "")
    lines.append(f"Usuário logado: {user or '-'}" + (f"  ({metodo})" if user and metodo else ""))

    if str((data or {}).get("MetodoTarefa") or "") == "com":
        # Mesma informacao que "o WMI nao respondeu" na linha do usuario: a
        # execucao deu certo, mas a maquina esta degradada.
        lines.append("Tarefa criada pela API COM — o módulo do agendador não respondeu.")

    script = str((data or {}).get("Script") or "").strip()
    if script:
        lines.append(f"Arquivo: {script}")

    last = (data or {}).get("LastResult")
    if isinstance(last, int):
        # O script da empresa nunca limpa o ON ERROR RESUME NEXT, entao 0 aqui
        # significa "o cscript iniciou e saiu", nao "as impressoras voltaram".
        lines.append(f"Código da tarefa: {last}")

    preparo = _format_phase_ms((data or {}).get("MsPreparo"))
    execucao = _format_phase_ms((data or {}).get("MsScript"))
    total = _format_phase_ms((data or {}).get("Ms"))
    psexec = _format_phase_ms((data or {}).get("MsPsExec"))
    if preparo or execucao or total or psexec:
        lines.append("")
        if preparo:
            lines.append(f"Preparo da tarefa: {preparo}")
        if execucao:
            lines.append(f"Execução do script: {execucao}")
        if total:
            lines.append(f"Total na máquina: {total}")
        if psexec:
            lines.append(f"Conexão PsExec (total da chamada): {psexec}")

    hint = SCRIPT_RUN_HINT.get(status, "")
    if hint:
        lines.extend(["", hint])

    detail = str((data or {}).get("Detail") or "").strip()
    if detail:
        lines.extend(["", f"Mensagem do Windows: {detail}"])

    available = (data or {}).get("Available")
    if status == "no_script" and isinstance(available, list):
        nomes = [str(item) for item in available if str(item).strip()]
        lines.append("")
        if nomes:
            lines.append("Arquivos na pasta de inicialização:")
            lines.extend(f"  {nome}" for nome in nomes)
        else:
            lines.append("A pasta de inicialização está vazia.")

    if status == "ok":
        lines.extend([
            "",
            "O script não informa sucesso pelo código de saída (ele suprime "
            "todos os erros internos). Confirme pelo botão Impressoras.",
        ])

    return "\n".join(lines)


def run_startup_script(host: str, script_name: str, psexec_path: Path) -> dict:
    """Roda um script da pasta de inicializacao como o usuario logado.

    Devolve o dicionario cru do computador remoto. Levanta PsExecQueryError
    quando o PsExec nem chegou a entregar um resultado.
    """
    host = str(host or "").strip().lstrip("\\")
    if not host:
        raise ValueError("Hostname ou IP não informado.")

    script_name = validate_script_name(script_name)
    payload = _build_run_script_payload(script_name)
    encoded_command = _encoded_command(payload)

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

    # Medido AQUI, e nao dentro do payload: o que o payload nao consegue ver e
    # justamente o custo de o PsExec abrir o servico na maquina remota, que e
    # a diferenca entre este numero e o "Total na maquina" dele.
    _psexec_inicio = time.monotonic()
    completed = _run_psexec(command, host, psexec_path, SCRIPT_RUN_TIMEOUT_SECONDS)
    _psexec_ms = int((time.monotonic() - _psexec_inicio) * 1000)

    stdout = _decode_process_output(completed.stdout)
    stderr = _decode_process_output(completed.stderr)
    data = parse_run_script_payload(f"{stdout}\n{stderr}")

    if not data:
        if _truncated_output(f"{stdout}\n{stderr}",
                             "__VNC_MENU_RUNVBS_BEGIN__", "__VNC_MENU_RUNVBS_END__"):
            raise _truncation_error(
                host, psexec_path, completed.returncode, stdout, stderr)
        summary, hint, category = _diagnose_psexec_failure(
            f"{stdout}\n{stderr}", completed.returncode
        )
        details = _build_psexec_details(
            host, psexec_path, completed.returncode, stdout, stderr
        )
        raise PsExecQueryError(
            summary,
            hint,
            details,
            returncode=completed.returncode,
            category=category,
        )

    data["MsPsExec"] = _psexec_ms
    return data


# ------------------------------------------------- instalar drivers (admin)

DRIVER_INSTALL_STATUS = {
    "ok": "Instalação de drivers concluída.",
    "no_script": "O arquivo não foi encontrado na pasta de inicialização.",
    "no_queues": "Nenhum caminho de impressora foi encontrado dentro do script.",
}

# De onde veio a resposta de cada fila. Fica no relatorio porque a diferenca
# entre "o usuario ja tinha" e "uma execucao nossa anterior tinha" e o que
# distingue a checagem que serve da que so acerta na segunda vez.
DRIVER_SKIP_SOURCE = {
    "usuario": "já no perfil de um usuário",
    "ja_existia": "respondido pelo servidor",
    "instalou_com": "pela API COM, o WMI recusou",
}

DRIVER_INSTALL_HINT = {
    "no_script": "Use o botão de abrir a pasta e confira o nome exato do arquivo.",
    "no_queues": "O script pode montar o caminho por variável ou laço, em vez de "
                 "escrever \\\\servidor\\fila entre aspas. Nesse caso a instalação "
                 "de drivers não tem como saber quais filas usar.",
}


def parse_printer_paths(script_text: str) -> list:
    r"""Extrai os \\servidor\fila escritos entre aspas no script.

    O script da empresa escreve cada caminho como literal
    (strPrinterPath = "\\SRV1315\FILA"), entao le-los e o suficiente para
    saber quais drivers precisam ser instalados antes. Nomes repetidos saem
    uma vez so, na ordem em que aparecem: a ordem do script e a ordem em que
    o suporte espera ver as filas.
    """
    encontrados = []
    for bruto in re.findall(r'"(\\\\[^"\r\n]+)"', str(script_text or "")):
        caminho = bruto.strip().rstrip("\\")
        # Precisa ser \\servidor\fila: so o servidor, sem fila, nao instala
        # driver nenhum e viraria uma chamada perdida.
        if not re.match(r"^\\\\[^\\]+\\.+", caminho):
            continue
        if caminho.casefold() not in {item.casefold() for item in encontrados}:
            encontrados.append(caminho)
    return encontrados


def _build_driver_install_payload(script_name: str) -> str:
    """PowerShell que instala os drivers das filas citadas no script.

    Roda como SYSTEM. SYSTEM se autentica no servidor de impressao como a
    conta de maquina (DOMINIO\\PC$), entao nao precisa de senha nenhuma; se o
    servidor recusar a conta de maquina, o erro volta por fila e a decisao de
    usar credencial nominal deixa de ser chute.

    A conexao criada fica no perfil do SYSTEM de proposito: o que interessa e
    o driver, que vai para o driver store da MAQUINA. Remover a conexao depois
    so acrescentaria um jeito de falhar depois do objetivo ja alcancado.

    Antes de instalar qualquer coisa a fila e procurada em DUAS listas locais,
    nenhuma delas com ida ao servidor:

      * as conexoes do proprio SYSTEM (Get-Printer). Essa lista so tem o que
        uma execucao ANTERIOR nossa criou, entao nunca acerta na primeira vez
        em cada maquina;
      * as conexoes do usuario logado, lidas direto de
        HKU\\<SID>\\Printers\\Connections. Essa e a que responde a pergunta que
        interessa - "esse usuario ja tem essa impressora funcionando?" - e
        acerta ja na primeira execucao.

    Uma conexao existente do usuario prova que o driver ja esta no driver
    store da maquina, que e o unico motivo desta fase existir.
    """
    name = _powershell_single_quoted(script_name)
    folder = _powershell_single_quoted(STARTUP_FOLDER)

    return rf"""$ErrorActionPreference='SilentlyContinue';$ProgressPreference='SilentlyContinue'
$m1='__VNC_MENU_DRIVERS_BEGIN__';$m2='__VNC_MENU_DRIVERS_END__'
$folder={folder};$name={name}
$o=[ordered]@{{Status='';Script='';Queues=@();Results=@();Detail='';Ms=0;FilasUsuario=@();FilasSistema=@();LimpasSistema=@()}}
$faseInicio=Get-Date
function Send($s,$d){{
 $o.Status=$s;$o.Detail=[string]$d
 $o.Ms=[int]((Get-Date)-$faseInicio).TotalMilliseconds
 $j=ConvertTo-Json -InputObject $o -Compress -Depth 5
 [Console]::Out.WriteLine($m1+[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($j))+$m2)
 [Console]::Out.Flush()
 exit
}}
$file=Join-Path $folder $name
$o.Script=$file
if(-not (Test-Path -LiteralPath $file -PathType Leaf)){{Send 'no_script' ''}}
$txt=Get-Content -LiteralPath $file -Raw
$achados=@()
foreach($mm in [regex]::Matches([string]$txt,'"(\\\\[^"\r\n]+)"')){{
 $p=([string]$mm.Groups[1].Value).Trim().TrimEnd('\')
 if($p -match '^\\\\[^\\]+\\.+' -and $achados -notcontains $p){{$achados+=$p}}
}}
$o.Queues=$achados
if($achados.Count -eq 0){{Send 'no_queues' ''}}

# --- Conexoes ja presentes na maquina, sem tocar no servidor ---------------

# 1) As conexoes do proprio SYSTEM. NAO servem para decidir nada: elas so
# existem porque uma execucao NOSSA anterior as criou, e a pergunta aqui e se
# o USUARIO ja tem a fila. Sao lidas para serem APAGADAS.
#
# O Add-Printer roda como SYSTEM porque o driver vai para o driver store da
# maquina, que e o objetivo; a conexao no perfil do SYSTEM e so um efeito
# colateral. Deixa-la la fazia a consulta de impressoras - que tambem roda
# como SYSTEM e tambem chama Get-Printer - listar a nossa sobra junto com as
# impressoras do usuario, como se ele tivesse uma fila que nunca teve.
#
# Em try: numa maquina com o WMI corrompido isso pode ser erro TERMINANTE,
# que o SilentlyContinue nao segura.
$filasSistema=@()
try{{
 foreach($imp in @(Get-Printer)){{
  $n=[string]$imp.Name
  if($n.StartsWith('\\')){{$filasSistema+=$n}}
 }}
}}catch{{$filasSistema=@()}}
$o.FilasSistema=$filasSistema

function Limpa-Sistema($caminho){{
 # Remove so a conexao do perfil do SYSTEM. O driver fica no driver store da
 # maquina, que e justamente o que esta fase existe para garantir.
 try{{Remove-Printer -Name $caminho -ErrorAction Stop;return $true}}catch{{}}
 try{{
  (New-Object -ComObject WScript.Network).RemovePrinterConnection($caminho,$true,$false)
  return $true
 }}catch{{}}
 return $false
}}

# Sobras de versoes anteriores, que deixavam a conexao para tras. Sem isso a
# maquina fica com a nossa sujeira ate alguem apagar na mao.
$limpas=@()
foreach($sobra in $filasSistema){{
 if(Limpa-Sistema $sobra){{$limpas+=$sobra}}
}}
$o.LimpasSistema=$limpas

# 2) As dos perfis de usuario carregados. Varre TODOS os SIDs de conta real
# em HKEY_USERS em vez de perguntar ao WMI quem esta logado: e a mesma
# varredura que a consulta de impressoras ja usa, nao depende de CIM e por
# isso continua respondendo em maquina com o WMI quebrado - que e
# exatamente a maquina onde Get-Printer e Add-Printer tambem falham e a
# checagem local e mais necessaria.
# As conexoes ficam como subchaves com as contrabarras trocadas por virgula:
# \\SRV\FILA vira ,,SRV,FILA.
$filasUsuario=@()
try{{
 foreach($hive in @(Get-ChildItem 'Registry::HKEY_USERS' | Where-Object{{
   $_.PSChildName -match '^S-1-5-21-(?:\d+-){{3}}\d+$'}})){{
  $chave="Registry::HKEY_USERS\$($hive.PSChildName)\Printers\Connections"
  foreach($sub in @(Get-ChildItem -Path $chave)){{
   $filasUsuario+=([string]$sub.PSChildName).Replace(',','\')
  }}
 }}
}}catch{{}}
$o.FilasUsuario=$filasUsuario

# So os perfis de usuario entram na decisao. O perfil do SYSTEM diria apenas
# "ja instalamos isso antes", que nao responde se o usuario tem a fila - e era
# por isso que a checagem so acertava a partir da segunda execucao.
$conhecidas=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
foreach($n in $filasUsuario){{[void]$conhecidas.Add($n.TrimEnd('\'))}}

foreach($path in $achados){{
 $r=[ordered]@{{Path=$path;Ok=$false;Error='';Pulou=$false;JaExistia=$false;Fonte='';Ms=0}}
 $t0=Get-Date
 # Consulta LOCAL antes da remota: se a fila ja esta presente, o driver ja
 # esta no driver store e o Add-Printer so faria uma ida ao servidor para
 # nao mudar nada. Era isso que fazia TODA execucao pagar a fase de drivers,
 # inclusive nas maquinas onde nao havia nada a instalar.
 if($conhecidas.Contains($path)){{
  $r.Ok=$true;$r.Pulou=$true
  $r.Fonte='usuario'
  $r.Ms=[int]((Get-Date)-$t0).TotalMilliseconds
  $o.Results+=,$r
  continue
 }}
 try{{
  Add-Printer -ConnectionName $path -ErrorAction Stop
  $r.Ok=$true;$r.Fonte='instalou'
  [void](Limpa-Sistema $path)
 }}catch{{
  $msg=[string]$_.Exception.Message
  # Ja instalada e sucesso: o driver que interessa ja esta no driver store.
  # Marcado a parte de proposito: cair aqui significa que as duas listas
  # locais erraram, e isso precisa aparecer no relatorio em vez de se
  # disfarcar de instalacao bem sucedida.
  if($msg -match '(?i)already exists|ja existe|já existe'){{
   $r.Ok=$true;$r.JaExistia=$true;$r.Fonte='ja_existia'
   [void](Limpa-Sistema $path)
  }}
  # Add-Printer e um cmdlet CDXML: ele fala com o provedor WMI de impressao.
  # Em maquina com o repositorio WMI corrompido ele responde 'namespace
  # invalido' e NENHUMA fila instala - inclusive as que o proprio script da
  # empresa instala sem problema, porque o script usa a API COM antiga, que
  # nao passa por WMI. Entao o COM e a segunda tentativa, nao um plano B
  # teorico: e comprovadamente o caminho que funciona nessas maquinas.
  elseif($msg -match '(?i)namespace|0x8004100E|WBEM'){{
   try{{
    (New-Object -ComObject WScript.Network).AddWindowsPrinterConnection($path)
    $r.Ok=$true;$r.Fonte='instalou_com'
    [void](Limpa-Sistema $path)
   }}catch{{
    $r.Error=$msg+' | COM: '+[string]$_.Exception.Message
   }}
  }}
  else{{$r.Error=$msg}}
 }}
 $r.Ms=[int]((Get-Date)-$t0).TotalMilliseconds
 $o.Results+=,$r
}}
Send 'ok' ''"""


def parse_driver_install_payload(output: str) -> dict:
    """Extrai o JSON marcado da instalacao de drivers. {} se nao achar."""
    match = re.search(
        r"__VNC_MENU_DRIVERS_BEGIN__\s*([A-Za-z0-9+/=\r\n]+?)\s*__VNC_MENU_DRIVERS_END__",
        str(output or ""),
    )
    if not match:
        return {}
    try:
        payload = re.sub(r"\s+", "", match.group(1))
        data = json.loads(base64.b64decode(payload).decode("utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def driver_install_failures(data: dict) -> list:
    """Filas que nao instalaram, como (caminho, erro)."""
    resultados = (data or {}).get("Results")
    if not isinstance(resultados, list):
        return []
    falhas = []
    for item in resultados:
        if not isinstance(item, dict):
            continue
        if not item.get("Ok"):
            falhas.append((str(item.get("Path") or "?"), str(item.get("Error") or "")))
    return falhas


def _format_phase_ms(value) -> str:
    """Tempo medido, ex.: '3,4s' ou '9 ms'. Vazio quando nao ha medicao.

    Vazio e diferente de zero de proposito: o payload so passou a medir tempo
    na 2.5.2, entao uma execucao de versao anterior nao deve imprimir um
    '0,0s' que parece medicao e nao e. Abaixo de um segundo sai em ms para que
    uma fila pulada (poucos milissegundos) nao vire '0,0s'.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    if value <= 0:
        return ""
    if value < 1000:
        return f"{int(value)} ms"
    return f"{value / 1000.0:.1f}s".replace(".", ",")


def driver_install_wmi_broken(data: dict) -> bool:
    """True quando TODA falha foi de namespace do WMI.

    Vale como diagnostico so quando e unanime: uma fila com erro de namespace
    no meio de outras com erro de acesso seria coincidencia, mas todas elas
    significa que o provedor de impressao nao respondeu a nenhuma chamada.
    """
    falhas = driver_install_failures(data)
    if not falhas:
        return False
    return all(
        re.search(r"(?i)namespace|0x8004100E|WBEM", erro or "")
        for _caminho, erro in falhas
    )


def format_driver_install_report(host: str, data: dict) -> str:
    """Relatorio da instalacao de drivers, fila por fila."""
    status = str((data or {}).get("Status") or "")
    linhas = [
        DRIVER_INSTALL_STATUS.get(
            status, f"Resultado não reconhecido: {status or '(vazio)'}"
        ),
        "",
        f"Computador: {host}",
    ]

    script = str((data or {}).get("Script") or "").strip()
    if script:
        linhas.append(f"Arquivo lido: {script}")

    resultados = (data or {}).get("Results")
    if isinstance(resultados, list) and resultados:
        linhas.append("")
        for item in resultados:
            if not isinstance(item, dict):
                continue
            caminho = str(item.get("Path") or "?")
            if item.get("Pulou"):
                rotulo = "JÁ TINHA"
            elif item.get("JaExistia"):
                # As duas listas locais erraram e quem respondeu foi o
                # servidor. Nao pode aparecer como instalacao: e um round-trip
                # que a checagem local deveria ter evitado.
                rotulo = "JÁ EXISTIA"
            elif item.get("Ok"):
                rotulo = "INSTALOU"
            else:
                rotulo = "FALHA"
            tempo = _format_phase_ms(item.get("Ms"))
            partes = [p for p in (DRIVER_SKIP_SOURCE.get(str(item.get("Fonte") or "")), tempo) if p]
            sufixo = f"  ({', '.join(partes)})" if partes else ""
            linhas.append(f"  {rotulo:<11}{caminho}{sufixo}")
            if not item.get("Ok"):
                erro = str(item.get("Error") or "").strip()
                if erro:
                    linhas.append(f"             {erro}")

    fase = _format_phase_ms((data or {}).get("Ms"))
    if fase:
        linhas.extend(["", f"Tempo da fase de drivers: {fase}"])

    psexec = _format_phase_ms((data or {}).get("MsPsExec"))
    if psexec:
        linhas.append(f"Conexão PsExec (total da chamada): {psexec}")

    hint = DRIVER_INSTALL_HINT.get(status, "")
    if hint:
        linhas.extend(["", hint])

    falhas = driver_install_failures(data)
    if status == "ok" and falhas:
        if driver_install_wmi_broken(data):
            # Conclusao diferente e acao diferente: nao adianta mexer no
            # servidor de impressao nem no driver da fila. O defeito e na
            # propria maquina, e enquanto ele existir Get-Printer, Add-Printer
            # e a consulta de quem esta logado continuam falhando junto.
            linhas.extend([
                "",
                "Todas as filas falharam por namespace do WMI — não é o "
                "servidor nem o driver, é o repositório WMI deste computador "
                "que está corrompido. A tentativa pela API COM também não "
                "passou. Nessa máquina, rode \"winmgmt /verifyrepository\" e, "
                "se acusar problema, \"winmgmt /salvagerepository\".",
            ])
        else:
            linhas.extend([
                "",
                "As filas acima falharam. Se o erro for de acesso, o servidor "
                "não está liberando o driver para a conta de máquina deste "
                "computador; se for de driver, a fila pode estar publicando um "
                "driver que esta máquina não aceita.",
            ])

    return "\n".join(linhas)


def install_printer_drivers(host: str, script_name: str, psexec_path: Path) -> dict:
    """Instala, com privilegio, os drivers das filas citadas no script.

    Separada de run_startup_script de proposito: instalar driver e operacao de
    MAQUINA (vai para o driver store) e mapear impressora e operacao de
    USUARIO (vai para o HKCU). Sao dois contextos diferentes, entao sao duas
    chamadas diferentes.

    Roda como SYSTEM, que se apresenta ao servidor de impressao como a conta
    de maquina (DOMINIO\\PC$). Foi testado em producao: o servidor libera o
    driver para a conta de maquina, o mesmo caminho que a consulta de
    impressoras ja usava para ler as filas do SRV. Rodar com -u/-p foi
    tentado e nao serve: o PsExec faz logon interativo no computador remoto,
    e a conta administrativa nao tem esse direito nas estacoes (erro 1385).
    """
    host = str(host or "").strip().lstrip("\\")
    if not host:
        raise ValueError("Hostname ou IP não informado.")

    script_name = validate_script_name(script_name)
    payload = _build_driver_install_payload(script_name)
    encoded_command = _encoded_command(payload)

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

    _psexec_inicio = time.monotonic()
    completed = _run_psexec(command, host, psexec_path, SCRIPT_RUN_TIMEOUT_SECONDS)
    _psexec_ms = int((time.monotonic() - _psexec_inicio) * 1000)

    stdout = _decode_process_output(completed.stdout)
    stderr = _decode_process_output(completed.stderr)
    data = parse_driver_install_payload(f"{stdout}\n{stderr}")

    if not data:
        if _truncated_output(f"{stdout}\n{stderr}",
                             "__VNC_MENU_DRIVERS_BEGIN__", "__VNC_MENU_DRIVERS_END__"):
            raise _truncation_error(
                host, psexec_path, completed.returncode, stdout, stderr)
        summary, hint, category = _diagnose_psexec_failure(
            f"{stdout}\n{stderr}", completed.returncode
        )
        details = _build_psexec_details(
            host, psexec_path, completed.returncode, stdout, stderr
        )
        raise PsExecQueryError(
            summary, hint, details,
            returncode=completed.returncode, category=category,
        )

    data["MsPsExec"] = _psexec_ms
    return data
