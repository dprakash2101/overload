# Overload — Project Guide

## What is this?

Overload is a free, open-source load testing tool that reads Postman collections and provides a browser-based UI. Published as `overload-cli` on PyPI, command is `overload`.

## Quick Start

```bash
pip install -e ".[dev]"   # Install in dev mode
overload                   # Opens browser UI on port 3000
overload run --collection path/to/collection.json --pattern burst  # CLI mode
overload mcp               # Start MCP server (requires mcp extra)
```

## Project Structure

```
src/overload/                  # Main package (src layout)
  collection/                  # Postman collection parsing
    data_source.py             # CSV data-driven testing (DataSource, VariableContext.derive)
    environment.py             # Postman environment file parsing
    models.py                  # ParsedCollection, ParsedRequest, AuthConfig, etc.
    parser.py                  # Collection JSON → ParsedCollection
    variables.py               # VariableContext — scope-chain variable resolution + discover_placeholders
  engine/                      # Test execution
    assertions.py              # Threshold expressions + JUnit XML generation
    auth.py                    # OAuth2 pre-run token acquisition
    events.py                  # EventBus — decouples engine from transports
    http_client.py             # Async httpx wrapper; CSV row cycling; result_sink for cancel safety
    load_patterns.py           # All load patterns (Burst, Load, Stress, Spike, Soak, Ramp, Breakpoint, Custom)
    models.py                  # PatternConfig, Stats, RunProgress, RequestResult, Threshold, etc.
    rate_limiter.py            # Rate-limit validation pattern (2-phase)
    runner.py                  # Sequential runner
    service.py                 # Shared run orchestration used by web API and MCP server
  mcp_server.py                # MCP server (stdio) — all MCP tool logic lives here
  report/                      # Report generation + export
    generator.py               # HTML report writer → reports/run_<id>/report.html
    responses.py               # responses.json writer (save_responses=True)
    exporters.py               # JSON and CSV export
    templates/                 # Jinja2 templates, CSS, JS for reports
  web/                         # FastAPI browser UI
    app.py                     # FastAPI app factory + startup
    routes/
      api.py                   # REST API endpoints (delegates run execution to engine/service.py)
      ws.py                    # WebSocket broadcast
    static/css/                # UI stylesheets
    static/js/                 # Vanilla JS frontend (app, collection, runner, charts, docs)
    templates/                 # index.html SPA shell
  config_file.py               # overload.config.yaml read/write
  utils/
    naming.py                  # generate_run_id, make_run_dir, stamped_filename
  cli.py                       # CLI entry point (overload, overload run, overload sequential, overload mcp)
tests/                         # Unit tests (pytest)
  fixtures/                    # Sample Postman collections for tests
  test_api.py
  test_assertions.py
  test_auth.py
  test_collection_parser.py
  test_config_file.py
  test_data_source.py
  test_http_client.py
  test_load_patterns.py
  test_mcp_server.py
  test_models.py
  test_rate_limiter.py
  test_report.py
  test_responses.py            # Tests for report/responses.py (responses.json writing)
  test_service.py              # Tests for engine/service.py (run folder layout, cancellation)
  test_variables.py
docs/                          # GitHub Pages documentation site
  index.html                   # Feature overview + quick start
  getting-started.html
  cli-reference.html
  test-patterns.html
  assertions.html
  authentication.html
  collections.html
  configuration.html
  reports.html
  browser-ui.html
  ci-cd.html
  architecture.html
  contributing.html
  changelog.html
  styles.css
```

## Run Output Layout

Each run writes to its own folder:

```
reports/
  run_20260609_153021_abc123/
    report.html       # Full HTML report (no embedded response bodies)
    meta.json         # Sidecar — persisted across restarts for history
    responses.json    # Only present when save_responses=True
```

`load_run_history()` scans both `run_*/meta.json` (new) and legacy `*_meta.json` flat sidecars.

## File Naming Convention

**Feature code must live in files whose name reflects the feature.** This makes debugging
and navigation fast — you always know exactly which file to open.

