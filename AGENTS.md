# Repository Guidelines

## Project Structure & Module Organization
`arbit/` contains the core package: `engine/` for triangle math and execution, `adapters/` for CCXT exchange connectors, `metrics/` for Prometheus exporters, `persistence/` for SQLite helpers, and `cli/` for Typer commands. Tests live in `tests/` as `test_*.py`. Local data and SQLite files stay in `data/` (gitignored). Container assets live at `Dockerfile` and `docker-compose.yml`; high-level docs are `README.md`, `WARP.md`, and `ROADMAP.md`.

## Build, Test, and Development Commands
Create a virtualenv with `python -m venv .venv && source .venv/bin/activate`. Install tooling via `pip install -r requirements.txt pytest`. Run the full suite with `pytest -q` or a targeted case like `pytest tests/test_cli.py::test_help`. The CLI can be explored read-only through `python -m arbit.cli fitness --venue kraken --secs 10`; verify API credentials using `python -m arbit.cli keys:check` before any live run.

## Coding Style & Naming Conventions
Format with Black and isort, lint with Ruff; all use four-space indentation. Favor type hints everywhere. Functions and modules use `snake_case`, classes use `PascalCase`, constants use `UPPER_SNAKE`. CLI commands follow the `name:sub` pattern and should ship with clear help strings.

## Testing Guidelines
Use Pytest fixtures and mocks to keep tests deterministic - never hit real exchanges. Name tests `test_*` and colocate them under `tests/`. Prefer `typer.testing.CliRunner` for CLI assertions. Add tests alongside behavior changes, especially around order routing and persistence paths.

## Commit & Pull Request Guidelines
Commits follow Conventional Commits (e.g., `feat:`, `fix:`, `refactor:`) and stay scope-focused. PRs should link issues, describe the motivation, list validation steps (`pytest -q`, CLI samples), and include CLI screenshots when behavior changes. Ensure all tests pass before requesting review.

## Security & Configuration Tips
Copy `.env.example` to `.env`, keep real keys out of git, and start with paper or sandbox credentials. `fitness` is read-only; treat `live` sessions with production keys cautiously. Metrics expose on `http://localhost:9109/metrics`; set `PROM_PORT` if you need a different port.
