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


# Arquivos que o repositorio PUBLICA dentro de data\. Nao sao dados do
# usuario: o template.vnc.example e a semente que o bootstrap usa para criar o
# template.vnc na primeira execucao, e o LEIA-ME e documentacao. Com data\
# preservada inteira, uma correcao em qualquer um dos dois chegava apenas em
# instalacao nova - a antiga ficava com a versao do dia em que foi instalada,
# para sempre e sem aviso.
#
# A lista e de EXCECOES a uma regra que preserva tudo, e nao o contrario: um
# arquivo novo que apareca em data\ continua protegido por padrao. Inverter
# isso (preservar so o que estiver listado) faria um esquecimento apagar dado
# do usuario, que e o erro caro.
SHIPPED_DATA_FILES = (
    Path("data/template.vnc.example"),
    Path("data/LEIA-ME-template-vnc.txt"),
)


def is_preserved(relative: Path) -> bool:
    normalized = Path(*relative.parts)
    if normalized in SHIPPED_DATA_FILES:
        return False
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
    planejados = []
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

            planejados.append((info, relative))

        # Extracao explicita, e nao extractall(). O ZIP gerado pelo
        # Compress-Archive do Windows PowerShell 5.1 grava os nomes com
        # CONTRABARRA, o que a especificacao do formato proibe (APPNOTE
        # 4.4.17.1 exige barra normal). O extractall() so acerta esses nomes
        # porque no Windows os.sep e a contrabarra e ele parte por ali: fora
        # do Windows o caminho inteiro vira UM nome de arquivo e o pacote sai
        # achatado. Aqui o separador ja foi normalizado na validacao acima,
        # entao o resultado e o mesmo em qualquer sistema.
        for info, relative in planejados:
            destino = destination / relative
            if info.is_dir():
                destino.mkdir(parents=True, exist_ok=True)
                continue
            destino.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as origem, open(destino, "wb") as saida:
                shutil.copyfileobj(origem, saida)


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
    package_root = main_file.parent

    # Uma raiz de pacote valida tem vncmenu\ ao lado (codigo-fonte) ou
    # _internal\ (build empacotado). Sem isso o pacote e recusado: melhor
    # recusar do que espalhar arquivo pela instalacao.
    #
    # A checagem NAO olha mais a extensao do arquivo encontrado. Quando so
    # valia para .pyw, um --main-entry errado escapava por baixo dela: o
    # aplicativo mandava "updates.py", isso casava com vncmenu\updates.py, a
    # raiz virava a propria pasta vncmenu\ e o conteudo dela era copiado solto
    # para a pasta de instalacao, deixando o ponto de entrada na versao
    # antiga. Quem define uma raiz valida e o que esta AO LADO dela, nunca o
    # nome de quem pediu.
    valido = (
        (package_root / "vncmenu" / "__init__.py").is_file()
        or (package_root / "_internal").is_dir()
    )
    if not valido:
        raise RuntimeError(
            "O pacote de atualizacao esta malformado: nao ha a pasta "
            "vncmenu\\ nem _internal\\ ao lado de " + main_file.name +
            ". Nenhum arquivo foi alterado."
        )

    return package_root, main_file


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
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)
        except Exception:
            # Disco cheio ou arquivo travado pelo antivirus no meio da copia
            # deixava um <nome>.update-new na pasta de instalacao, que o
            # rollback nao conhece - ele so desfaz o que ja foi registrado em
            # overwritten/created.
            try:
                temporary.unlink(missing_ok=True)
            except Exception:
                pass
            raise

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
