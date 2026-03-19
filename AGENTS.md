# Repository Guidelines

## Project Structure & Module Organization
`main.py` is the CLI entrypoint and `main_gui.py` starts the Tk GUI. Core runtime code lives in `app/`, with audio capture, ASR backends, config loading, controller logic, hotkeys, and output sinks split by module. Use `app/plugins/` for optional recorder-style extensions. Tests live in `tests/` and follow the runtime module layout. Helper scripts are in `scripts/`, while `models/`, `files/`, and `logs/` hold runtime assets and local artifacts. Treat `build/`, `build_rebuilt/`, `dist/`, and `dist_rebuilt/` as generated output, not source.

## Build, Test, and Development Commands
Set up the local Windows environment with `.\setup_runtime.bat`; it creates `.venv`, installs `requirements.txt`, and downloads the default Sherpa model. Run dictation with `.\run_dictation.bat` or `python main.py --mode dictation --source microphone`. Run subtitles with `.\run_subtitles.bat` or `python main.py --mode subtitles --source loopback`. Start the GUI with `python main_gui.py`. Build distributables with `.\build_exe.bat`, which packages `UniSpeechRuntime.spec` into `dist\UniSpeechRuntime\`.

## Coding Style & Naming Conventions
Target Python 3.12+ and match the existing style: 4-space indentation, explicit type hints where helpful, small focused modules, and standard-library-first utilities. Use `snake_case` for modules, functions, variables, and config keys; use `PascalCase` for classes; use `UPPER_CASE` for constants such as `DEFAULT_CONFIG`. Preserve UTF-8 support, but prefer ASCII-only code/comments unless non-ASCII text is required for UI or docs.

## Testing Guidelines
This repo uses `unittest` test cases with `pytest` discovery settings in `pytest.ini`. Add tests under `tests/` as `test_*.py`, and name methods `test_*`. Run the suite with `python -m unittest discover -s tests -v`. Run a quick syntax pass before packaging with `python -m compileall main.py app tests`. Cover config validation, controller state changes, and Windows-specific integration edges with mocks rather than real devices where possible.

## Commit & Pull Request Guidelines
Recent commits use short, imperative subjects, sometimes with a scope prefix: `docs: rewrite bilingual README`, `Fix packaged model path resolution`. Keep commit titles concise and action-oriented. Pull requests should describe the user-visible change, list validation steps, and mention any Windows-only behavior or model/runtime assumptions. Include screenshots for GUI or overlay subtitle changes, and call out packaging impacts when `spec`, `build`, or runtime asset handling changes.
