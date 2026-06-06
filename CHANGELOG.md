# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.2.0]: https://github.com/dprakash2101/overload/compare/v0.1.1...v0.2.0
[0.1.0]: https://github.com/dprakash2101/overload/releases/tag/v0.1.0
