# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.3.2] — 2026-06-14

### Added

**In-app docs linked to GitHub Pages**
- The browser UI Docs tab now links to the published GitHub Pages documentation site at `https://dprakash2101.github.io/overload/`.
- A "Full documentation" link is shown in the Docs page header, and each topic (Getting Started, Patterns, Auth, etc.) has a "Read full documentation" link at the bottom pointing to the corresponding page.

**Configurable Phase 2 multiplier for rate limit tests**
- New `rate_limit_exceed_multiplier` config field (default: 2) controls how many times the stated cap to send in Phase 2 of the rate limit test. Supports 2×–10×.
- **Browser UI:** New "Phase 2 multiplier" slider in the ratelimit pattern config panel.
- **CLI:** New `--exceed-multiplier` flag (e.g., `overload run --pattern ratelimit --rps 60 --exceed-multiplier 3`).
- **MCP server:** New `rate_limit_exceed_multiplier` parameter on `run_load_test`.
- **Config file:** Supports `rate_limit_exceed_multiplier` key in `overload.config.yaml`.
- Removed hardcoded `_EXCEED_MULTIPLIER = 2` constant from the rate limiter engine.

### Tests

- 4 new tests in `tests/test_rate_limiter.py` covering custom multiplier values for phase RPM, labels, and result counts.
- 261 tests total, all passing.

---

## [0.3.1] — 2026-06-09

### Security

**GitHub Actions — Script injection in publish.yml**
- All `${{ inputs.version }}` interpolations in `run:` shell blocks have been replaced with safe environment variable bindings (`INPUT_VERSION`). Previously, a crafted `workflow_dispatch` version input could inject arbitrary shell commands into the CI runner.
- A new `validate-version` job gates all downstream jobs and rejects version inputs that don't match a semver pattern (`^[0-9]+\.[0-9]+\.[0-9]+...`).

**API — Path traversal in load-local endpoints**
- `/api/collection/load-local`, `/api/environment/load-local`, and `/api/data/load-local` now reject any path that resolves (via `os.path.realpath()`) outside the configured working directory. This covers symlink-based escapes.
- Error responses from these endpoints no longer expose raw exception messages.

### Tests

- 5 new security tests in `tests/test_api.py` — path traversal blocked for collection, environment, and CSV endpoints; symlink escape rejected; parse errors do not leak filesystem paths.
- 254 tests total, all passing.

---

## [0.3.0] — 2026-06-09

### Added

**Per-run report folders and response saving**
- Each run now writes to its own folder: `reports/run_<run_id>/` containing `report.html`, `meta.json` (history sidecar), and — when `save_responses=True` — `responses.json` with all captured response bodies.
- `responses.json` is kept separate from the HTML report so the report stays lean. Response bodies are no longer embedded in the report payload.
- New `GET /api/runs/{id}/responses` endpoint — downloads `responses.json` as `responses_{id}.json`.
- Results page shows a **Responses** download link next to HTML Report when bodies were captured.
- CLI prints the responses path after a run when bodies were saved.
- `load_run_history()` scans both the new `run_*/meta.json` layout and legacy flat `*_meta.json` sidecars.

**Robust cancellation — partial reports always generated**
- Fixed: stopping a test (graceful or hard-cancel via watchdog) now always produces a partial HTML report from whatever data was collected. Previously, a hard `task.cancel()` could discard all results.
- `HttpClient` now accumulates every completed result into a `result_sink` owned by the service, so partial results survive even an `asyncio.CancelledError` propagating all the way up.
- Both `status="stopped"` paths (cooperative cancel and watchdog hard-cancel) generate a report when `stats.total > 0`.

**Request selection checkboxes (browser UI)**
- Per-request checkboxes in the collection tree on the Collection page.
- Folder checkboxes with indeterminate-state for partial folder selection.
- Select All / Select None buttons with a live "N of M selected" counter.
- If nothing is explicitly selected, the entire collection runs (no breaking change).
- `selected_requests` is validated server-side; an explicitly empty array returns HTTP 400.



