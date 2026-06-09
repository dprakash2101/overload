# Contributing to Overload

Thank you for your interest in improving Overload. This guide covers the local setup, development expectations, and pull request checklist for contributors.

## Development Setup

Clone the repository and install Overload in editable mode with development dependencies:

```bash
git clone https://github.com/dprakash2101/overload
cd overload
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Run the browser UI locally:

```bash
overload
```

Run a CLI test:

```bash
overload run --collection path/to/collection.json --pattern burst
```

## Running Tests

Before submitting a pull request, run the full test suite:

```bash
pytest tests/
```

To stop on the first failure while developing:

```bash
pytest tests/ -x
```

## Development Principles

- Build complete, production-quality changes. Do not leave TODOs, placeholders, or partial implementations.
- Understand the problem before coding. Avoid copying patterns without checking whether they fit this codebase.
- Keep changes focused. One feature or fix per pull request is easier to review and maintain.
- Follow PEP 8 style guidelines.
- Add type hints to all function signatures.
- Use `from __future__ import annotations` in new Python files.
- Use dataclasses for internal models. Use Pydantic only at the FastAPI boundary.
- Use `async` and `await` for I/O-bound work.
- Do not block the event loop with synchronous I/O during test runs, HTTP requests, WebSocket handling, or other async flows.
- Use the `logging` module for diagnostics. Use `print()` only for user-facing CLI output.

## Project Structure

```text
src/overload/
  collection/      Postman collection parsing, variables, environments
  engine/          Load patterns, runner, HTTP client, rate limiting
  report/          HTML, JSON, and CSV report generation
  web/             FastAPI browser UI and vanilla JavaScript frontend
  utils/           Shared utility helpers
  cli.py           CLI entry point
tests/             Pytest suite and fixtures
docs/              Static documentation site
```

## Pull Request Checklist

Before opening a pull request:

1. Create a branch from `main`.
2. Keep the change focused on a single feature, bug fix, or documentation improvement.
3. Add or update tests for new behavior.
4. Run `pytest tests/` and confirm the full suite passes.
5. Update documentation when user-facing behavior changes.
6. Write a clear commit message describing what changed and why.
7. Open a pull request against `main`.

Do not include `Co-authored-by` trailers in commit messages.

## Useful Commands

```bash
pip install -e ".[dev]"
python -m overload
pytest tests/
pytest tests/ -x
python -m build
```

## Release Package

Overload is published on PyPI as `overload-cli`, and the installed command is `overload`.
