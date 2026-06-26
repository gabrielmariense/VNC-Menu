# VNC-Menu

A lightweight Windows GUI for organizing and opening VNC connections from a structured host list.

The goal is to give technicians quick access to multiple machines without manually opening several VNC profiles or repeatedly typing the same credentials.

<p align="center">
  <img src="assets/VNC-Menu PROMOTION.png" alt="Interface preview" width="850">
</p>

## Features

- CustomTkinter desktop interface for Windows.
- Host organization by **Unit > Sector > Host**.
- Currently supports only **UltraVNC** and **RealVNC**.
- UltraVNC connections using a shared `template.vnc`.
- RealVNC connections using `.vnc` profile files.
- Per-user credentials encrypted with Windows DPAPI.
- Per-user settings.
- Shared or personal host lists.
- First-run host list selection: **Padrão**, **Personalizada** or **Vazia**.
- Warning before editing the shared host list.
- Optional host restart action.
- Logged-in user/session check using `qwinsta`.
- Per-user audit logs under the application `logs` folder.
- Dark mode.
- PyInstaller-compatible structure.

## Requirements

- Windows.
- Python 3.12 or newer.
- UltraVNC Viewer installed for UltraVNC connections.
- RealVNC Viewer installed for RealVNC connections.
- Python packages listed in `requirements.txt`.

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

The installer checks whether Python is available, attempts to install it through `winget` if missing, updates `pip`, installs the requirements and validates the main imports.

Manual installation:

```bat
py -3 -m pip install -r requirements.txt
```

Run as a script:

```bat
py -3 VNC-Menu-v5.pyw
```

## Recommended structure

```text
VNC-Menu/
├─ VNC-Menu-v5.pyw
├─ requirements.txt
├─ INSTALAR.bat
├─ template.vnc
├─ hosts.json
├─ realvnc/
│  └─ example-profile.vnc
└─ logs/
   └─ <windows-user>.log
```

When packaged with PyInstaller, application data is expected inside `_internal`:

```text
VNC-Menu/
├─ VNC-Menu.exe
└─ _internal/
   ├─ hosts.json
   ├─ template.vnc
   └─ realvnc/
```

Per-user files:

```text
C:\Users\<user>\Documents\VNC-Menu\
├─ creds.json
├─ settings.json
└─ hosts.json
```

Per-user logs:

```text
.\logs\<windows-user>.log
.\logs\<windows-user>_error.log
```

## hosts.json format

The host list uses a JSON structure based on units, sectors and hosts.

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

If `viewer` is omitted or invalid, the app defaults to `ultravnc`.

## UltraVNC

Expected UltraVNC Viewer path:

```text
C:\Program Files\uvnc bvba\UltraVNC\vncviewer.exe
```

The app uses a `template.vnc` file from the application data folder. It copies the template to a temporary file, injects the target host and starts UltraVNC from that temporary profile.

## RealVNC

Expected RealVNC Viewer path:

```text
C:\Program Files\RealVNC\VNC Viewer\vncviewer.exe
```

RealVNC profiles should be stored in the `realvnc` folder.

Expected filename format:

```text
<Sector>_<Host Name>.vnc
```

Example:

```text
Support_Workstation 01.vnc
```

If the profile is missing or empty, the app shows a dialog with options to create the file or copy the expected filename.

## Credentials

Credentials are configured from:

```text
Configurações > Credenciais
```

They are stored per Windows user in:

```text
Documents\VNC-Menu\creds.json
```

Passwords are encrypted with Windows DPAPI, so the encrypted credentials are tied to the Windows account that created them.

## Host list modes

### Padrão

Uses the shared `hosts.json` from the application folder.

Use this when all users of the same installation should share the same host list.

### Personalizada

Copies the shared `hosts.json` to `Documents\VNC-Menu`.

Use this when a user needs to edit their own list without affecting other users.

### Vazia

Creates a personal host list from the default structure embedded in the script.

Use this for a clean setup.

## Audit logs

The app writes per-user logs to:

```text
.\logs\<windows-user>.log
```

Logged actions include:

- app start;
- host list selection or changes;
- shared list edit prompt choices;
- VNC connection attempts and starts;
- restart attempts;
- restart command sent or errors;
- logged-user queries;
- unit, sector and host changes;
- host list saves;
- RealVNC profile renames.

Example:

```text
[2026-06-25 09:30:12] user=john action=CONNECTION_ATTEMPT details=viewer=UltraVNC; name=Workstation 01; host=192.168.1.10; setor=Support
```

## Building an executable

Install dependencies:

```bat
py -3 -m pip install -r requirements.txt
```

Example PyInstaller command:

```bat
py -3 -m PyInstaller ^
  --onedir ^
  --noconsole ^
  --clean ^
  --name "VNC-Menu" ^
  --contents-directory _internal ^
  --add-data "template.vnc;." ^
  --add-data "hosts.json;." ^
  "VNC-Menu-v5.pyw"
```

After building, place any RealVNC profiles inside:

```text
dist\VNC-Menu\_internal\realvnc\
```

## Notes

- Currently, only UltraVNC and RealVNC are supported.
- VNC viewers are not bundled with this project.
- Credentials are not shared between Windows users.
- Shared host list edits affect all users using the same application folder.
- Restart actions depend on Windows permissions and network policy.
- The `qwinsta` user/session check depends on Windows remote query access.

## License

Define a license before publishing the project.
