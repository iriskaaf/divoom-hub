"""Package an isolated test copy from the production onedir build."""
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent.parent


def main():
    source = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "dist" / "DivoomHub"
    target = ROOT / "divoom_hub_TEST"
    if not (source / "DivoomHub.exe").is_file():
        raise SystemExit("Build DivoomHub.spec first")
    shutil.copytree(source, target, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("DivoomHub.exe"))
    shutil.copy2(source / "DivoomHub.exe", target / "DivoomHub_TEST.exe")
    (target / "RESET_TEST_PROFILE.bat").write_text(
        '@echo off\ncd /d "%~dp0"\n'
        'start /wait "" "%~dp0DivoomHub_TEST.exe" --reset-test-profile\n'
        'if errorlevel 1 (echo Reset failed. Exit TEST from the tray and try again. & pause & exit /b 1)\n'
        'echo TEST profile reset. Production settings were not changed.\npause\n', encoding="ascii")
    (target / "README_TEST.txt").write_text(
        "Divoom Hub TEST\n\n"
        "Запуск: DivoomHub_TEST.exe. Не переименовывайте EXE: имя выбирает тестовый профиль.\n"
        "Настройки и логи: %LOCALAPPDATA%\\DivoomHub_TEST. Spotify использует отдельную запись в диспетчере учётных данных.\n"
        "Конфиг TEST автоматически сбрасывается при каждом новом запуске. Для повторения мастера выйдите из TEST через трей и откройте EXE снова.\n"
        "Сброс очищает настройки и авторизацию TEST; кэш и файлы паков остаются на диске. Основной профиль не затрагивается.\n"
        "Обе программы независимы, но команды подключённому физическому устройству остаются общими.\n", encoding="utf-8-sig")
    print(target / "DivoomHub_TEST.exe")


if __name__ == "__main__":
    main()
