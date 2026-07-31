import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from tkinter import messagebox

PRESERVED_PREFIXES = (
    Path("data"),
    Path("logs"),
    Path("_internal/hosts.json"),
    Path("_internal/template.vnc"),
    Path("_internal/realvnc"),
)


def is_preserved(relative: Path) -> bool:
    normalized = Path(*relative.parts)
    for prefix in PRESERVED_PREFIXES:
        if normalized == prefix or prefix in normalized.parents:
            return True
    return False


def update_result_path() -> Path:
    path = Path.home() / "Documents" / "VNC-Menu" / "update-result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_result(status: str, version: str, message: str = ""):
    payload = {
        "status": status,
        "version": version,
        "message": message,
        "timestamp": time.time(),
    }
    update_result_path().write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def wait_for_process(pid: int, timeout_seconds: int = 120):
    if os.name != "nt":
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return
            time.sleep(0.25)
        raise TimeoutError("O VNC-Menu não encerrou dentro do tempo esperado.")

    synchronize = 0x00100000
    wait_object_0 = 0x00000000
    wait_timeout = 0x00000102

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return
    try:
        result = kernel32.WaitForSingleObject(handle, timeout_seconds * 1000)
        if result == wait_object_0:
            return
        if result == wait_timeout:
            raise TimeoutError("O VNC-Menu não encerrou dentro do tempo esperado.")
        raise RuntimeError(f"Falha ao aguardar o processo principal: código {result}")
    finally:
        kernel32.CloseHandle(handle)


def safe_extract(archive_path: Path, destination: Path):
    destination = destination.resolve()
    with zipfile.ZipFile(archive_path, "r") as archive:
        for info in archive.infolist():
            relative = Path(info.filename.replace("\\", "/"))
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError(f"Caminho inseguro no ZIP: {info.filename}")

            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise RuntimeError(f"Link simbólico não permitido no ZIP: {info.filename}")

            target = (destination / relative).resolve()
            if destination not in target.parents and target != destination:
                raise RuntimeError(f"Caminho fora da pasta de extração: {info.filename}")

        archive.extractall(destination)


def find_package_root(staging: Path, requested_main: str) -> tuple[Path, Path]:
    candidates = []

    for path in staging.rglob(requested_main):
        if path.is_file():
            candidates.append(path)

    if not candidates:
        fallback_names = ("VNC-Menu.pyw", "VNC-Menu.exe")
        for name in fallback_names:
            candidates.extend(path for path in staging.rglob(name) if path.is_file())

    if not candidates:
        candidates.extend(
            path for path in staging.rglob("VNC-Menu*.pyw")
            if path.is_file() and "Updater" not in path.name
        )

    if not candidates:
        raise RuntimeError(
            "O pacote não contém o arquivo principal do VNC-Menu."
        )

    main_file = sorted(candidates, key=lambda path: len(path.parts))[0]
    return main_file.parent, main_file


def copy_update_files(package_root: Path, install_dir: Path, backup_dir: Path):
    overwritten = []
    created = []

    for source in package_root.rglob("*"):
        if not source.is_file():
            continue

        relative = source.relative_to(package_root)
        if is_preserved(relative):
            continue

        destination = install_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)

        if destination.exists():
            backup = backup_dir / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, backup)
            overwritten.append(relative)
        else:
            created.append(relative)

        temporary = destination.with_name(destination.name + ".update-new")
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)

    return overwritten, created


def rollback(install_dir: Path, backup_dir: Path, overwritten, created):
    for relative in reversed(created):
        target = install_dir / relative
        try:
            target.unlink(missing_ok=True)
        except Exception:
            pass

    for relative in overwritten:
        backup = backup_dir / relative
        target = install_dir / relative
        if backup.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)


def get_pythonw_executable() -> str:
    executable = Path(sys.executable)
    if executable.name.lower() == "python.exe":
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.exists():
            return str(pythonw)
    return str(executable)


def relaunch(main_path: Path):
    creationflags = 0
    creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
    creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)

    if main_path.suffix.lower() == ".exe":
        command = [str(main_path)]
    else:
        command = [get_pythonw_executable(), str(main_path)]

    subprocess.Popen(
        command,
        cwd=str(main_path.parent),
        close_fds=True,
        creationflags=creationflags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--install-dir", required=True)
    parser.add_argument("--main-entry", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()

    archive_path = Path(args.archive).resolve()
    install_dir = Path(args.install_dir).resolve()
    work_dir = Path(tempfile.mkdtemp(prefix="VNC-Menu-Updater-"))
    staging_dir = work_dir / "staging"
    backup_dir = work_dir / "backup"
    staging_dir.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)

    overwritten = []
    created = []
    relaunch_path = install_dir / args.main_entry

    try:
        wait_for_process(args.pid)
        safe_extract(archive_path, staging_dir)
        package_root, package_main = find_package_root(staging_dir, args.main_entry)

        overwritten, created = copy_update_files(
            package_root,
            install_dir,
            backup_dir,
        )

        relative_main = package_main.relative_to(package_root)
        relaunch_path = install_dir / relative_main
        if not relaunch_path.exists():
            raise RuntimeError(f"Arquivo atualizado não encontrado: {relaunch_path}")

        write_result("success", args.version)
        relaunch(relaunch_path)

    except Exception as exc:
        try:
            rollback(install_dir, backup_dir, overwritten, created)
        except Exception as rollback_error:
            exc = RuntimeError(f"{exc}\n\nFalha adicional no rollback: {rollback_error}")

        write_result("error", args.version, str(exc))

        try:
            if relaunch_path.exists():
                relaunch(relaunch_path)
            elif (install_dir / args.main_entry).exists():
                relaunch(install_dir / args.main_entry)
        except Exception:
            pass

        try:
            messagebox.showerror(
                "VNC-Menu Updater",
                f"Falha ao instalar a atualização:\n\n{exc}",
            )
        except Exception:
            pass

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
