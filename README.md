<div align="center">
  <img src="winui/Assets/logo.png" width="96" height="96" alt="Divoom Hub">
  <h1>Divoom Hub</h1>
  <p><strong>Your music, on your Divoom displays.</strong></p>
  <p>Album artwork, clock faces, and lighting for Times Gate and Ditoo Pro.<br>One Windows app. Multiple devices. Your setup.</p>

  <p>
    <img src="https://img.shields.io/badge/Windows-10%20%2F%2011-0078D4?style=flat-square" alt="Windows 10 / 11">
    <img src="https://img.shields.io/badge/UI-WinUI%203-8B5CF6?style=flat-square" alt="WinUI 3">
    <img src="https://img.shields.io/badge/.NET-8-512BD4?style=flat-square" alt=".NET 8">
    <img src="https://img.shields.io/badge/Backend-Python-3776AB?style=flat-square" alt="Python backend">
  </p>

  <p>
    <a href="#versions-and-downloads"><strong>Download</strong></a> ·
    <a href="#getting-connected">Setup</a> ·
    <a href="#building-from-source">Build</a> ·
    <a href="docs/architecture.md">Architecture</a> ·
    <a href="https://github.com/iriskaaf/divoom-hub/issues">Report a bug</a>
  </p>
</div>

---

## Supported devices

Divoom Hub currently supports **two device models: Times Gate and Ditoo Pro**. Support for more Divoom devices is planned, and the compatibility list will grow over time.

<table>
  <tr>
    <td align="center" width="50%">
      <img src="winui/Assets/times-gate.png" width="300" alt="Divoom Times Gate"><br>
      <strong>Times Gate</strong><br>
      <sub>Wi-Fi · five 128 × 128 displays</sub>
    </td>
    <td align="center" width="50%">
      <img src="winui/Assets/ditoo.png" width="160" alt="Divoom Ditoo Pro"><br>
      <strong>Ditoo Pro</strong><br>
      <sub>Bluetooth · 16 × 16 pixel display</sub>
    </td>
  </tr>
  <tr>
    <td>Custom clock faces, album artwork on the center display, your own images, and lighting that follows the music.</td>
    <td>Pixel-art album covers, image adjustments, brightness controls, and idle display modes.</td>
  </tr>
</table>

The WinUI version supports multiple units of each model, with separate names and settings for every device.

## Features

- **Music from Windows.** Read the current track and artwork from a Windows media session without signing in. Use Spotify only or allow other compatible players.
- **Spotify Web API.** Follow playback when your music is playing on another device.
- **Custom clock faces.** Choose built-in styles, adjust colors, reorder faces, and import or export face packs.
- **Artwork-based colors.** Let Times Gate clock faces and lighting follow the album palette, with manual colors restored when playback pauses.
- **Multiple devices.** Add, rename, and configure several Times Gate and Ditoo Pro units in the WinUI version.
- **Tray controls.** Access music and clock-face actions from the system tray, with light and dark interface themes.

## Versions and downloads