**CSV data-driven testing**
- New `--data PATH` flag on `overload run` and `overload sequential` — feed a CSV file and each row's column values fill `{{placeholders}}` in URLs, headers, body, and auth fields automatically.
- `DataSource` class (`overload.collection.data_source`) — accepts a file path or file-like object, strips UTF-8 BOM, round-robins rows (`index % len(rows)`) across concurrent requests.
- `VariableContext.derive(extra)` — prepends a CSV-row scope at the top of the existing scope chain (CSV row > runtime > environment > collection) without mutating the base context; safe for concurrent use.
- `HttpClient` accepts `data_source: DataSource | None = None`; when `None` behaviour is identical to before (no breaking change).
- Browser UI — "Data file (CSV)" drop-zone card on the Collection page (shown after a collection is loaded). Drag-and-drop or file-picker upload; shows row count, column names, matched `{{placeholders}}` (green ✓), and unmatched placeholders (amber warning). Remove button clears the attached source.
- New API endpoints: `POST /api/data/upload`, `POST /api/data/load-local`, `POST /api/data/clear`, `GET /api/data/status`.
- `GET /api/detect` response now includes a `csv_files` array listing CSV files in the working directory.
- 13 new tests in `tests/test_data_source.py`.

**Request selection**
- Cherry-pick a subset of requests before running: per-request checkboxes in the collection tree, Select All / Select None buttons, and a live "N of M selected" counter.
- Folder checkboxes with indeterminate-state support for partial folder selection.
- `POST /api/test/start` returns HTTP 400 (`"No requests selected"`) when `selected_requests` is an explicitly empty array.
- Live dashboard title shows "N of M requests" when a subset is active.

**Report on Stop**
- Stopping a test mid-run now generates a partial report instead of discarding all data.
- `POST /api/test/stop` uses cooperative cancellation: sets a cancel event and gives the pattern a 10-second grace window to return partial results. The watchdog hard-cancels only if the task is still running after the grace window.
- Runs stopped early are recorded with status `"stopped"` (distinct from `"complete"`). The Results table and report viewer show action buttons for both statuses.

**In-app documentation**
- New "Docs" tab in the browser UI — two-pane layout with a topic sidebar and content pane; all navigation is client-side with no page reload.
- 8 topics: Getting Started, Collections & Variables, CSV Data Files, Authentication, Test Patterns, Assertions, CI/CD, Reports.
- `overload` startup banner now links to the Docs tab and the GitHub Pages site.

**Beginner-friendly live dashboard**
- `?` tooltip chips on all 6 live KPI labels (Total, Success, Avg Latency, Current RPS, Elapsed, Errors).
- "Beginner mode" toggle button in the live dashboard header. When ON, shows a concise plain-English sub-label under each KPI value. State is persisted in `localStorage`.
- `friendlyPhase()` function maps every pattern phase string (ramp-up, holding, spike, probing, cooldown, etc.) to a plain-English sentence shown below the progress bar throughout the run.

### Changed

- `POST /api/test/stop` behaviour: cooperative cancellation with 10-second grace window (previously immediate `task.cancel()`).
- `GET /api/detect` response: now includes `csv_files` array alongside existing `collections` and `environments`.

**MCP server (Claude Code, Codex CLI, GitHub Copilot)**
- New `overload mcp` subcommand — starts a stdio MCP server exposing Overload as tools for any MCP client.
- Install: `pip install "overload-cli[mcp]"` (FastMCP is an optional extra; core install stays lean).
- Six MCP tools: `list_patterns`, `describe_collection`, `run_load_test`, `get_run_status`, `get_run_results`, `stop_run`.
- `run_load_test` returns a `run_id` immediately (non-blocking); poll `get_run_status` while running, then fetch results via `get_run_results`. Guardrails: concurrency capped at 200, total requests at 10,000.
- Register with Claude Code: `claude mcp add overload -- overload mcp`
- Register with Codex CLI: `codex mcp add overload -- overload mcp`
- Register with GitHub Copilot (VS Code): add `"overload": {"command": "overload", "args": ["mcp"]}` under `"mcpServers"` in VS Code settings.
- New `src/overload/engine/service.py` — shared run orchestration used by both the web API and the MCP server; no duplicated logic.
- 18 new tests in `tests/test_mcp_server.py`.

