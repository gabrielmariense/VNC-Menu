# VNC-Menu

A Windows desktop interface for organizing VNC connections and common remote-support tasks from a structured host list.

The project was created to speed up access to multiple machines, reduce repetitive work, and centralize operations such as VNC connections, remote restarts, session checks, remote printer listings, and quick access to administrative shares.

<p align="center">
  <img src="assets/VNC-Menu PROMOTION.png" alt="Interface preview" width="850">
</p>

> The application interface is in Portuguese. Menu labels quoted below are the ones you will see on screen.

## Features

- Host organization by **Unit > Sector > Host**.
- Host search by name or IP/hostname within the selected unit.
- Support for **UltraVNC** and **RealVNC**, with a per-host VNC port.
- Per-user UltraVNC credentials protected with **Windows DPAPI**.
- Automatic UltraVNC authentication, toggleable between **Login automático** and **Login manual**.
- Shared or personal host lists.
- One-click connect on a host; restart from the context menu, with confirmation.
- Remote session checks with `qwinsta`, run in parallel in the background.
- Remote printer listing through **PsExec** + PowerShell.
- Re-running the printer mapping script **in the logged-on user's session**, with the queue drivers installed on the machine first.
- Per-host context menu with **Copy IP**, **Open c$**, **Open Startup folder**, **Printers** and **Sessions**; the manual host window offers the same actions minus **Copy IP** (the address was just typed there).
- Configuration for hosts, viewers, PsExec, columns, theme, and window placement.
- Update checks and installation from GitHub releases.
- Per-user audit and error logs, with automatic rotation.


## Credentials and automatic typing

With automatic login enabled, the app waits for the UltraVNC authentication
dialog and fills in the stored credential. Two rules hold it together:

- The credential is written **only** with `set_text()`, which writes into the
  control by its handle. Unlike `send_keys()`, it does not depend on which
  window holds the foreground, so the password cannot land in the search bar, a
  chat, or any field you click while the viewer opens. The module does not even
  import `send_keys`, deliberately.
- A new connection **cancels** the previous fill, so two attempts never compete
  for the same dialog. The dialog is also checked with `exists()` immediately
  before writing.

If the dialog's fields cannot be identified, the app **gives up** and you type.
There is no "blind" path — it was removed precisely because it was the only one
that typed without a bound control.

Field lookup uses `class_name`, the criterion for the `win32` backend in use,
with `control_type` as a second attempt. The audit log records which criterion
worked (`VNC_AUTO_LOGIN_FIELDS`) and, when none does, lists the class names of
the dialog's controls (`VNC_AUTO_LOGIN_ABORTED` with `controles=`).

## Requirements

- Windows.
- Python 3.12 or newer.
- UltraVNC Viewer for UltraVNC connections.
- RealVNC Viewer for RealVNC connections.
- PsExec (Sysinternals) v2.43 for the printer features (query, driver
  installation and script execution).
- Windows 8 or newer on the target machines: the printer features use
  `Get-Printer`, `Add-Printer` and the `ScheduledTasks` module.
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
├─ remote.py          VNC, remote restart, qwinsta, PsExec, printers, script execution.
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

- **clicking a host**: opens the viewer configured for it;
- **right-clicking a host**: context menu with restart, copy IP, open `c$`, open
  the startup folder, printers and sessions;
- **Usuários** (Users): queries remote sessions for the sector's hosts with `qwinsta`;
- **Impressoras** (Printers): opens the printers window;
- **Host manual**: opens the actions window for a host typed in on the spot.

Connect and Restart used to be *modes*: a global state decided what clicking a
host did. Leaving it on Restart and coming back later restarted a machine on
what felt like a connection click, so the mode was removed — clicking connects,
and restarting is a per-host action with confirmation.

The user query runs in the background with a progress window and in parallel
across hosts. The printer query runs inside the printers window itself, which
shows progress in its output area.

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

### Search

The bar above the action buttons finds hosts by **name** or by **IP/hostname**, across every sector of the **selected unit**. Each result shows the name, the address, and the sector it belongs to.

The search ignores case and accents, so `recepcao` finds `Recepção`.

While a search is active:

- the sectors stop driving the list and are dimmed;
- the area above the list shows `Buscando em: <unit>`;
- clicking a sector, switching unit, pressing `Esc`, or using the `✕` button returns to normal browsing.

Clicking a result connects, as in the normal list. Right-clicking opens the same context menu.

The query is not persisted. Reopening the application returns to the selected sector.

### Context menu

Right-click a host to access:

- **Host/IP**: shows the configured `host` value (informational only);
- **Reiniciar** (Restart): asks for confirmation and sends the restart;
- **Copiar IP** (Copy IP): copies that value;
- **Abrir c$** (Open c$): attempts to open `\\HOST\c$`;
- **Abrir Menu Iniciar** (Open Startup folder): opens the all-users startup folder on the remote machine:

```text
\\HOST\c$\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup
```

