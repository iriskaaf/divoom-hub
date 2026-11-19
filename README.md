# Divoom Hub

Приложение для Ditoo Pro и Times Gate на Windows 10/11. Показывает обложку текущего трека, меняет циферблаты и управляет подсветкой. Источник музыки — медиасессия Windows или Spotify Web API.

Основной интерфейс написан на C# / WinUI 3. Работа с Bluetooth, Wi-Fi, музыкой и рендером циферблатов выполняется в отдельном Python-процессе. Можно подключить несколько устройств каждого типа, переименовать их и настроить отдельно.

## Структура

- [winui/](winui/) — актуальный интерфейс, IPC-клиент, упаковка и проверки WinUI.
- [legacy/](legacy/) — самостоятельная прежняя версия на Python / PySide6. Её модули `core`, `bluetooth` и `timesgate` также используются бэкендом WinUI.
- [docs/architecture.md](docs/architecture.md) — поток данных и карта кода.
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) — компоненты, лицензии и графика.

## Сборка WinUI

Нужны Windows x64, .NET 8 SDK, инструменты разработки WinUI/XAML и Python 3.13. Проект использует Windows App SDK 2.6.5. Для разработки через Visual Studio установите поддержку WinUI и откройте `winui/divoom-hub-winui3.slnx`.

Из корня репозитория:

```powershell
py -3.13 -m venv legacy/.venv
legacy/.venv/Scripts/python -m pip install -r legacy/requirements.txt pyinstaller
pwsh -File winui/Build.ps1
```

Результат:

- `winui/artifacts/DivoomHub.WinUI/divoom-hub-winui3.exe` — основная версия.
- `winui/artifacts/test/divoom-hub-winui3_TEST.exe` — тестовая версия.

Копируйте всю папку сборки: Python, .NET и Windows App SDK поставляются рядом с EXE. Для запуска из Visual Studio выберите x64 и Unpackaged. Если Python-исходники находятся отдельно, задайте `DIVOOM_HUB_PYTHON_ROOT` или передайте `-PythonRoot` в скрипт сборки.

## Подключение

**Times Gate:** подключите часы к Wi-Fi через приложение Divoom. Компьютер должен находиться в той же сети. В мастере укажите IP и LocalToken из настроек устройства в приложении Divoom.

**Ditoo Pro:** выполните сопряжение с DitooPro-Audio в настройках Bluetooth Windows. Другой контроллер, например приложение Divoom на телефоне, может занимать соединение.

**Музыка:** медиасессия Windows работает без авторизации. Для воспроизведения на другом устройстве выберите Spotify Web API, укажите Client ID своего приложения Spotify и добавьте redirect URI `http://127.0.0.1:8888/callback`.

Закрытие основного окна сворачивает программу в трей. Команда «Выход» завершает бэкенд и возвращает встроенный циферблат, если эта настройка включена.

## Профили

Основной профиль: `%LOCALAPPDATA%/DivoomHub.WinUI`. LocalToken и авторизация Spotify хранятся в Windows Credential Manager.

TEST использует отдельный профиль `DivoomHub.WinUI_TEST`, при каждом запуске открывает приветствие и читает настройки старой Python-версии, если они есть. Исходный профиль Python не перезаписывается. Перед подключением устройств из TEST закройте другую версию через трей.

## Проверки

```powershell
Push-Location legacy
.venv/Scripts/python -m pytest -q
Pop-Location
legacy/.venv/Scripts/python winui/Backend/smoke_test.py winui/artifacts/DivoomHub.WinUI/Backend/DivoomHub.Backend.exe
legacy/.venv/Scripts/python winui/Backend/smoke_cover_flow.py (Resolve-Path legacy)
```

WinUI поддерживает `--ui-smoke-test <абсолютный-путь-к-отчёту>`. Проверка использует профиль в памяти: страницы в двух темах, мастер, выбор цвета, нативное меню, импорт/экспорт паков и IPC с Python. Сетевые проверки используют локальный имитатор Times Gate. Реальная цветопередача подсветки и одновременные Bluetooth-соединения требуют проверки на устройствах.