### Tests

- 218 tests total, all passing (up from 182).
- 13 new tests in `tests/test_data_source.py` covering `DataSource`, `VariableContext.derive`, and `HttpClient` CSV cycling.
- 5 new tests in `tests/test_api.py` covering request selection validation and stop-generates-report paths.
- 18 new tests in `tests/test_mcp_server.py` covering all 6 MCP tools and the shared `engine/service.py` orchestration.

---

## [0.2.1] — 2026-06-06

### Fixed

**Live dashboard — real-time updates for all 10 test types**
- All patterns now emit progress at least every ~0.5 s via a time-based throttle in `_emit_progress`. Previously, batch-gather patterns (Ramp, Stress) blocked up to 30 s between updates.
- `RampPattern`, `StressPattern`, `SpikePattern`, `SoakPattern`, `CustomPattern`, and `LoadTestPattern` switched from `asyncio.gather` to `add_done_callback` + `asyncio.as_completed`, so completed-request counts and status codes update as each HTTP response arrives instead of at the end of a whole step or phase.
- `BreakpointPattern` — the internal `_probe()` coroutine previously used `asyncio.gather` and blocked silently for the full 5-second probe window (RPS × 5 s). It now uses `add_done_callback` + `asyncio.as_completed` so results accumulate and progress emits throughout each binary-search probe.
- Client-side elapsed timer (`setInterval 1 s`) now ticks independently so the elapsed counter never freezes between WebSocket messages. It syncs to the authoritative server value on each update.
- Status-code doughnut chart uses incremental `chart.update()` instead of destroy + recreate, eliminating jank during rapid updates.

**Rate limit test — 50–60 s delay before showing any info**
- `_run_phase` previously emitted no progress during the 60-second task-dispatch loop. It now emits a progress update per request dispatched (throttled to 0.5 s) showing a `sent N/M` counter.
- Cooldown period now emits a countdown tick every second (`Cooldown: Ns remaining`) instead of 15 s of silence.
- `total_requests` in every progress message is now the full cumulative total (`cap + 2×cap`) so the progress bar never resets to 0% when Phase 2 starts.
- Status codes and error count are tracked and sent with every progress update, including the final `complete` message.

### Added

- `_safe_done_callback` helper used by all patterns to safely append task results without swallowing exceptions.
- `tests/test_load_patterns.py` — 27 new tests covering throttle behaviour, `_safe_done_callback`, and per-pattern liveness for all 8 engine patterns (Burst, Ramp, Load, Stress, Spike, Soak, Breakpoint, Custom).
- Additional tests in `test_rate_limiter.py` for live progress emission, cumulative total_requests, status code tracking, cooldown countdown, and no-callback safety.
- 177 tests total, all passing.

---

## [0.2.0] — 2026-06-02

### Changed

**Rate Limit pattern — complete redesign**
- Unit is now **req/min** (not req/s) — matches how rate limits are documented in API specs and gateways
- Old design: burst + ramp (DDoS-style threshold hunt). New design: 2-phase validation with a clear verdict
  - **Phase 1** — sends exactly `rate_limit_cap` req/min for 60 s (at the stated limit)
  - **Cooldown** — waits 15 s for the rate-limiter's sliding window to reset
  - **Phase 2** — sends `2 × rate_limit_cap` req/min for 60 s (deliberately exceeds the limit)
