# Repository Guidelines

## Project Structure & Module Organization
- `arbit/`: Core package
  - `engine/`: triangle math and execution
  - `adapters/`: exchange connectors (CCXT-based)
  - `metrics/`: Prometheus exporters
  - `persistence/`: SQLite helpers
  - `cli/`: Typer CLI package (Typer entry point and commands)
- `tests/`: Pytest suite (`test_*.py`)
- `data/`: Local data/DB (gitignored)
- `Dockerfile`, `docker-compose.yml`: containerization
- `README.md`, `WARP.md`, `ROADMAP.md`: docs

## Build, Test, and Development Commands
- Create venv: `python -m venv .venv && source .venv/bin/activate`
- Install deps: `pip install -r requirements.txt pytest`
- Run tests: `pytest -q`
- Run a specific test: `pytest tests/test_cli.py::test_help`
- CLI (read-only): `python -m arbit.cli fitness --venue kraken --secs 10`
- CLI (keys check): `python -m arbit.cli keys:check`
- CLI (live, caution): `python -m arbit.cli live --venue alpaca`

## Coding Style & Naming Conventions
- Formatter/lint: Black, isort, Ruff (see `.deepsource.toml`). Use 4-space indents and type hints.
- Modules/functions: `snake_case`; classes: `PascalCase`; constants: `UPPER_SNAKE`.
- CLI commands use `name:sub` (e.g., `keys:check`). Keep help strings clear and action-focused.

## Testing Guidelines
- Framework: Pytest. Place tests under `tests/` as `test_*.py`.
- Prefer fast, deterministic tests. Mock network/exchange access; don’t hit real APIs.
- Use `typer.testing.CliRunner` for CLI tests. Add tests with any user-facing behavior change.

## Commit & Pull Request Guidelines
- Commits: follow Conventional Commits (`feat:`, `fix:`, `refactor:`, `style:`). Keep focused and descriptive.
- PRs: include purpose, linked issues, how to test (commands/log samples), and screenshots of CLI output when relevant.
- Required: passing tests; docs updated (`README.md`/`WARP.md`) if behavior or flags change.

## Security & Configuration Tips
- Never commit secrets. Copy `.env.example` to `.env` locally; use paper/sandbox keys first.
- `fitness` is read-only. `live` may place real orders depending on venue/keys; verify symbols and limits.
- Metrics: exposed on `http://localhost:9109/metrics` by default; set `PROM_PORT` to change.

