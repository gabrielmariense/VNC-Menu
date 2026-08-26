"""Verificacao e download de atualizacoes pelo GitHub Releases.

O SHA-256 e obrigatorio: sem digest nem arquivo .sha256 a atualizacao
e bloqueada em vez de prosseguir.

Depende apenas de config.
"""

from pathlib import Path
import hashlib
import json
import re
import shutil
import ssl
import sys
import urllib.error
import urllib.request

from .config import APP_NAME, APP_VERSION, GITHUB_LATEST_RELEASE_API, SCRIPT_DIR, UPDATER_EXE_NAME, UPDATER_SCRIPT_NAME

def create_https_context() -> ssl.SSLContext:
    """Create a verified HTTPS context compatible with corporate Windows PKI.

    Python 3.13 enables OpenSSL X509 strict mode in create_default_context().
    Some valid enterprise/proxy CA chains omit Authority Key Identifier and are
    rejected only by that extra strict flag. Disabling STRICT keeps normal CA
    verification and hostname checking enabled.
    """
    context = ssl.create_default_context()
    strict_flag = getattr(ssl, "VERIFY_X509_STRICT", 0)
    if strict_flag:
        context.verify_flags &= ~strict_flag
    return context


HTTPS_CONTEXT = create_https_context()


def parse_version(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", str(value or "").strip().lower().removeprefix("v"))
    return tuple(int(part) for part in parts) if parts else (0,)


def normalize_release_version(value: str) -> str:
    value = str(value or "").strip()
    return value[1:] if value.lower().startswith("v") else value


def github_request_json(url: str, timeout: int = 15) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{APP_NAME}/{APP_VERSION}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout, context=HTTPS_CONTEXT) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("Resposta inválida recebida do GitHub.")
    return data


def fetch_latest_release() -> dict:
    return github_request_json(GITHUB_LATEST_RELEASE_API)


def find_release_zip_asset(release: dict) -> dict:
    assets = [item for item in release.get("assets", []) if isinstance(item, dict)]
    zip_assets = [
        item for item in assets
        if str(item.get("name") or "").lower().endswith(".zip")
    ]
    if not zip_assets:
        raise RuntimeError(
            "A release mais recente não possui um arquivo ZIP de atualização."
        )

    latest = normalize_release_version(release.get("tag_name", ""))
    preferred_names = {
        f"vnc-menu-v{latest}.zip".lower(),
        f"vnc-menu-{latest}.zip".lower(),
        f"vnc-menu-v{latest}-win64.zip".lower(),
    }

    for asset in zip_assets:
        if str(asset.get("name") or "").lower() in preferred_names:
            return asset

    for asset in zip_assets:
        if "vnc-menu" in str(asset.get("name") or "").lower():
            return asset

    return zip_assets[0]


def download_url_bytes(url: str, timeout: int = 30) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"},
    )
    with urllib.request.urlopen(request, timeout=timeout, context=HTTPS_CONTEXT) as response:
        return response.read()


def get_release_asset_checksum(release: dict, asset: dict) -> str:
    digest = str(asset.get("digest") or "").strip().lower()
    if digest.startswith("sha256:"):
        candidate = digest.split(":", 1)[1].strip()
        if re.fullmatch(r"[0-9a-f]{64}", candidate):
            return candidate

    assets = [item for item in release.get("assets", []) if isinstance(item, dict)]
    asset_name = str(asset.get("name") or "")
    checksum_names = {
        f"{asset_name}.sha256".lower(),
        f"{Path(asset_name).stem}.sha256".lower(),
        "sha256sums.txt",
        "checksums.txt",
    }

    checksum_asset = None
    for item in assets:
        if str(item.get("name") or "").lower() in checksum_names:
            checksum_asset = item
            break

    if checksum_asset is None:
        raise RuntimeError(
            "A release não possui digest SHA-256 nem arquivo .sha256. "
            "A atualização foi bloqueada por segurança."
        )

    checksum_url = str(checksum_asset.get("browser_download_url") or "").strip()
    if not checksum_url:
        raise RuntimeError("URL do arquivo de checksum não encontrada.")

    checksum_text = download_url_bytes(checksum_url).decode("utf-8", errors="replace")

    for line in checksum_text.splitlines():
        if asset_name.lower() not in line.lower():
            continue
        match = re.search(r"\b[0-9a-fA-F]{64}\b", line)
        if match:
            return match.group(0).lower()

    match = re.search(r"\b[0-9a-fA-F]{64}\b", checksum_text)
    if not match:
        raise RuntimeError("Checksum SHA-256 inválido na release.")
    return match.group(0).lower()


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_pythonw_executable() -> str:
    executable = Path(sys.executable)
    if executable.name.lower() == "python.exe":
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.exists():
            return str(pythonw)
    return str(executable)


def get_updater_launch_command(work_dir: Path) -> list[str]:
    """Run a temporary updater copy so the installed updater can be replaced."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    if getattr(sys, "frozen", False):
        updater = SCRIPT_DIR / UPDATER_EXE_NAME
        if not updater.exists():
            raise FileNotFoundError(
                f"Atualizador não encontrado:\n{updater}"
            )
        temporary_updater = work_dir / UPDATER_EXE_NAME
        shutil.copy2(updater, temporary_updater)
        return [str(temporary_updater)]

    updater = SCRIPT_DIR / UPDATER_SCRIPT_NAME
    if not updater.exists():
        raise FileNotFoundError(
            f"Atualizador não encontrado:\n{updater}"
        )
    temporary_updater = work_dir / UPDATER_SCRIPT_NAME
    shutil.copy2(updater, temporary_updater)
    return [get_pythonw_executable(), str(temporary_updater)]


def current_main_entry_name() -> str:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).name
    return Path(__file__).name


def format_release_notes_for_display(markdown_text: str) -> str:
    """Convert common GitHub release Markdown into clean readable text."""
    source_lines = str(markdown_text or "").replace("\r\n", "\n").splitlines()
    output = []
    first_content_seen = False

    for raw_line in source_lines:
        line = raw_line.strip()

        if not line:
            if output and output[-1] != "":
                output.append("")
            continue

        if line.startswith("```"):
            continue

        heading_match = re.match(r"^#{1,6}\s+(.+)$", line)
        if heading_match:
            heading = heading_match.group(1).strip()

            if not first_content_seen and re.match(
                r"(?i)^vnc-menu\s+v?\d",
                heading,
            ):
                first_content_seen = True
                continue

            heading = re.sub(r"[*_`]", "", heading).strip()
            if output and output[-1] != "":
                output.append("")
            output.append(heading.upper())
            first_content_seen = True
            continue

        bullet_match = re.match(r"^[-*+]\s+(.+)$", line)
        if bullet_match:
            content = bullet_match.group(1).strip()
            content = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", content)
            content = re.sub(r"[*_`]", "", content)
            output.append(f"• {content}")
            first_content_seen = True
            continue

        line = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", line)
        line = re.sub(r"[*_`]", "", line)
        output.append(line)
        first_content_seen = True

    while output and output[-1] == "":
        output.pop()

    return "\n".join(output) or "Nenhuma nota de versão informada."
