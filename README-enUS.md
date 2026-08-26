# VNC-Menu

A Windows desktop interface for organizing VNC connections and common remote-support tasks from a structured host list.

The project was created to speed up access to multiple machines, reduce repetitive work, and centralize operations such as VNC connections, remote restarts, session checks, remote printer listings, and quick access to administrative shares.

<p align="center">
  <img src="assets/VNC-Menu PROMOTION.png" alt="Interface preview" width="850">
</p>

> The application interface is in Portuguese. Menu labels quoted below are the ones you will see on screen.

## Features

- Host organization by **Unit > Sector > Host**.
- Support for **UltraVNC** and **RealVNC**, with a per-host VNC port.
- Per-user UltraVNC credentials protected with **Windows DPAPI**.
- Automatic UltraVNC authentication, toggleable between **Login automático** and **Login manual**.
- Shared or personal host lists.
- **Connect** and **Restart** action modes.
- Remote session checks with `qwinsta`, run in parallel in the background.
- Remote printer listing through **PsExec** + PowerShell.
- Per-host context menu with **Copy IP**, **Open c$**, **Open Startup folder**, and **Printers**.
- Configuration for hosts, viewers, PsExec, columns, theme, and window placement.
- Update checks and installation from GitHub releases.
- Per-user audit and error logs, with automatic rotation.

## Requirements

- Windows.
- Python 3.12 or newer.
- UltraVNC Viewer for UltraVNC connections.
- RealVNC Viewer for RealVNC connections.
- PsExec (Sysinternals) for the remote printer query.
- Dependencies listed in `requirements.txt`.

Runtime dependencies:

```txt
customtkinter
pywinauto
pywin32
comtypes
```

`requirements.txt` covers runtime only. Packaging tools are not listed there and are not needed to run the application from source.

## Installation

Clone the repository and run:

```bat
INSTALAR.bat
```

The installer checks the project folder, looks for Python, attempts to install it through `winget` if missing, reloads `PATH` from the registry (so the install finishes without having to run the file twice), prepares `pip`, installs the dependencies, and validates the main imports.

Manual installation:

```bat
py -3 -m pip install -r requirements.txt
```

Run as a script:

```bat
py -3 VNC-Menu.pyw
```

## Project structure

```text
VNC-Menu.pyw          Entry point. Anchors data\ and logs\.
VNC-Menu-Updater.pyw  Updater, executed outside the application.
vncmenu\              Application package.
├─ config.py          Constants, paths, install-root detection.
├─ dpapi.py           Credential protection through Windows DPAPI.
├─ applog.py          Audit log and error log.
├─ storage.py         JSON read/write, hosts, credentials, paths.
├─ theme.py           Palette and fonts.
├─ helpers.py         Window, file, and viewer utilities.
├─ updates.py         Release lookup and download.
├─ remote.py          VNC, remote restart, qwinsta, PsExec, printers.
└─ ui\
   ├─ dialogs.py      Shared modal dialogs.
   ├─ windows.py      Configuration, progress, and update windows.
   └─ app.py          Main window.
data\                 Shared installation data.
logs\                 Per-Windows-user logs.
tests\                Test suite (not needed to use the app).
```

`VNC-Menu.pyw` must stay at the install root and keep that name: `data\` and `logs\` are resolved from it, and the updater relaunches the application by that name.

## Usage

### Host organization

Hosts are organized as:

```text
Unit
└─ Sector
   └─ Host
