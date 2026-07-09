# VNC-Menu

A Windows desktop interface for organizing VNC connections and common remote-support tasks from a structured host list.

The project was created to speed up access to multiple machines, reduce repetitive work, and centralize operations such as VNC connections, remote restarts, session checks, and quick access to administrative shares.

<p align="center">
  <img src="assets/VNC-Menu PROMOTION.png" alt="Interface preview" width="850">
</p>

## Features

- Host organization by **Unit > Sector > Host**.
- Support for **UltraVNC** and **RealVNC**.
- Per-user UltraVNC credentials protected with **Windows DPAPI**.
- Shared or personal host lists.
- **Connect** and **Restart** action modes.
- Remote session checks with `qwinsta`, executed in the background.
- Per-host context menu with **Copy IP** and **Open Folder** (`\\HOST\c$`).
- Configuration for hosts, viewers, columns, theme, and window placement.
- Per-user audit and error logs.
- **PyInstaller**-compatible packaging.

## Requirements

- Windows.
- Python 3.12 or newer.
- UltraVNC Viewer for UltraVNC connections.
- RealVNC Viewer for RealVNC connections.
- Dependencies listed in `requirements.txt`.

Current dependencies:

```txt
pywinauto==0.6.9
pyinstaller>=6.0,<7.0
pywin32>=306
comtypes>=1.4.0
customtkinter>=5.2.2
```

## Installation

Clone the repository and run:

```bat
INSTALAR.bat
```

The installer checks whether Python is available, attempts to install it through `winget` if missing, updates `pip`, installs the dependencies, and validates the main imports.

Manual installation:

```bat
py -3 -m pip install -r requirements.txt
```

Run as a script:

```bat
py -3 VNC-Menu.pyw
```

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
- `viewer`: `ultravnc` or `realvnc`.

### Main actions

On the main screen, select the desired mode:

- **Connect**: opens the configured viewer for the host.
- **Restart**: asks for confirmation and sends a remote restart.
- **Users**: queries remote sessions with `qwinsta`.

The user-session query runs in the background to keep the interface responsive and displays a progress window while running.

### Manual host

The **Host manual** button follows the currently selected mode:

- in **Connect** mode, it asks for hostname/IP and viewer;
- in **Restart** mode, it asks for hostname/IP and confirmation.

Manual UltraVNC connections do not use automatic entry of the saved password.

### Context menu

Right-click a host to access:

- **Copy IP**: copies the configured `host` value;
- **Open Folder**: attempts to open the administrative share:

```text
\\HOST\c$
```

Access to `C$` depends on user permissions, SMB availability, firewall rules, and network policies.

### Editing hosts

The screen:

```text
Configurações > Hosts VNC
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

## Host list modes

### Default

Uses the shared installation `hosts.json`.

Recommended when multiple users should use the same host list.

### Custom

Creates a personal copy at:

```text
Documents\VNC-Menu\hosts.json
```

Recommended when a user needs to edit their own list without affecting others.

### Empty

Creates a clean personal list for a new setup.

> The current application UI uses the Portuguese labels **Padrão**, **Personalizada**, and **Vazia** for these modes.

## UltraVNC

Default path:

```text
C:\Program Files\uvnc bvba\UltraVNC\vncviewer.exe
```

The path can be changed under:

```text
Configurações > Caminhos dos Viewers
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

For saved hosts, the application can automatically enter stored UltraVNC credentials. Automatic credential entry is disabled for manual connections.

## RealVNC

Default path:

```text
C:\Program Files\RealVNC\VNC Viewer\vncviewer.exe
```

The path can also be changed under:

```text
Configurações > Caminhos dos Viewers
```

RealVNC profiles are stored in the `realvnc` folder and follow this naming format:

```text
<Sector>_<Host Name>.vnc
```

Example:

```text
Support_Workstation 01.vnc
```

If a profile is missing or empty, the application displays the expected filename.

## Per-user credentials and settings

Credentials are configured under:

```text
Configurações > Credenciais
```

Per-user files are stored in:

```text
C:\Users\<user>\Documents\VNC-Menu\
├─ creds.json
├─ settings.json
└─ hosts.json
```

- `creds.json`: UltraVNC credentials protected with Windows DPAPI.
- `settings.json`: UI preferences, viewer paths, current selection, and saved window geometry.
- `hosts.json`: personal host list when **Custom** or **Empty** mode is used.

If Windows denies write access to `Documents\VNC-Menu\settings.json`, the application falls back to:

```text
%APPDATA%\VNC-Menu\settings.json
```

to avoid startup failures.

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
- host-list changes;
- configuration changes;
- hostname/IP copy actions;
- administrative `C$` share open attempts;
- internal errors.

## Building the executable

Install the dependencies:

```bat
py -3 -m pip install -r requirements.txt
```

Example using PyInstaller:

```bat
py -3 -m PyInstaller ^
  --onedir ^
  --noconsole ^
  --clean ^
  --name "VNC-Menu" ^
  --contents-directory _internal ^
  --add-data "template.vnc;." ^
  --add-data "hosts.json;." ^
  "VNC-Menu.pyw"
```

After the build, RealVNC profiles can be placed under:

```text
dist\VNC-Menu\_internal\realvnc\
```

## Notes

- Currently, only UltraVNC and RealVNC are supported.
- VNC viewers are not bundled with the project.
- DPAPI-protected credentials cannot be directly shared between Windows users.
- Remote restart, `qwinsta`, and `C$` access depend on environment permissions and policies.
- Changes to the shared host list may affect every user of the same installation.
- Files such as `creds.json`, `settings.json`, and sensitive profiles should not be committed to version control.

## License

This project is distributed under the MIT License. See [LICENSE](https://github.com/gabrielmariense/VNC-Menu/blob/main/LICENSE).