| Feature / domain | File prefix / name |
|------------------|--------------------|
| MCP server tools | `mcp_server.py` |
| Rate-limit logic | `rate_limiter.py` |
| Load patterns    | `load_patterns.py` (single file; new pattern families get `load_*.py`) |
| Auth flows       | `auth.py` |
| Data / CSV       | `data_source.py` |
| Report output    | `report/generator.py`, `report/responses.py`, `report/exporters.py` |
| Response saving  | `report/responses.py` |
| Run orchestration | `engine/service.py` |

The general rule: **if a file is hard to find by name alone, rename it**. Never lump
unrelated features into a generic `utils.py` or `helpers.py`.

Test files follow the same pattern: `test_rate_limiter.py` tests `rate_limiter.py`,
`test_service.py` tests `engine/service.py`, etc.

## Tech Stack

- **Python 3.10+**, asyncio for concurrency
- **FastAPI + Uvicorn** — web server, WebSocket
- **httpx** — async HTTP client
- **Jinja2** — report templates
- **Vanilla JS + Chart.js** — frontend (no build step)
- **FastMCP** — MCP server (optional extra: `pip install "overload-cli[mcp]"`)
- **pyyaml** — config file read/write
- **pytest** — testing

## All Features

### Test Patterns (10 total)
| Pattern | CLI flag | Description |
|---------|----------|-------------|
| Burst | `--pattern burst` | Fire N requests simultaneously |
| Load | `--pattern load` | Ramp → hold → ramp down |
| Stress | `--pattern stress` | Step up RPS until errors exceed threshold |
| Spike | `--pattern spike` | Baseline → spike → recovery |
| Soak | `--pattern soak` | Steady RPS over long duration |
| Ramp | `--pattern ramp` | Linear RPS increase |
| Breakpoint | `--pattern breakpoint` | Binary search for degradation point |
| Custom | `--pattern custom` | User-defined JSON stages |
| Rate Limit | `--pattern ratelimit` | 2-phase rate limiter validation |
| Sequential | `overload sequential` | Ordered functional flow testing |

### Auth Types (4 total, inherited through collection folders)
- **Bearer token** — `Authorization: Bearer <token>`
- **Basic auth** — base64-encoded username:password
- **API key** — header or query-string placement
- **OAuth2 client credentials** — pre-run token acquisition, cached in-process

### Variable System
- Three-scope chain: runtime (`--var`) > environment file > collection variables
- CSV row scope prepended dynamically per-request via `VariableContext.derive()`
- Dynamic variables: `{{$guid}}`, `{{$timestamp}}`, `{{$randomInt}}`, `{{$randomBoolean}}`, `{{$randomEmail}}`
- `discover_placeholders(collection)` → scans all fields to show matched/unmatched CSV columns in CLI banner

### CSV Data-Driven Testing
- `--data PATH` on `overload run` and `overload sequential`
- Drag-and-drop CSV in browser UI; shows matched/unmatched placeholders live
- Round-robin row cycling across concurrent requests (row `i % len(rows)`)
- `POST /api/data/upload`, `/api/data/load-local`, `/api/data/clear`, `/api/data/status`

### Request Selection (Browser UI)
- Per-request checkboxes in the collection tree on the Collection page
- Folder checkboxes with indeterminate-state for partial folder selection
- Select All / Select None buttons + "N of M selected" counter
- If nothing selected: entire collection runs
- API validates indices; `selected_requests=[]` returns HTTP 400

### CI/CD Assertions
- `--assert "METRIC OP VALUE"` — repeatable threshold expressions
- Supported metrics: `p50_latency_ms`, `p95_latency_ms`, `p99_latency_ms`, `max_latency_ms`, `mean_latency_ms`, `error_rate_pct`, `success_rate_pct`, `avg_rps`, `total_requests`, `rate_limited_count`
- Operators: `<`, `<=`, `>`, `>=`, `==`
- Exit code 1 on failure (CI-friendly)
- `--junit PATH` for JUnit XML (GitHub Actions, Jenkins, GitLab)
- YAML config: `overload.config.yaml` via `--config PATH`