- **Impressoras** (Printers): opens the printers window with the host already
  filled in. Nothing is queried on its own: a context menu opened by mistake
  does not fire PsExec at the machine;
- **Sessões** (Sessions): shows the raw `qwinsta` text for that machine, which
  is what tells you whether it was access denied, an unresolved name, or a
  timeout.

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

## Printers window

One window for the whole printer call: check what is mapped, re-run the script,
and check again to confirm. The output area is shared by both actions, so you
can compare before and after without switching windows.

Opened from the host list or the context menu, the field is already filled in;
from the toolbar button it comes up empty. Nothing runs on its own in either
case — querying and re-running have different costs on the user's machine, so
the choice is always explicit.

The script side has the file name (which varies per machine), a button that
opens the folder over `c$` so you can check the name, and the startup folder
path:

```text
C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup
```

### Why the script is not run as SYSTEM

The script uses `AddWindowsPrinterConnection` and `SetDefaultPrinter`, which
write to the **caller's** `HKCU`. Run as SYSTEM — or as the technician's own
account — the printers would be mapped into the wrong profile and the user at
the machine would see no difference at all.

So execution works like this:

1. PsExec runs a PowerShell as SYSTEM on the machine.
2. That PowerShell resolves the logged-on user
   (`Win32_ComputerSystem.UserName`, falling back to the owner of
   `explorer.exe`).
3. It creates a temporary scheduled task with `LogonType Interactive`, which
   uses the **token of the already-open session** and therefore needs no
   password from the user.
4. It starts the task, waits for it to finish, and removes the task.

With nobody logged on, nothing is executed: without a user token, running as
SYSTEM would leave the machine worse off than before.

The `.vbs` runs through **wscript** in batch mode (`//nologo //B`), which has no
console: nothing appears on the user's screen and there is no window for them to
close mid-run — closing the `cscript` console used to kill the script, possibly
after the printers had been deleted and before they were remapped. `.cmd` and
`.bat` have no equivalent: `cmd.exe` opens a prompt, and the confirmation says
so beforehand.

The task is created with `-AllowStartIfOnBatteries` (Windows defaults to not
starting a task on battery, which made a laptop report "never entered
execution") and with its own execution time limit, so Windows kills a stuck
script after the app has already removed the task and moved on.

### Driver installation

`AddWindowsPrinterConnection` does two things with different requirements:

| Step | Writes to | Requires |
|---|---|---|
| Installing the driver from the server | the **machine's** driver store | administrative privilege |
| Creating the printer connection | the **user's** `HKCU` | their token |

Since the PrintNightmare patch (KB5005652),
`RestrictDriverInstallationToAdministrators` is on by default: a standard user
cannot install a printer driver, not even by hand. That is what leaves a machine
unable to pull the queue from the server no matter how often the script runs.

So **before** running the script, the app reads the `\\server\queue` paths
written in the `.vbs` itself and runs `Add-Printer -ConnectionName` for each
one, as SYSTEM. The driver goes into the machine's driver store; after that, the
mapping in the user's context no longer needs an administrator.

It is not optional and there is no checkbox: it is cheap (an already-installed
queue counts as success), requires no credentials, and leaving it to the
operator would only work if they knew in advance which machines need it — which
is exactly what they cannot know before trying.

Notes:

- It runs as **SYSTEM**, which presents itself to the print server as the
  machine account (`DOMAIN\PC-NAME$`). This is the same path the printer query
  already uses to read the server's queues.
- Running with a named credential (`psexec -u/-p`) was tried and **does not
  work**: PsExec performs an interactive logon on the remote computer, and the
  administrative account does not hold that right on workstations — logon 1385,
  with the correct password.
- `Add-Printer` raises real errors, so the window shows **which queue** failed
  and **why** — the diagnosis the `.vbs` never gives.
- The connection it creates stays in SYSTEM's profile. That is deliberate: what
  matters is the driver, and removing it afterwards would only add a way to fail
  after the goal was already reached.
- If the installation does not run at all, the script is **not** executed:
  deleting the user's printers with no guarantee of remapping would leave the
  machine worse off.

### Limits

- The run result **does not prove** the printers came back. The script keeps
  `ON ERROR RESUME NEXT` on from start to finish, so it exits 0 even when it
  fails. Confirmation is querying again, in the same place.
- While the script runs, the user's printers are unavailable: it deletes every
  queue and network connection before remapping.
- Driver installation only finds queues written as quoted literals in the
  `.vbs`. A script that builds the path from a variable or a loop is reported as
  "no path found", not silently ignored.
- `Register-ScheduledTask` with an interactive logon depends on the domain's
  scheduled-task policy. When it refuses, the window shows the Windows message
  instead of trying another path on its own.
- The script field accepts only a **file name** ending in `.vbs`, `.cmd` or
  `.bat`, with no path, so the field cannot become remote execution of any file.

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

Common failures are translated into a readable message such as host unreachable,
name not resolved, credentials refused and timed out, instead of the raw PsExec
code.

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
