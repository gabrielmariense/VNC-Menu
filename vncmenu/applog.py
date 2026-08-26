"""Log de auditoria e log de erros, ambos com rotacao.

Depende apenas de config. Nunca levanta: falhar ao escrever log jamais
pode derrubar uma operacao do usuario.
"""

from pathlib import Path
import os
import sys
import time
import traceback

from .config import AUDIT_LOG, AUDIT_LOG_MAX_BYTES, ERROR_LOG, ERROR_LOG_MAX_BYTES, _LOG_USERNAME

def rotate_log_if_needed(path: Path, max_bytes: int) -> None:
    """Keep one previous generation so an appended log cannot grow without limit."""
    try:
        if path.exists() and path.stat().st_size >= max_bytes:
            os.replace(path, path.with_name(path.name + ".1"))
    except OSError:
        pass


def log_exception(exc: Exception | None = None):
    """Append the current traceback to the per-user error log.

    This appends instead of overwriting: log_psexec_failure() writes to the same
    file, and the previous write_text() implementation erased that PsExec
    history on the next unrelated exception.
    """
    try:
        ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        rotate_log_if_needed(ERROR_LOG, ERROR_LOG_MAX_BYTES)

        if sys.exc_info()[0] is not None:
            details = traceback.format_exc()
        elif exc is not None:
            # Called outside an except block: format_exc() has nothing to report.
            details = f"{type(exc).__name__}: {exc}"
        else:
            details = "Nenhuma exceção ativa."

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with ERROR_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"\n[{timestamp}] EXCEPTION\n")
            handle.write(details.rstrip("\n"))
            handle.write("\n" + ("-" * 72) + "\n")
    except Exception:
        pass


def audit_log(action: str, details: str = ""):
    """Grava uma linha de auditoria por usuário."""
    username = _LOG_USERNAME

    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        rotate_log_if_needed(AUDIT_LOG, AUDIT_LOG_MAX_BYTES)
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
