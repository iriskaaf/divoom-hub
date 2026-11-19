"""Keep the test executable isolated from production data and IPC."""
import os
import sys
from pathlib import Path

TEST_MODE = (Path(sys.executable).stem.lower() == "divoomhub_test"
             if getattr(sys, "frozen", False)
             else os.environ.get("DIVOOM_HUB_PROFILE") == "test")
_override = os.environ.get("DIVOOM_HUB_PROFILE")
WINUI_MODE = _override in ("winui", "winui_test")
PROFILE_NAME = ("DivoomHub.WinUI_TEST" if _override == "winui_test" else "DivoomHub.WinUI") if WINUI_MODE else "DivoomHub_TEST" if TEST_MODE else "DivoomHub"
