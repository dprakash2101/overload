# Overload — Next Release Enhancement Plan

> **Status:** Planning only — no code written yet. This document is the full
> implementation spec for the next major release so any developer can pick up the
> work without missing context.
>
> **Author of plan:** drafted 2026-06-02 via codebase review.
> **Build order recommendation:** see [Sequencing](#suggested-sequencing).

---

## Table of contents
1. [Context & goals](#context)
2. [Confirmed product decisions](#decisions)
3. [Feature 1 — CSV data-driven testing](#feature-1)
4. [Feature 2 — Choose which requests to run](#feature-2)
5. [Feature 3 — In-app documentation/help](#feature-3)
6. [Feature 4 — Report from partial data on Stop](#feature-4)
7. [Feature 5 — Beginner-friendly live status](#feature-5)
8. [Feature 6 — MCP server for Claude Code](#feature-6)
9. [Strategic direction — hosted/server mode for internal APIs](#strategic)
10. [Suggested sequencing](#suggested-sequencing)
11. [Verification](#verification)
12. [Key architecture notes for implementers](#architecture-notes)

---

<a name="context"></a>
## 1. Context & goals

Five enhancements requested for the next major Overload release:

1. **CSV data-driven testing** — placeholders in a Postman collection are filled
   from a CSV file, so one collection drives many distinct requests. Auth must
   work whether values live in the collection (e.g. OAuth) or come from the CSV
   (body / query / headers / tokens).
2. **Request selection** — after uploading a collection, show all requests and let
   the user pick which ones to run.
3. **In-app documentation** — a help/docs area inside the running UI; links open
   **in the same page** (content swaps client-side), never a new tab. Also point
   users to it when the CLI starts.
4. **Report on Stop** — today, clicking Stop shows "cancelled" with no report.
   Generate a report from whatever valid data was collected up to that point.
5. **Beginner-friendly live status** — make the live dashboard understandable to
   users who aren't performance-testing experts.

---

<a name="decisions"></a>
## 2. Confirmed product decisions

These were agreed up front and drive the designs below.

| Topic | Decision | Rationale |
|-------|----------|-----------|
| **CSV → placeholder mapping** | **Auto by header name.** A CSV column `email` fills `{{email}}` everywhere. No mapping UI in v1. | Zero-config, "upload and go." Explicit mapping can be added later if users need to reconcile mismatched names. |
| **Row iteration** | **Cycle / round-robin.** Request *N* uses row *N mod rowcount*; wraps around. | Every request gets data; load volume stays whatever the pattern dictates. Best fit for load testing (vs. capping requests at row count). |
| **Auth model** | **Unified precedence.** Auth values are ordinary variables resolved through one chain: **CSV row > `--var`/runtime > environment > collection.** No auth-type-specific CSV code. | Basic/Bearer/API-key already resolve through `VariableContext`, so a CSV-row scope on top makes "CSV if present, else env/collection" fall out automatically. |
| **OAuth2** | **Resolve once per run** from the layered context (so `token_url`/`client_id`/`client_secret` may come from CSV-as-single-value, env, or collection). **Per-row OAuth is OUT of scope for v1**, surfaced in the UI as "not currently supported." | OAuth is fetched once before the run (`prepare_collection_auth`); a different client per row would mean a token fetch per row — heavy, niche. Defer until there's demand. |

### Why the auth concern is simpler than it looks (important context)
Auth fields are **already** resolved as variables. In
`src/overload/engine/http_client.py` `_apply_auth` (lines ~179-198):

- Bearer: `token = ctx.resolve(auth.params.get("token", ""))`
- Basic: `username = ctx.resolve(...)`, `password = ctx.resolve(...)`
- API key: `key = ctx.resolve(...)`, `value = ctx.resolve(...)`

So if we add a **CSV-row scope at the top of the existing precedence chain**, any
auth value written as a `{{placeholder}}` is filled by "CSV if present, else env,
else collection" — with **no auth-type-specific code**. The user's three cases
(basic-from-CSV, token-in-collection-or-placeholder, key-anywhere) all collapse to
one mechanism. OAuth2 is the single exception because it is fetched once
(`prepare_collection_auth` uses the **base** context), so it stays a per-run value.

---

<a name="feature-1"></a>
## 3. Feature 1 — CSV data-driven testing (placeholders fed from CSV)

### 3.1 Goal
Attach a CSV; each request fills its `{{placeholders}}` from a CSV row
(round-robin) across URL, headers, body, query params, and auth — via one unified
variable mechanism.

### 3.2 Design

**A. New `DataSource` — `src/overload/collection/data_source.py`**
- `from_csv(path_or_file) -> DataSource` using stdlib `csv.DictReader`.
- Holds `rows: list[dict[str, str]]` and `columns: list[str]`.
- `row_for(index: int) -> dict[str, str]` → `rows[index % len(rows)]`
  (round-robin); empty dict if no rows.
- Type hints on all signatures; `from __future__ import annotations`; dataclass or
  plain class per existing style.

**B. `VariableContext.derive()` — `src/overload/collection/variables.py`**
- Current scopes (lines 33-37): `[runtime, environment, collection]`.
- Add:
  ```python
  def derive(self, extra: dict[str, str]) -> "VariableContext":
      new = VariableContext.__new__(VariableContext)
      new._scopes = [extra, *self._scopes]
      new._unresolved = self._unresolved  # share aggregate set
      return new
  ```
- Result precedence (highest first): **CSV row > runtime > environment >
  collection** — matches the confirmed auth model. Cheap, concurrency-safe (no
  mutation of the shared base context).

**C. `HttpClient` — `src/overload/engine/http_client.py`**
- Constructor gains `data_source: DataSource | None = None` and an internal
  monotonic counter `self._row_index = 0`.
- At the **top** of `execute()` (after `ctx = variables or VariableContext()`,
  line ~56), before any `await`:
  ```python
  if self._data_source is not None:
      row = self._data_source.row_for(self._row_index)
      self._row_index += 1
      ctx = ctx.derive(row)
  ```
  The read+increment has no `await` between, so it is atomic under asyncio's
  single thread.
- **This is the only call-path change.** Every pattern (`load_patterns.py`), the
  sequential runner (`runner.py`), and the rate limiter (`rate_limiter.py`) all
  call `client.execute(request, variables)` unchanged, yet transparently get
  per-row data — including auth, because `_apply_auth` and `_prepare_body` already
  use `ctx`.
- `prepare_collection_auth()` (lines 155-167) keeps using the **base** `variables`
  (no row) → OAuth2 resolves once. No change needed; document the behavior.

**D. Placeholder discovery helper** (new function in `variables.py` or
`parser.py`): scan a `ParsedCollection` — `url_raw`, `headers`, `query_params`,
`body.content`, and `auth.params` — with the existing `VARIABLE_PATTERN` regex
(`variables.py:13`) to list every `{{name}}` used. The UI uses this to show which
CSV columns matched.

### 3.3 Web API — `src/overload/web/routes/api.py`
- `POST /api/data/upload` and a `load-local` variant: parse CSV → build
  `DataSource`; store in `_state["data_source"]`. Return
  `{columns, row_count, matched_placeholders, unmatched_placeholders}` by
  intersecting `columns` with discovered placeholders.
- `POST /api/data/clear` to detach.
- `start_test` (line ~249): construct the client with
  `HttpClient(..., data_source=_state.get("data_source"))`.
- Extend `/api/detect` (`_detect_postman_files`, line 43) to also surface `*.csv`
  files in the working directory.

### 3.4 Frontend — `src/overload/web/static/js/collection.js`
- Add a "Data file (CSV)" card below the environment card (`renderCollection`,
  ~line 190): a drop-zone upload mirroring the env upload flow.
- After upload, render a small table of detected columns: matched placeholders
  highlighted green, unmatched placeholders flagged amber ("no column").
- Persist attachment state so the runner can show "Using data file: N rows."

### 3.5 CLI — `src/overload/cli.py`
- Add `--data PATH` to the `run` subparser (and optionally `sequential`); build a
  `DataSource` and pass it into `HttpClient` (construction at lines ~225 and ~365).
- Print row count + matched columns in the banner.

### 3.6 Out of scope (v1, documented)
- **Per-row OAuth2** token acquisition (different client per row). UI shows a note
  that OAuth values are resolved **once per run**.

### 3.7 Tests — `tests/test_data_source.py` (+ extend existing)
- `DataSource.from_csv` parsing + `row_for` round-robin wrap-around.
- `VariableContext.derive` precedence (row overrides env/collection).
- Auth resolution from CSV: bearer/basic/api-key `{{placeholder}}` → CSV value via
  a derived context.
- `HttpClient.execute` integration with a mock transport (httpx `MockTransport`):
  consecutive calls cycle rows; verify the right values land in URL/header/body.
- Placeholder discovery helper.

---

<a name="feature-2"></a>
## 4. Feature 2 — Choose which requests to execute

### 4.1 Status — backend already exists
`start_test` already accepts `selected_requests` (a list of indices) and filters
`collection.requests`:
```python
# src/overload/web/routes/api.py
selected_indices = body.get("selected_requests")          # line 220
...
requests = collection.requests
if selected_indices is not None:                          # lines 237-239
    requests = [collection.requests[i] for i in selected_indices if i < len(collection.requests)]
```
**This feature is frontend-only.**

### 4.2 Frontend
- `collection.js`:
  - `renderRequestItem` (line 295) / `renderTree` (line 260): add a checkbox per
    request (checked by default), plus folder-level and a global "Select all /
    none" toggle. Track the selected index set in module state.
  - Expose selection (e.g. `getSelectedIndices()`); default to all when nothing is
    explicitly deselected.
- `app.js`: surface the selection through `OverloadApp` (e.g.
  `getSelectedRequests()`), since the runner reads collection state from there.
- `runner.js` `startTest()` (line 415): include `selected_requests` in the POST
  payload; show "Running N of M requests"; validate ≥1 selected.

### 4.3 Tests
- Add an API test asserting `selected_requests` filters correctly — this guards the
  existing backend contract the UI now depends on.

---

<a name="feature-3"></a>
## 5. Feature 3 — In-app documentation / help (same-page navigation)

### 5.1 Goal
A "Docs" area inside the running UI. Topic links open **in the same page** (swap
content client-side), never a new tab. Point users to it at CLI startup.

### 5.2 Design
- `src/overload/web/templates/index.html`: add to the sidebar (after the Results
  link, line 15):
  `<a href="#" data-page="docs" class="nav-link">Docs</a>`. Add `docs.js` to the
  script tags (lines 18-21).
- `src/overload/web/static/js/app.js` `navigate()` (line 17): add
  `case 'docs': DocsPage.render(content); break;`.
- New `src/overload/web/static/js/docs.js` (`window.DocsPage`): a two-pane layout —
  left list of topics, right content pane. Topic content is a JS object of HTML
  partials (concise versions of the existing `docs/*.html` site). Clicking a topic
  calls a JS handler that swaps the right pane (no `<a href>` navigation).
  Intra-doc cross-links use `data-topic="..."` handled by the same JS
  (scroll/swap), so nothing ever leaves the SPA.
  - **Topics:** Getting Started, Collections & Variables, **CSV Data Files** (new,
    for Feature 1), Authentication, Test Patterns, Assertions, CI/CD, Reports.
- `cli.py` `_start_ui()` banner (lines 116-118): add a line such as
  `Docs: open the in-app "Docs" tab, or https://dprakash2101.github.io/overload/`.

### 5.3 Notes
- The existing `docs/*.html` is a separate full GitHub-Pages site. Don't embed it
  wholesale; author trimmed in-app partials so the bundle stays light and the
  no-build-step constraint holds (vanilla JS, no Node).

### 5.4 Tests
- Light: assert the SPA shell (`/`) includes the Docs nav entry and loads
  `docs.js` (string check). Content is static; no heavy testing needed.

---

<a name="feature-4"></a>
## 6. Feature 4 — Generate a report from partial data on Stop

### 6.1 Root cause (confirmed by code review)
`stop_test` fires **both** a graceful cancel **and** a hard cancel:
```python
# src/overload/web/routes/api.py  (lines 360-370)
async def stop_test() -> JSONResponse:
    cancel_event = _state.get("cancel_event")
    if cancel_event:
        cancel_event.set()        # graceful path — patterns return partial results
    task = _state.get("current_task")
    if task and not task.done():
        task.cancel()             # HARD cancel — raises CancelledError mid-await
    return JSONResponse({"status": "ok"})
```
Every pattern already checks `cancel_event.is_set()` and returns its partial
`results` (e.g. `BurstPattern.execute` lines 165-174). But `task.cancel()` raises
`CancelledError` into the in-flight `await pattern.execute(...)`, so the pattern
never reaches `return all_results`; `stats.add_all(results)` is skipped; in the
`except asyncio.CancelledError` handler (lines 333-349) `stats.total == 0`, so
`stats.compute()` returns `None` and **no report is generated**.

### 6.2 Fix
- **`stop_test`:** set `cancel_event` only. Do **not** hard-cancel immediately.
  Optionally add a watchdog that calls `task.cancel()` *only* if the task hasn't
  finished within a grace window (e.g. 10s) as a safety fallback.
- **`_run_test` (lines 249-352):** after the pattern/runner returns (the graceful
  path), if `cancel_event.is_set()`, still run `stats.compute()` +
  `generate_report(...)`, store `report_path` + `stats`, and set
  `status = "stopped"` (a distinct, successful-with-partial-data state). Keep the
  `except asyncio.CancelledError` branch as a fallback that **also** attempts a
  report when `stats.total > 0`.
- **Results UI — `app.js` `renderResults` (lines 106-109):** show the HTML Report +
  Details actions for `status === 'stopped'` as well as `'complete'`.
- The live dashboard already treats a `phase` starting with `complete` as done
  (`runner.js:518, 599`), so the existing `"complete (stopped)"` broadcast flips
  the button to "View Results" — no change needed there.

### 6.3 Tests
- Simulate a run with `cancel_event` set mid-way; assert partial results are
  returned, a report file is generated, and run status is `stopped`.

---

<a name="feature-5"></a>
## 7. Feature 5 — Beginner-friendly live status

### 7.1 Goal
Make the live dashboard understandable to non-experts, building on the existing
rate-limit phase explainer (`runner.js:527-548`), which already does this well for
one pattern.

### 7.2 Design (mostly client-side — phase strings are already descriptive)
- **Generalize the phase explainer:** add a `friendlyPhase(phase)` map in
  `runner.js` covering all patterns and render a plain-English line under the
  progress bar. Examples:
  - `"Ramping up: 50 req/s"` → "Slowly increasing traffic to warm up the server."
  - `"Holding at 50 req/s"` → "Steady traffic to measure stable performance."
  - `"SPIKE: 200 req/s"` → "Sudden traffic surge to test recovery."
  - `"Firing 200 requests..."` → "Sending everything at once."
  - `"Probing: 120 req/s"` → "Searching for the exact point where performance degrades."
- **KPI glossary tooltips:** reuse the existing `.tooltip` pattern (already used in
  the config editor, `runner.js:152`) on the live KPI labels (Total, Success Rate,
  Avg Latency, Current RPS, Elapsed, Errors) with one-sentence explanations.
- **Optional "Beginner mode" toggle:** expands each KPI/phase with a fuller
  explanation; persist in `localStorage`; off by default.
- **Backend:** no change required for v1. If richer structure is wanted later, add
  an optional `phase_help` field to `RunProgress` (`engine/models.py:42-53`) and
  populate it in patterns — note as a follow-up, **not** required now.

### 7.3 Tests
- Light/manual (UI copy). Optionally a JS assertion that the friendly-phase map
  covers each pattern's emitted phase prefixes.

---

<a name="feature-6"></a>
## 8. Feature 6 — MCP server for Claude Code

### 8.1 Goal
Expose Overload's engine as a **Model Context Protocol (MCP) server** so Claude
Code (and any MCP client) can drive load tests conversationally, e.g.
*"Run a burst test on this collection and fail if p95 > 500 ms."* This is
high-leverage and low-cost: the engine is already a clean async library
(`parse_collection`, the load patterns, `Stats`, `assertions`), and the web layer
already orchestrates exactly this flow in `_run_test`.

### 8.2 Design

**A. Refactor orchestration into a shared service (prerequisite).**
The run orchestration currently lives inline in `web/routes/api.py` `_run_test`
(lines 249-352): build `HttpClient` → `prepare_collection_auth` → dispatch to
pattern/`run_sequential`/`run_rate_limit_test` → `Stats.compute` → assertions →
`generate_report`. Extract this into a reusable service, e.g.
`src/overload/engine/service.py` with something like:
```python
async def run_test(collection, test_type, config, *, variables, thresholds=None,
                   data_source=None, selected_indices=None, output_dir=...,
                   on_progress=None, cancel_event=None) -> RunResult
```
Then **both** the web route and the MCP server call it — no duplicated logic.
This refactor also benefits Features 1, 2 and 4 (single place to thread
`data_source`, `selected_indices`, and the stop-and-report fix).

**B. MCP server — new `src/overload/mcp_server.py`.**
- Use the official `mcp` Python SDK (FastMCP). Add an optional extra:
  `pip install "overload-cli[mcp]"`.
- Transport: **stdio** (what Claude Code launches locally). HTTP/SSE can come later.
- Tools to expose (thin wrappers over the shared service + existing functions):
  - `list_patterns()` → names + descriptions of the 10 test types.
  - `describe_collection(path)` → request count, names, methods, detected
    `{{placeholders}}` (reuses the Feature 1 placeholder-discovery helper).
  - `run_load_test(collection_path, pattern, config, assertions=None,
    environment_path=None, data_csv=None, selected_requests=None)` →
    **starts** a run, returns a `run_id` immediately (long tests must not block the
    MCP call). Mirrors the web `start_test` design.
  - `get_run_status(run_id)` → phase / completed / elapsed (poll while running).
  - `get_run_results(run_id)` → computed `Stats` summary + verdict + report path.
  - `stop_run(run_id)` → graceful stop (reuses the Feature 4 cancel path).
- Keep an in-process run registry (same shape as `api.py` `_state["runs"]`), or
  share it via the service module so web + MCP see the same runs.

**C. CLI wiring — `src/overload/cli.py`.**
- Add an `overload mcp` subcommand that starts the stdio MCP server.
- Document registration, e.g.:
  ```bash
  claude mcp add overload -- overload mcp
  ```

### 8.3 Guardrails (important — a load tester is a powerful tool)
- Sane caps surfaced to the model: warn/refuse on extreme `concurrency` /
  `total_requests` unless explicitly confirmed.
- `run_load_test` returns a clear summary the model can reason about (verdict,
  p95, error rate) rather than raw dumps.
- Never auto-open browsers or write outside the configured `output_dir`.

### 8.4 Tests — `tests/test_mcp_server.py`
- Tool schemas validate; `list_patterns` / `describe_collection` return expected
  shapes against a fixture collection.
- `run_load_test` → `get_run_results` happy path against a mock transport.
- The extracted `engine/service.py` gets its own unit tests (it becomes the
  critical shared path for web, CLI, and MCP).

### 8.5 Dependencies
- New optional extra in `pyproject.toml`: `mcp = ["mcp>=1.0"]` (exact package/
  version to confirm at implementation time). Keep it **optional** so the core
  install stays lean.

---

<a name="strategic"></a>
## 9. Strategic direction — hosted/server mode for internal APIs

> Captured in response to: *"Why can't we publish to a server and load test
> internal APIs — is that a good option, or is the CLI enough?"* This section is
> **analysis + recommendation**, not a committed feature.

### 9.1 Recommendation (short version)
- **CLI + local UI is enough** for individual, ad-hoc, and CI use. Don't replace it.
- **Reachability is already solved** in this setup: the developer's laptop reaches
  the internal APIs over **VPN**, so the usual top reason to host a runner (network
  access) does **not** apply here. That weakens the case for a server.
- A server is therefore only worth it later for **team-scale** reasons —
  scheduling/continuous runs without a laptop online, shared result history, or
  RPS beyond one machine — not for access.
- **Build MCP (Feature 6) first**; it's higher-leverage and far cheaper.
- **Defer distributed load generation and any public SaaS** under YAGNI until
  there's proven demand and a security model.

### 9.2 Where a self-hosted runner would (and would not) help
> **Context update:** the laptop already reaches internal endpoints via VPN, so
> *reachability is not a problem to solve.* That removes the single most common
> justification for a hosted runner. The points below are the **remaining** —
> narrower — reasons, which are "nice to have at team scale," not blockers.

Remaining value, only if/when these become real needs:
- **Scheduling / continuous testing** without keeping a laptop on and connected.
- **Shared run history & dashboards** for a team (today `_state["runs"]` is
  in-memory and per-process; survives nothing).
- **Higher RPS** than one machine + Python asyncio can push (needs distributed
  workers — a large, separate track).
- **Not tying up the laptop / VPN session** for long soak tests.

If pursued, it's still an **incremental, opt-in deployment mode**, not a rewrite —
**the FastAPI app already _is_ a server** (`overload` runs uvicorn via
`_start_ui`; the `--host` flag already exists):
- Ship a **Docker image**; allow binding to `0.0.0.0`.
- Add **persistent run history** (SQLite) so results survive restarts.
- Add **optional auth** (token / basic) before exposing beyond localhost.
- Add **scheduling** (cron-style) for continuous runs.

**Bottom line for the current setup:** with VPN access working, the CLI/local UI
covers the need today. Treat a hosted runner as a *future, team-scale* option —
not part of this release.

### 9.3 Why NOT a public/multi-tenant SaaS (for now)
- **Security liability:** a network-reachable load tester is a DoS weapon if
  abused. It needs a **target allowlist**, per-run **request/concurrency caps**,
  and access control before it is safe to host.
- **Secret handling:** Postman collections embed tokens/credentials; storing them
  server-side raises real compliance/security concerns.
- **Scope explosion:** multi-tenancy, a real database, billing/quotas, infra/ops.
- **Single-node RPS ceiling:** one box + Python asyncio caps throughput. Serious
  load needs **distributed workers** (a coordinator + multiple generators) — a
  major engineering track on its own. Defer until single-node is proven
  insufficient.

### 9.4 If/when hosted mode is pursued — guardrails (non-negotiable)
- Target allowlist (only approved internal hosts).
- Hard caps on concurrency and total requests per run, with admin overrides.
- AuthN/AuthZ on every endpoint; no anonymous runs.
- Secrets kept out of persistent storage where possible (reference env/secret
  managers instead of embedding).
- Audit log of who ran what against which target.

### 9.5 Suggested phasing
1. **Now:** MCP (Feature 6) + the five UX/engine features.
2. **Next (opt-in):** self-hosted runner — Docker image + SQLite history + optional
   auth, deployed inside the network.
3. **Later (only if needed):** scheduling, then distributed load generation, then
   (only with a real security model) any multi-tenant/hosted offering.

---

<a name="suggested-sequencing"></a>
## 10. Suggested sequencing for implementers

Each feature is independently shippable and should be its own focused PR
(per `CLAUDE.md` "Keep PRs focused").

1. **Feature 4** — small, high-value bugfix; isolated to `api.py` + a UI tweak.
2. **Feature 2** — frontend-only; backend contract already exists.
3. **Feature 5** — client-side UX; independent.
4. **Feature 3** — additive Docs page; independent.
5. **Feature 1** — largest; new `DataSource`, `VariableContext.derive`, `HttpClient`
   wiring, API/UI/CLI, tests. Land last; it touches the engine core.

---

<a name="verification"></a>
## 9. Verification (per feature, when implemented)

- **Unit tests:** `pytest tests/` — add the suites listed per feature; keep
  coverage (the suite currently covers every module).
- **Feature 1:** create a small CSV (`email,token` columns) + a collection using
  `{{email}}`/`{{token}}` (including a Bearer `{{token}}` auth); run
  `overload run --collection c.json --data data.csv --pattern burst --save-responses`
  against an echo endpoint and confirm each request used a different row and the
  Bearer header reflected the CSV token. Repeat via the UI.
- **Feature 2:** load a multi-request collection, deselect some, start a run, and
  confirm only selected requests appear in the live log + report.
- **Feature 3:** run `overload`, open the Docs tab, click topics and intra-doc
  links; confirm content swaps in-place with no new tab/page load.
- **Feature 4:** start a long run (e.g. soak), click Stop, confirm a report is
  produced from partial data and the run shows `stopped` with working HTML
  Report/Details actions.
- **Feature 5:** start each pattern; confirm the plain-English status line and KPI
  tooltips render and read clearly.

---

<a name="architecture-notes"></a>
## 10. Key architecture notes for implementers

These are the load-bearing facts uncovered during review — read before coding.

- **Variable resolution is the spine of the engine.** `VariableContext`
  (`collection/variables.py`) resolves `{{var}}` through ordered scopes. Auth, body,
  URL, headers, and query params all flow through it. Feature 1's entire design
  leans on this: add one scope, touch one method in `HttpClient.execute`.
- **Patterns share two helpers.** `_fire_one` and `_pick_request`
  (`engine/load_patterns.py:39-56`) are called by every pattern and by the rate
  limiter. The rate limiter imports them directly (`rate_limiter.py:12`). Keep
  changes there minimal and uniform.
- **Cancellation is cooperative.** Patterns poll `cancel_event.is_set()` and return
  partial results. The *graceful* path is the one that yields data; hard
  `task.cancel()` destroys it (root cause of Feature 4).
- **Progress is decoupled via `RunProgress` + WebSocket.** Engine emits
  `RunProgress` (`engine/models.py`); `web/routes/ws.py` `broadcast_progress`
  serializes it with `dataclasses.asdict` and pushes to subscribed sockets;
  `runner.js onProgress` renders it. Feature 5 mostly lives in `onProgress`.
- **`start_test` already accepts `selected_requests`.** Feature 2 only needs the UI
  to send the indices.
- **No build step / no Node.** Frontend is vanilla JS in
  `web/static/js/{app,collection,runner,charts}.js` loaded directly by
  `templates/index.html`. New JS (docs.js) follows the same `window.X = (function(){…})()`
  module pattern.
- **Conventions (from `CLAUDE.md`):** type hints on all signatures;
  `from __future__ import annotations`; dataclasses for internal models;
  async/await for all I/O; `logging` (never `print` for diagnostics); PEP 8;
  module-level imports unless a concrete perf reason; no `Co-Authored-By` in
  commits; one focused PR per feature; add tests for new behavior.
