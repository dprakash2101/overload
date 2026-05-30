# Overload — Project Guide

## What is this?

Overload is a free, open-source load testing tool that reads Postman collections and provides a browser-based UI. Published as `overload-cli` on PyPI, command is `overload`.

## Quick Start

```bash
pip install -e ".[dev]"   # Install in dev mode
overload                   # Opens browser UI on port 3000
overload run --collection path/to/collection.json --pattern burst  # CLI mode
```

## Project Structure

```
src/overload/           # Main package (src layout)
  collection/           # Postman collection parsing (parser, models, variables, environment)
  engine/               # Test execution (http_client, load_patterns, runner, rate_limiter, events)
  report/               # HTML report generation + CSV/JSON export
    templates/           # Jinja2 templates, CSS, JS for reports
  web/                  # FastAPI browser UI
    routes/             # API endpoints + WebSocket
    static/css/         # UI stylesheets
    static/js/          # Vanilla JS frontend (app, collection, runner, charts)
    templates/          # index.html SPA shell
  utils/                # Naming, timestamps
  cli.py                # CLI entry point
tests/                  # Unit tests (pytest)
  fixtures/             # Sample Postman collections for tests
old/                    # Original main.py kept for reference
```

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
