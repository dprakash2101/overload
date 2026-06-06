# Overload — Project Guide

## What is this?

Overload is a free, open-source load testing tool that reads Postman collections and provides a browser-based UI. Published as `overload` on PyPI, command is `overload`.

## Quick Start

```bash
pip install -e ".[dev]"   # Install in dev mode
overload                   # Opens browser UI on port 3000
overload run --collection path/to/collection.json --pattern burst  # CLI mode
```

## Project Structure

```
src/overload/           # Main package (src layout)
  collection/           # Postman collection parsing
    data_source.py      # CSV data-driven testing (DataSource, VariableContext.derive)
    environment.py      # Postman environment file parsing
    models.py           # ParsedCollection, ParsedRequest, AuthConfig, etc.
    parser.py           # Collection JSON → ParsedCollection
    variables.py        # VariableContext — scope-chain variable resolution
  engine/               # Test execution
    assertions.py       # Threshold expressions + JUnit XML
    auth.py             # OAuth2 pre-run token acquisition
    http_client.py      # Async httpx wrapper; CSV row cycling
    load_patterns.py    # All load patterns (Burst, Load, Stress, Spike, Soak, Ramp, Breakpoint, Custom)
    models.py           # PatternConfig, Stats, RunProgress, RequestResult, Threshold, etc.
    rate_limiter.py     # Rate-limit validation pattern
    runner.py           # Sequential runner
    service.py          # Shared run orchestration used by web API and MCP server
  mcp_server.py         # MCP server (stdio) — all MCP tool logic lives here
  report/               # HTML report generation + CSV/JSON export
    templates/          # Jinja2 templates, CSS, JS for reports
  web/                  # FastAPI browser UI
    routes/
      api.py            # REST API endpoints (delegates run execution to engine/service.py)
      ws.py             # WebSocket broadcast
    static/css/         # UI stylesheets
    static/js/          # Vanilla JS frontend (app, collection, runner, charts, docs)
    templates/          # index.html SPA shell
  config_file.py        # overload.config.yaml read/write
  utils/                # Naming, timestamps
  cli.py                # CLI entry point (overload, overload run, overload sequential, overload mcp)
tests/                  # Unit tests (pytest)
  fixtures/             # Sample Postman collections for tests
```

## File Naming Convention

**Feature code must live in files whose name reflects the feature.** This makes debugging
and navigation fast — you always know exactly which file to open.

| Feature / domain | File prefix / name |
|------------------|--------------------|
| MCP server tools | `mcp_*.py` — e.g. `mcp_server.py`, `mcp_utils.py` |
| Rate-limit logic | `rate_limit*.py` — e.g. `rate_limiter.py`, `rate_limit_utils.py` |
| Load patterns    | `load_patterns.py` (single file; new pattern families get `load_*.py`) |
| Auth flows       | `auth*.py` |
| Data / CSV       | `data_source.py`, `data_*.py` |
| Report output    | `report/*.py` (inside the `report/` package) |

The general rule: **if a file is hard to find by name alone, rename it**. Never lump
unrelated features into a generic `utils.py` or `helpers.py`. The engine service
(`engine/service.py`) is an intentional exception — it is shared orchestration plumbing,
not a named feature.

Test files follow the same pattern: `test_rate_limiter.py` tests `rate_limiter.py`,
`test_mcp_server.py` tests `mcp_server.py`, etc.

## Tech Stack

- **Python 3.10+**, asyncio for concurrency
- **FastAPI + Uvicorn** — web server, WebSocket
- **httpx** — async HTTP client
- **Jinja2** — report templates
- **Vanilla JS + Chart.js** — frontend (no build step)
- **pytest** — testing

## Development Principles

- **Build it right the first time.** Write complete, production-quality code on the first pass. Do not leave TODOs, placeholders, or partial implementations to revisit later.
- **First principles thinking.** Understand the problem from the ground up before writing code. Don't copy patterns blindly — reason about why a particular approach is correct for this specific case.
- **Honest feedback.** If the user's approach is wrong or suboptimal, say so directly with reasoning. Don't silently go along with a bad idea.
- **Major changes require planning.** Any significant architectural change or new feature should be discussed and planned before implementation.
- **PEP 8 compliance.** Follow PEP 8 style guidelines strictly.
- **Lazy imports only when necessary.** Use module-level imports by default. Only use lazy imports when there's a concrete performance reason (e.g., heavy optional dependency in a rarely-used code path).
- **Tests are required for every change.** Every new feature, bug fix, or behaviour change must include tests. New code must not lower test coverage. When a bug is fixed, add a regression test that would have caught it.
- **Live dashboard is non-negotiable for interactive mode.** Every load pattern must emit progress updates at least every ~0.5 seconds during execution so the browser dashboard shows real-time metrics. This is enforced by the 0.5s throttle in `_emit_progress` and `add_done_callback`/`asyncio.as_completed` patterns in all patterns. CI/headless mode (no WebSocket subscriber) is exempt. When adding a new pattern or modifying an existing one, confirm it emits progress continuously — raise this during planning if the pattern's structure makes that non-trivial.

