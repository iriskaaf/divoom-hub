import json
import os
from pathlib import Path
import subprocess
import sys


def test_test_profile_does_not_access_production(tmp_path):
    env = dict(os.environ, DIVOOM_HUB_PROFILE="test", LOCALAPPDATA=str(tmp_path))
    code = '''
import json
import winreg
from core.settings import APP_DIR, Settings
from core.spotify import KEYRING_SERVICE, LEGACY_KEYRING_SERVICE
from gui.main_window import INSTANCE_KEY
from core import autostart
winreg.OpenKey = lambda *a: (_ for _ in ()).throw(AssertionError("registry accessed"))
assert not autostart.is_enabled()
autostart.refresh()
autostart.set_enabled(True)
Settings().save()
print(json.dumps([str(APP_DIR), KEYRING_SERVICE, LEGACY_KEYRING_SERVICE, INSTANCE_KEY]))
'''
    result = subprocess.run([sys.executable, "-c", code], env=env,
                            cwd=Path(__file__).resolve().parent.parent,
                            capture_output=True, text=True, check=True)
    data = json.loads(next(line for line in result.stdout.splitlines() if line.startswith("[\"")))
    assert Path(data[0]) == tmp_path / "DivoomHub_TEST"
    assert data[1:] == ["DivoomHub_TEST", "DivoomHub_TEST", "DivoomHub_TEST-single-instance"]
    assert not (tmp_path / "DivoomHub").exists()


def test_gui_launch_resets_only_test_config(tmp_path):
    code = """
from core.settings import Settings, CONFIG_PATH, settings_for_gui_launch
previous = Settings(tg_ip="192.168.1.10", tg_token="123", onboarding_completed=True)
previous.save()
before = CONFIG_PATH.read_bytes()
result = settings_for_gui_launch(Settings.load())
from core.profile import TEST_MODE
if TEST_MODE:
    assert result.tg_ip == "" and not result.onboarding_completed
    assert not Settings.load().onboarding_completed
else:
    assert result.tg_ip == "192.168.1.10" and result.onboarding_completed
    assert CONFIG_PATH.read_bytes() == before
"""
    for profile in ("test", "production"):
        env = dict(os.environ, DIVOOM_HUB_PROFILE=profile, LOCALAPPDATA=str(tmp_path/profile))
        subprocess.run([sys.executable, "-c", code], env=env, check=True,
                       cwd=Path(__file__).resolve().parent.parent)
