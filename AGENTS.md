# Repository Guidelines

## Project Structure & Module Organization
- `rss-agent/` houses the application code and runtime assets.
- `rss-agent/src/` contains Python modules organized by concern: `core/` (fetch/filter/AI pipeline), `fetchers/`, `formatters/`, `generators/`, and shared helpers in `utils.py`.
- `rss-agent/config/` stores runtime configuration (`config.yaml`, `weekly_config.yaml`).
- `rss-agent/scripts/` includes entry scripts for day-to-day runs.
- `rss-agent/output/` and `rss-agent/cache/` are runtime artifacts; keep generated files here.
- `rss-agent/venv/` is a local virtualenv; do not commit changes inside it.

## Build, Test, and Development Commands
- `python -m venv venv` then `source venv/bin/activate` to set up the environment.
- `pip install -r requirements.txt` installs dependencies.
- `bash scripts/run.sh --config config/config.yaml` runs the main pipeline.
- `bash scripts/generate_weekly.sh` generates the weekly report using `config/weekly_config.yaml`.
- `python main.py --help` lists CLI flags like `--dry-run` and `--hours`.

## Coding Style & Naming Conventions
- Use 4-space indentation and PEP 8 style for Python.
- Favor `snake_case` for functions/variables, `CapWords` for classes, and `UPPER_SNAKE_CASE` for constants.
- Keep module responsibilities narrow (e.g., fetchers should not format output).
- No formatter or linter is configured; keep changes minimal and readable.

## Testing Guidelines
- No automated tests are present in this repository.
- If you add tests, keep them under `rss-agent/tests/` and name them `test_*.py`.
- Prefer lightweight unit tests around `src/core/` and `src/utils.py`.

## Commit & Pull Request Guidelines
- Git history is minimal (`init` only), so no strict commit convention exists.
- Use concise, imperative commit subjects (e.g., "Add weekly generator options").
- PRs should describe behavior changes, configuration updates, and attach a sample output path in `rss-agent/output/` when relevant.

## Configuration & Runtime Notes
- API keys and feed URLs live in `rss-agent/config/*.yaml`; avoid hardcoding secrets in code.
- `cache/processed_urls.json` is used for deduplication; keep it out of PR diffs unless debugging.
