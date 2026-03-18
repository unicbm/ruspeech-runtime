from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


class RuntimeScriptTests(unittest.TestCase):
    def test_setup_runtime_has_a_valid_model_bootstrap_path(self) -> None:
        setup_script = (REPO_ROOT / "setup_runtime.bat").read_text(encoding="utf-8")
        model_exists = (REPO_ROOT / "models" / "sherpa-onnx-ru-streaming" / "model.onnx").exists()
        download_script_exists = (REPO_ROOT / "scripts" / "download_russian_model.ps1").exists()

        self.assertIn("models\\sherpa-onnx-ru-streaming\\model.onnx", setup_script)
        self.assertTrue(model_exists or download_script_exists)

    def test_requirements_include_pyinstaller_for_build_exe(self) -> None:
        requirements = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        self.assertTrue(any(line.lower().startswith("pyinstaller") for line in requirements))


if __name__ == "__main__":
    unittest.main()