| Version | Purpose | Get it |
| :--- | :--- | :--- |
| **WinUI 3** | Current application: C# interface with a bundled Python backend | [Download Windows x64](https://github.com/iriskaaf/divoom-hub/releases/latest/download/DivoomHub-WinUI-windows-x64.zip) · [Latest release](https://github.com/iriskaaf/divoom-hub/releases/latest) |
| **Python Legacy · 1.8.1** | Previous standalone PySide6 application | [Download Windows ZIP](https://github.com/iriskaaf/divoom-hub/releases/download/legacy-v1.8.1/DivoomHub-1.8.1-legacy-windows.zip) · [Release notes](https://github.com/iriskaaf/divoom-hub/releases/tag/legacy-v1.8.1) |
| **WinUI Archive · Nov 18, 2026** | Preserved intermediate build | [Archived release](https://github.com/iriskaaf/divoom-hub/releases/tag/archive-winui-2026-11-18) |

> [!NOTE]
> The current WinUI release includes its runtimes and Python backend. Extract the entire folder and launch `divoom-hub-winui3.exe`. A separate TEST archive is available on the release page.
>
> The Legacy ZIP includes a ready-to-run application. Extract the **entire folder** and launch `DivoomHub.exe`. The archived WinUI build requires a separate Python environment and is not a replacement for the current version in `main`.

## Getting connected

### Times Gate

1. Connect the device to Wi-Fi using the Divoom mobile app.
2. Connect your PC to the same local network.
3. Add Times Gate in Divoom Hub and enter its IP address and LocalToken from the device settings in the Divoom app.

### Ditoo Pro

1. Open **Windows Settings → Bluetooth & devices**.
2. Pair with **DitooPro-Audio**.
3. Add Ditoo Pro in Divoom Hub. If the Divoom app on your phone is occupying the connection, disconnect the phone from the device over Bluetooth.

### Music source

| Source | When to use it | Setup |
| :--- | :--- | :--- |
| **Windows media session** | Music is playing on this PC | No sign-in; the player must expose playback through Windows SMTC |
| **Spotify Web API** | Music is playing on another device | Your Spotify application's Client ID and account authorization |

For Spotify Web API, register this redirect URI in your Spotify application settings:

```text
http://127.0.0.1:8888/callback
```

Closing the window minimizes Divoom Hub to the tray. Use the tray's **Exit** command to quit. Times Gate returns to its built-in clock face on exit when that setting is enabled.

## Building from source

Requires **Windows x64**, **.NET 8 SDK**, **Python 3.13**, **PowerShell 7**, and **WinUI/XAML development tools**. The project uses Windows App SDK 2.6.5.

```powershell
git clone https://github.com/iriskaaf/divoom-hub.git
cd divoom-hub

py -3.13 -m venv legacy/.venv
legacy/.venv/Scripts/python -m pip install -r legacy/requirements.txt pyinstaller
pwsh -File winui/Build.ps1
```

| Build | Executable |
| :--- | :--- |
| Main | `winui/artifacts/DivoomHub.WinUI/divoom-hub-winui3.exe` |
| TEST | `winui/artifacts/test/divoom-hub-winui3_TEST.exe` |

The build script bundles Python, .NET, and Windows App SDK. Copy the entire output folder when moving the application to another location.

<details>
<summary><strong>Developing in Visual Studio</strong></summary>

Open `winui/divoom-hub-winui3.slnx`, select **x64 → Unpackaged**, and run the project. Python source and its virtual environment are loaded from the adjacent `legacy` folder.

For a separate Python checkout, set `DIVOOM_HUB_PYTHON_ROOT` or pass its path through `Build.ps1 -PythonRoot`.

</details>

<details>
<summary><strong>Profiles and the TEST edition</strong></summary>

| Edition | Data folder |
| :--- | :--- |
| WinUI | `%LOCALAPPDATA%/DivoomHub.WinUI` |
| WinUI TEST | `%LOCALAPPDATA%/DivoomHub.WinUI_TEST` |
| Python Legacy | `%LOCALAPPDATA%/DivoomHub` |

WinUI stores LocalToken and Spotify credentials in Windows Credential Manager.

TEST shows the welcome screen on every launch and imports settings from the Python version when available. It does not overwrite the original Python profile. Exit other editions through the tray before connecting physical devices from TEST.

</details>

## Under the hood

```text
divoom-hub/
├── winui/                    C# / WinUI 3
│   ├── Pages/                Home, devices, settings, and setup
│   ├── Controls/             Shared interface controls and tray
│   ├── Models/               Profiles, devices, and clock-face packs
│   ├── Services/             IPC, credentials, and startup
│   └── Backend/              Python worker and integration checks
├── legacy/                   Standalone Python application
│   ├── core/                 Music, artwork, and settings
│   ├── bluetooth/            Ditoo connection and protocol
│   ├── timesgate/            Times Gate HTTP, rendering, and lighting
│   ├── gui/                  Previous PySide6 interface
│   └── tests/                Python tests
└── docs/                     Architecture documentation
```

WinUI communicates with Python through JSON lines over the child process's standard streams. One music engine feeds independent device workers. Both editions share the `core`, `bluetooth`, and `timesgate` modules; the WinUI backend does not load PySide6.

**[Explore the architecture and the media session → artwork → center display flow →](docs/architecture.md)** *(Currently documented in Russian.)*

## Tests

```powershell
Push-Location legacy
.venv/Scripts/python -m pytest -q
Pop-Location

legacy/.venv/Scripts/python winui/Backend/smoke_test.py winui/artifacts/DivoomHub.WinUI/Backend/DivoomHub.Backend.exe
legacy/.venv/Scripts/python winui/Backend/smoke_cover_flow.py (Resolve-Path legacy)
```

WinUI also supports `--ui-smoke-test <absolute-report-path>`. It checks pages in both themes, setup, color selection, menus, clock-face packs, and Python IPC. Network tests use a local Times Gate simulator.

Physical LED color reproduction and concurrent Bluetooth connections require separate testing on real devices.

## Feedback

Found a bug? [Open an issue](https://github.com/iriskaaf/divoom-hub/issues) with your app version, device model, Windows version, and steps to reproduce it. Include a screenshot for interface problems. Keep LocalToken and authorization credentials out of public reports.

## Acknowledgments

Thanks to the people maintaining the open-source projects that Divoom Hub builds on:

- **[WinUI and Windows App SDK](https://github.com/microsoft/WindowsAppSDK)** and **[.NET](https://github.com/dotnet/runtime)** for the Windows interface and runtime.
- **[Python](https://www.python.org/)** and **[PyWinRT](https://github.com/pywinrt/pywinrt)** for the backend and access to Windows media sessions.
- **[Qt / PySide6](https://www.qt.io/qt-for-python)** and **[Fluent Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)** for the legacy interface.
- **[Pillow](https://github.com/python-pillow/Pillow)**, **[Requests](https://github.com/psf/requests)**, **[keyring](https://github.com/jaraco/keyring)**, **[PyInstaller](https://pyinstaller.org/)**, and **[pytest](https://github.com/pytest-dev/pytest)** for image processing, networking, credential storage, packaging, and testing.
- The designers of the bundled open fonts, and everyone who shares device observations, reports bugs, or helps test the app on real hardware.

Component licenses and artwork credits are listed in [Third-party notices](THIRD_PARTY_NOTICES.md).

---

<div align="center">
  <sub>An independent project. Not an official Divoom or Spotify application.</sub><br>
  <sub><a href="THIRD_PARTY_NOTICES.md">Third-party components, fonts, and licenses</a></sub>
</div>