## Conventions

- **Type hints** on all function signatures
- **Dataclasses** for data models (not Pydantic for internal models; Pydantic only for FastAPI request/response schemas)
- **async/await** for all HTTP and I/O operations
- **No comments** unless the "why" is non-obvious
- Import order: stdlib, then third-party, then local (PEP 8)
- Use `from __future__ import annotations` in all files

## Git

- Never use Co-Authored-By in commit messages
- Use the repo owner's git credentials (already configured)
- Write clear, concise commit messages describing what changed and why
- Commit after every change

## Async & Concurrency Discipline

- All I/O-bound operations (HTTP requests, file reads during test runs, WebSocket) must use `async/await`. Never block the event loop with synchronous I/O.
- Use `asyncio.Semaphore` to control concurrency — never create unbounded numbers of tasks.
- Use `asyncio.Event` for cancellation signals — patterns must check the cancel event and stop gracefully.
- Never mix `threading` with `asyncio` unless there is no async alternative. If threads are necessary, use `asyncio.to_thread()` to bridge.
- All shared state accessed from multiple coroutines must be protected or designed to be safe (e.g., append-only lists, asyncio.Queue).
- Connection pools (httpx.AsyncClient) must be properly opened and closed using async context managers.

## Logging

- Use Python's `logging` module with `logger = logging.getLogger(__name__)` in every module.
- Log levels: `DEBUG` for detailed execution flow (request/response details, timing), `INFO` for high-level progress, `WARNING` for recoverable issues, `ERROR` for failures.
- When the user enables debug mode (`--debug` flag or `OVERLOAD_DEBUG=1`), set root logger to `DEBUG`.
- Default log level is `WARNING` for clean output.
- Never use `print()` for diagnostic output — always use the logger. `print()` is only for CLI user-facing progress output.

## Key Patterns

- **Load patterns** implement `LoadPattern` protocol with `async execute()` method
- **EventBus** decouples engine from transport (WebSocket, CLI print)
- **Collection parser** flattens nested Postman items, handles auth inheritance
- **Variable substitution** uses `{{var}}` regex with scoped resolution

## Commands

```bash
# Development
pip install -e ".[dev]"          # Install with dev deps
python -m overload               # Run via module
pytest tests/                    # Run tests
pytest tests/ -x                 # Stop on first failure

# Package
python -m build                  # Build package
pip install dist/*.whl           # Install built package
```

## Test Types

Load, Stress, Spike, Soak, Ramp, Burst, Breakpoint, Custom (step-based), Rate Limit, Sequential Runner.

## Dependencies

Runtime: fastapi, uvicorn, httpx, jinja2, python-multipart
Dev: pytest, pytest-asyncio

## Contributing

### Setup

```bash
git clone https://github.com/dprakash2101/overload
cd overload
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### Before submitting a PR

1. **Run the full test suite** — all tests must pass:
   ```bash
   pytest tests/
   ```
2. **Add tests** for any new behaviour. The test suite covers every module; new code should not lower coverage.
3. **Follow the conventions** in this file — type hints, dataclasses, async/await, PEP 8, no unnecessary comments.
4. **Keep PRs focused.** One feature or fix per PR. If you are refactoring and adding a feature, split them.

### Areas open for contribution

- **New load patterns** — implement the `LoadPattern` protocol in [src/overload/engine/load_patterns.py](src/overload/engine/load_patterns.py)
- **Additional auth types** — extend `_apply_auth` in [src/overload/engine/http_client.py](src/overload/engine/http_client.py)
- **Report improvements** — HTML/CSS/JS lives in [src/overload/report/templates/](src/overload/report/templates/)
- **Browser UI features** — vanilla JS in [src/overload/web/static/js/](src/overload/web/static/js/)
- **Collection format support** — parser in [src/overload/collection/parser.py](src/overload/collection/parser.py)

### Submitting

- Fork the repo, create a branch off `main`, open a PR against `main`.
- Write a clear PR description: what changed, why, and how to test it.
- Do not open PRs for cosmetic-only changes (whitespace, renaming for style preference).
