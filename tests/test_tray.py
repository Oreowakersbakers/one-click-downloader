import ctypes
import importlib.util
import os
from pathlib import Path
import unittest


class TrayPortabilityTests(unittest.TestCase):
    def test_module_imports_when_winfunctype_is_unavailable(self):
        tray_path = Path(__file__).parents[1] / "oneclickdl" / "tray.py"
        original_name = os.name
        missing = object()
        original_winfunctype = getattr(ctypes, "WINFUNCTYPE", missing)

        try:
            os.name = "posix"
            if original_winfunctype is not missing:
                del ctypes.WINFUNCTYPE

            spec = importlib.util.spec_from_file_location("portable_tray", tray_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            self.assertFalse(module.IS_WINDOWS)
            self.assertIsNone(module.start(lambda: None, lambda: None))
        finally:
            os.name = original_name
            if original_winfunctype is not missing:
                ctypes.WINFUNCTYPE = original_winfunctype


if __name__ == "__main__":
    unittest.main()