### Reports
- **HTML** — `reports/run_<id>/report.html` — charts, latency stats, timeline, request log
- **responses.json** — `reports/run_<id>/responses.json` — captured bodies when `save_responses=True`
- **meta.json** — `reports/run_<id>/meta.json` — sidecar for run history persistence
- **JSON export** — via CLI `--format json` or `GET /api/runs/{id}/export/json`
- **CSV export** — via CLI `--format csv` or `GET /api/runs/{id}/export/csv`
- `GET /api/runs/{id}/responses` — download responses.json from browser UI (shown as "Responses" button in Results table when captured)

### Cancellation / Partial Reports
- Graceful stop: `cancel_event.set()` → 10-second grace → watchdog hard-cancels
- Both paths generate a partial report from whatever was collected
- `HttpClient` keeps a `result_sink` so results survive even a hard `task.cancel()`
- Status = `"stopped"` (not `"error"`) — shows action buttons in Results table

### Run History Persistence
- `load_run_history(reports_dir)` scans on `/api/runs` to restore previous runs
- New layout: `run_*/meta.json`; legacy `*_meta.json` flat files also read

### MCP Server
- `overload mcp` — stdio MCP server for Claude Code, Codex CLI, GitHub Copilot
- 6 tools: `list_patterns`, `describe_collection`, `run_load_test`, `get_run_status`, `get_run_results`, `stop_run`
- Non-blocking: `run_load_test` returns `run_id` immediately; poll `get_run_status`
- Guardrails: concurrency ≤ 200, total requests ≤ 10,000

### Browser UI Features
- Auto-detect Postman JSON + CSV files in working directory
- Live dashboard: Chart.js charts (RPS, latency, errors), phase label, `friendlyPhase()` descriptions
- Beginner mode toggle — plain-English sub-labels under KPI cards (persisted in localStorage)
- `?` tooltip chips on all 6 KPI labels
- Assertions editor with metric/operator/value rows
- Save Config / Load Config — writes/reads `overload.config.yaml`
- PASS/FAIL verdict banner with per-assertion breakdown
- In-app Docs tab — 8 topics, client-side navigation, no page reload
- Results table with HTML Report + Responses download links + Details expand panel

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
- `HttpClient` keeps a `result_sink: list[RequestResult]` that is populated on every completed request so the service can recover partial results after a hard task cancellation.

## Logging

- Use Python's `logging` module with `logger = logging.getLogger(__name__)` in every module.
- Log levels: `DEBUG` for detailed execution flow (request/response details, timing), `INFO` for high-level progress, `WARNING` for recoverable issues, `ERROR` for failures.
- When the user enables debug mode (`--debug` flag or `OVERLOAD_DEBUG=1`), set root logger to `DEBUG`.
- Default log level is `WARNING` for clean output.
- Never use `print()` for diagnostic output — always use the logger. `print()` is only for CLI user-facing progress output.

## Key Patterns

- **Load patterns** implement `LoadPattern` protocol with `async execute()` method
- **EventBus** (`engine/events.py`) decouples engine from transport (WebSocket, CLI print)
- **Collection parser** flattens nested Postman items, handles auth inheritance
- **Variable substitution** uses `{{var}}` regex with scoped resolution
- **result_sink** in `HttpClient` — every `execute()` call appends to the sink so `service.py` has partial results even on hard cancel
- **Run folder** — `make_run_dir(base, run_id)` creates `{base}/run_{run_id}/`; `generator.py` writes `report.html` and `responses.py` writes `responses.json` into it

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

## Dependencies

Runtime: `fastapi`, `uvicorn`, `httpx`, `jinja2`, `python-multipart`, `pyyaml`
Optional: `fastmcp` (for `overload mcp`)
Dev: `pytest`, `pytest-asyncio`

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