```

Each host contains:

- `name`: display name used by the interface;
- `host`: hostname or IP address;
- `viewer`: `ultravnc` or `realvnc`;
- `port`: optional, the host's VNC port.

### Main actions

On the main screen:

- **Conectar** (Connect): action mode. Clicking a host opens the configured viewer.
- **Reiniciar** (Restart): action mode. Clicking a host asks for confirmation and sends the restart.
- **Usuários** (Users): queries remote sessions for the sector's hosts with `qwinsta`.
- **Impressoras** (Printers): lists the printers installed on the host.

**Conectar** and **Reiniciar** also accept a double-click on the button itself to act on a host typed in on the spot.

The user and printer queries run in the background, with a progress window, to keep the interface responsive. The `qwinsta` query runs in parallel.

### Automatic and manual login

The button next to **Host manual** toggles between:

- **Login automático**: for saved hosts, the application enters the stored UltraVNC credential into the authentication prompt;
- **Login manual**: the UltraVNC authentication window is left to the user.

Manual connections never use automatic credential entry.

### Manual host

The **Host manual** button follows the currently selected mode:

- in **Conectar** mode, it asks for hostname/IP and viewer;
- in **Reiniciar** mode, it asks for hostname/IP and confirmation.

In **Conectar** mode, the field accepts an explicit port in `HOST::5901` form.

### Context menu

Right-click a host to access:

- **Host/IP**: shows the configured `host` value (informational only);
- **Copiar IP** (Copy IP): copies that value;
- **Abrir c$** (Open c$): attempts to open `\\HOST\c$`;
- **Abrir Menu Iniciar** (Open Startup folder): opens the all-users startup folder on the remote machine:

```text
\\HOST\c$\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup
```

- **Impressoras** (Printers): lists the printers installed on the host.

Access to `C$` depends on user permissions, SMB availability, firewall rules, and network policies.

### Editing hosts

The screen:

```text
Configurações > Hosts e Setores
```

allows users to add, edit, remove, reorder, and sort hosts, as well as manage units and sectors.

In the host list:

- single-click selects a host;
- double-click opens that host directly for editing.

## hosts.json format

Example:

```json
{
  "units": [
    {
      "name": "Main Office",
      "sectors": [
        {
          "name": "Support",
          "hosts": [
            {
              "name": "Workstation 01",
              "host": "192.168.1.10",
              "viewer": "ultravnc"
            },
            {
              "name": "Workstation 02",
              "host": "192.168.1.11",
              "viewer": "ultravnc",
              "port": 5901
            },
            {
              "name": "Server 01",
              "host": "192.168.1.20",
              "viewer": "realvnc"
            }
          ]
        }
      ]
    }
  ]
}
```

Supported `viewer` values:

```txt
ultravnc
realvnc
```

If `viewer` is missing or invalid, the application defaults to `ultravnc`.

`port` is optional and accepts values from 1 to 65535. When missing, invalid, or equal to `5900`, the field is omitted on save and the application uses the default port. The `host` field also accepts an embedded port (`HOST::5901`); it is extracted into `port` on the next write.

## Host list modes

Selectable under `Configurações > Selecionar Lista`.

### Default (**Padrão**)

Uses the shared installation `data\hosts.json`.

Recommended when multiple users should use the same host list.

### Custom (**Personalizada**)

Creates a personal copy at:

```text
Documents\VNC-Menu\hosts.json
```

Recommended when a user needs to edit their own list without affecting others.

### Empty (**Vazia**)

Creates a personal list with no hosts, for a new setup.

## UltraVNC

Default path:

```text
C:\Program Files\uvnc bvba\UltraVNC\vncviewer.exe
```

The path can be changed under:

```text
Configurações > Viewers VNC
```

The application uses a shared `template.vnc`. During a connection:

1. the template is copied to a temporary file;
2. UltraVNC is started with `-config`;
3. the target is passed separately as:

```text
HOST::5900
```

Equivalent flow:

```text
vncviewer.exe -config <temporary-profile.vnc> HOST::5900
```

If the host has a configured `port`, it replaces `5900`.

### Where template.vnc lives

The expected file is `data\template.vnc`. It is **not** version controlled: a
profile exported from UltraVNC Viewer can carry the saved connection password
(`passwd` / `passwd2`).

The repository ships `data\template.vnc.example`, which holds no password. On
first run, if `template.vnc` is missing, VNC-Menu copies the example into
place. An existing `template.vnc` is never overwritten.

**The template requires SecureVNC.** It ships with `UseDSMPlugin=1` and
`DSMPlugin=SecureVNCPlugin64.dsm`, so connections only work with that plugin
installed in the viewer and configured on the remote server. If your
installation does not use SecureVNC, set `UseDSMPlugin=0` and `DSMPlugin=` in
`data\template.vnc`. See `data\LEIA-ME-template-vnc.txt`.

For the password, prefer `Configurações > Credenciais UltraVNC`, which stores
it DPAPI-protected in the user profile instead of in plain text on disk.

## RealVNC

Default path:

```text
C:\Program Files\RealVNC\VNC Viewer\vncviewer.exe
```

The path can also be changed under:

```text
Configurações > Viewers VNC
```

RealVNC profiles are stored in `data\realvnc` and follow this naming format:

```text
<Sector>_<Host Name>.vnc
```

Example:

```text
Support_Workstation 01.vnc
```

If a profile is missing or empty, the application displays the expected filename.

## PsExec and remote printers

The printer listing runs a PowerShell collector on the remote machine through
PsExec and returns, for each installed queue:

- printer name;
- driver;
- port and address (IP or `USB`);
- whether it is shared, and the originating server when applicable.

The PsExec path is set under:

```text
Configurações > PsExec
```

It applies to every user of the computer (stored in `data\paths.json`). If the
field is left empty, the application looks for PsExec on `PATH`.

Common failures are translated into a readable message — host unreachable, name
not resolved, credentials refused, timed out — instead of the raw PsExec code.

## Per-user credentials and settings

Credentials are configured under:

```text
Configurações > Credenciais UltraVNC
```

Per-user files are stored in:

```text
C:\Users\<user>\Documents\VNC-Menu\
├─ creds.json
├─ settings.json
└─ hosts.json
```

- `creds.json`: UltraVNC credentials protected with Windows DPAPI.
- `settings.json`: UI preferences, current selection, and saved window geometry.
- `hosts.json`: personal host list when **Personalizada** or **Vazia** mode is used.

If Windows denies write access to `Documents\VNC-Menu\settings.json`, the application falls back to:

```text
%APPDATA%\VNC-Menu\settings.json
```

to avoid startup failures.

Viewer and PsExec paths are shared by the installation and live in `data\paths.json`.

## Shared installation data

```text
.\data\
├─ hosts.json             Shared host list.
├─ paths.json             Viewer and PsExec paths.
├─ template.vnc           UltraVNC profile in use (not version controlled).
├─ template.vnc.example   Example profile, no password (version controlled).
└─ realvnc\               RealVNC profiles.
```

Every JSON write is atomic: the content is written to a temporary file in the
same folder, flushed to disk, and only then replaces the destination. A power
loss mid-write cannot leave a half-written file.

## Updates

The application checks the latest release at:

```text
https://github.com/gabrielmariense/VNC-Menu/releases
```

The startup check can be turned off under `Configurações > Atualizações ao iniciar`. The manual check lives under `Configurações > Sobre > Buscar atualização`.

When a new version exists, the download runs with a progress bar and the install is handed to `VNC-Menu-Updater.pyw`, which runs outside the application, replaces the files, and relaunches VNC-Menu. User data and the contents of `data\` are preserved.

## Logs

Logs are stored in the application `logs` folder:

```text
.\logs\<windows-user>.log
.\logs\<windows-user>_error.log
```

Logged events include:

- application startup;
- VNC connections;
- remote restarts;
- `qwinsta` queries;
- printer queries;
- host-list changes;
- configuration changes;
- hostname/IP copy actions;
- administrative `C$` and remote startup-folder open attempts;
- updates;
- internal errors.

Both files are size-capped and keep one previous generation as `<name>.log.1`.

## Tests

The suite uses only the standard library and runs with the GUI stubbed out, in
its own temporary folder. Nothing under `Documents\VNC-Menu` or `data\` is
touched.

```bat
py -3 -m unittest discover -s tests -v
```

The tests are not needed to use the application.

## Building the executable

The default distribution model is source plus the updater. Packaging is optional.

Install the runtime dependencies and the packager:

```bat
py -3 -m pip install -r requirements.txt
py -3 -m pip install pyinstaller
```

Example using PyInstaller:

```bat
py -3 -m PyInstaller ^
  --onedir ^
  --noconsole ^
  --clean ^
  --name "VNC-Menu" ^
  --contents-directory _internal ^
  "VNC-Menu.pyw"
```

The contents of `data\` should not be embedded in the executable: it is writable
and belongs to the installation. Copy the `data\` folder next to the generated
executable instead.

## Notes

- Currently, only UltraVNC and RealVNC are supported.
- VNC viewers and PsExec are not bundled with the project.
- DPAPI-protected credentials cannot be directly shared between Windows users.
- Remote restart, `qwinsta`, PsExec, and `C$` access depend on environment permissions and policies.
- Changes to the shared host list may affect every user of the same installation.
- Files such as `creds.json`, `settings.json`, `data\template.vnc`, and sensitive profiles should not be committed to version control.

## License

This project is distributed under the MIT License. See [LICENSE](https://github.com/gabrielmariense/VNC-Menu/blob/main/LICENSE).
