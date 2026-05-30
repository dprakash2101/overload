# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.1.0]: https://github.com/dprakash2101/overload/releases/tag/v0.1.0
