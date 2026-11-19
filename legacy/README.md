# Divoom Hub · Legacy

Самостоятельная версия на Python 3.13 и PySide6 / Fluent Widgets. Основной интерфейс развивается в [../winui](../winui). Протоколы устройств и обработка музыки из этой папки используются обеими версиями.

## Запуск и сборка

```powershell
py -3.13 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python app.py
```

`build.bat` запускает проверки и собирает `dist/DivoomHub/DivoomHub.exe`. Для переноса нужна вся папка. `run.bat` запускает исходники. Закрытие окна сворачивает приложение в трей.

## Модули

- `app.py` — запуск приложения, одиночный экземпляр и диагностика.
- `gui/` — страницы и виджеты PySide6.
- `core/` — медиасессия Windows, Spotify, обработка обложек, настройки.
- `bluetooth/` — подключение к Ditoo и двоичный протокол.
- `timesgate/` — HTTP-клиент Times Gate, рендер циферблатов, пакеты и подсветка.
- `resources/` и `imgs/` — шрифты, иконки и фотографии устройств.
- `tests/` — модульные проверки и проверки GUI.

Профиль: `%LOCALAPPDATA%/DivoomHub`. Для отдельной тестовой копии используйте `tools/package_test.py` после сборки. Адрес и токен для автоподстановки можно задать переменными окружения `DIVOOM_TEST_GATE_IP` и `DIVOOM_TEST_GATE_TOKEN`; они применяются только к TEST.

Диагностические команды: `app.py --scan`, `app.py --probe`, `app.py --test-display`. Последние две работают с реальным устройством.