- **Verdict** — one of three outcomes:
  - `working` — no 429s in Phase 1, 429s observed in Phase 2 (expected)
  - `not_working` — no 429s in either phase (rate limiter is not enforcing)
  - `too_strict` — 429s appeared during Phase 1 (limit is tighter than configured)
- Removed `rate_limit_requests` config field; only `rate_limit_cap` (req/min) remains
- Live browser dashboard shows the active phase label and description during the test
- HTML report section renamed to "Rate Limit Validation" with a phase-summary bar chart and verdict banner

### Added

- 26 unit tests for the new rate limit engine (`tests/test_rate_limiter.py`)
  - `_phase_stats` edge cases, `_run_phase` mechanics, verdict paths, progress callbacks, cancellation

---

## [0.1.0] — 2026-05-30

First public release.

### Added

**Core engine**
- Async HTTP engine built on `httpx` with connection pooling and configurable concurrency
- 10 load test patterns: Burst, Load, Stress, Spike, Soak, Ramp, Breakpoint, Custom (stage-based), Rate Limit, Sequential
- Postman Collection v2.1 parser — nested folders, auth inheritance, variable substitution, all body types (raw, form-data, urlencoded, GraphQL)

**Authentication**
- Bearer token auth
- HTTP Basic auth
- API key auth — header and query string placement
- OAuth2 client-credentials flow — pre-run token acquisition with in-process caching and `expires_in` respect

**Variable system**
- Three-scope variable resolution: runtime (`--var`) > environment file > collection variables
- Dynamic variables: `{{$guid}}`, `{{$timestamp}}`, `{{$randomInt}}`, `{{$randomBoolean}}`, `{{$randomEmail}}`
- Recursive resolution (a variable whose value references another variable)

**CI/CD assertions**
- `--assert "p95_latency_ms<500"` inline threshold expressions (repeatable)
- Exit code 1 on assertion failure — the primitive every CI system reads
- JUnit XML output via `--junit report.xml` — native test results in GitHub Actions, GitLab, Jenkins
- Colored terminal verdict table with per-assertion ✓/✗ rows
- YAML config file (`overload.config.yaml`) for storing test configuration and thresholds in source control
- `--config` flag to load the YAML config; CLI flags override file values

**Browser UI**
- FastAPI + Vanilla JS SPA — no build step, no Node.js required
- Auto-detects Postman collections and environment files in the working directory
- Live progress dashboard with Chart.js charts (RPS, latency, error rate)
- Assertions editor with metric/operator/value rows
- Save Config / Load Config — writes/reads `overload.config.yaml`
- PASS/FAIL verdict banner with per-assertion breakdown
- Past runs table with verdict badge
- HTML report viewer

**Reports**
- HTML report with embedded Chart.js charts and verdict section
- JSON export
- CSV export (one row per request)
- Reports written to `reports/` subdirectory

**CLI**
- `overload` — starts browser UI on port 3000
- `overload run` — headless CLI mode with full flag surface
- `overload sequential` — sequential runner for functional flows
- `--open-report` — opens HTML report in browser after run

**Supported metrics for assertions**
`p50_latency_ms`, `p95_latency_ms`, `p99_latency_ms`, `max_latency_ms`, `mean_latency_ms`,
`error_rate_pct`, `success_rate_pct`, `avg_rps`, `total_requests`, `rate_limited_count`

**Test suite**
- 124 unit tests across all layers (assertions, auth, collection parser, variables, HTTP client, models, report, API)
- GitHub Actions CI matrix: Python 3.10 · 3.11 · 3.12 · 3.13

[0.3.2]: https://github.com/dprakash2101/overload/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/dprakash2101/overload/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/dprakash2101/overload/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/dprakash2101/overload/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/dprakash2101/overload/compare/v0.1.1...v0.2.0
[0.1.0]: https://github.com/dprakash2101/overload/releases/tag/v0.1.0
