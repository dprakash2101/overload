# Changes Done — feat/report-on-stop-and-request-selection

Branch: `feat/report-on-stop-and-request-selection`
Date: 2026-06-06

---

## Feature 4 — Report on Stop

**Problem:** Stopping a test immediately hard-cancelled the asyncio task via `task.cancel()`, raising `CancelledError` before the pattern could return partial results. As a result, `stats.compute()` returned `None` and no report was generated.

**Fix:**

- `stop_test` (`src/overload/web/routes/api.py`) no longer calls `task.cancel()` immediately. It only sets `cancel_event` and spawns a 10-second async watchdog. The watchdog hard-cancels only if the task is still running after the grace window.
- `_run_test` checks `cancel_event.is_set()` after `pattern.execute()` returns:
  - Sets `status = "stopped"` (distinct from `"complete"`)
  - Sets `phase = "complete (stopped)"` in the final `RunProgress` broadcast
  - Always generates a report when `stats.compute()` is not `None` (partial data is sufficient)
- The `except asyncio.CancelledError` fallback (hard-cancel path) also attempts report generation from partial `stats` data and records `status = "stopped"` instead of the old `"cancelled"`.
- `src/overload/web/static/js/app.js`: Results page now shows HTML Report + Details action buttons for both `"complete"` and `"stopped"` status runs.

**Files changed:**
- `src/overload/web/routes/api.py`
- `src/overload/web/static/js/app.js`

---

## Feature 2 — Request Selection

**Problem:** Users could not cherry-pick a subset of requests from the loaded collection to run. All requests were always executed.

**Fix:**

### Backend (`src/overload/web/routes/api.py`)
- `start_test` now validates that `selected_requests` (when provided) is not empty — returns `400` with `"No requests selected"` if it is an empty list.
- Existing `selected_indices` filtering logic was already in place in `_run_test`; no further backend changes needed.

### Frontend — Collection page (`src/overload/web/static/js/collection.js`)
- Module-level `selectedIndices` variable (`null` = all selected, array = subset).
- `initSelectedIndices()` initialises from the full request list on collection load.
- `renderCollection()` now renders selection controls: **Select All** / **Select None** buttons and a live **"N of M selected"** counter above the tree.
- `renderTree()` adds a `<input type="checkbox" class="folder-checkbox">` per folder with indeterminate-state support for partial folder selection.
- `renderRequestItem()` adds a `<input type="checkbox" class="req-checkbox" data-idx="N">` per request (checked by default).
- `updateSelectionCount()` keeps the counter in sync after every checkbox change.
- `updateFolderCheckbox(changedCb)` syncs the parent folder checkbox state (checked / unchecked / indeterminate).
- Checkbox clicks use `event.stopPropagation()` to prevent triggering the request detail view.
- New export: `getSelectedIndices()` — returns `null` (all) or a sorted index array (subset).

### Frontend — Runner page (`src/overload/web/static/js/runner.js`)
- `startTest()` calls `CollectionPage.getSelectedIndices()`:
  - Shows `App.toast('Select at least one request to run', 'error')` and aborts if the array is empty.
  - Adds `selected_requests` to the POST payload only when a subset is selected (`null` omits the field, meaning run all).
- `showLiveDashboard(selectedReqs, totalReqs)` displays **"N of M requests"** in the dashboard title when a partial selection is active.

**Files changed:**
- `src/overload/web/routes/api.py`
- `src/overload/web/static/js/collection.js`
- `src/overload/web/static/js/runner.js`

---

## Tests (`tests/test_api.py`)

5 new tests added (total suite: 182, all passing).

### `TestSelectedRequests`
- `test_empty_selection_returns_400` — empty `selected_requests` array → 400, message contains "No requests selected"
- `test_valid_selection_accepted` — `[0, 2]` selection → 200, status "ok"
- `test_no_selection_field_runs_all` — omitting `selected_requests` → 200, status "ok"

### `TestStopGeneratesReport`
- `test_graceful_stop_produces_stopped_status` — mock pattern sets `cancel_event` and returns 5 `RequestResult` objects; verifies run `status == "stopped"` and `report_path` exists on disk.
- `test_hard_cancel_still_stores_stopped_status` — mock pattern hangs; task is directly cancelled (simulating watchdog); verifies `status == "stopped"`.

New fixture: `multi_request_collection` — 3-request collection wired to a `TestClient`.

---

## Feature 5 — Beginner-friendly live status

**Files changed:**
- `src/overload/web/static/js/runner.js`

- Added `friendlyPhase(phase)` — maps every pattern phase string to a plain-English sentence shown below the progress bar during a run.
- Added `?` tooltip chips on all 6 live KPI labels (Total, Success Rate, Avg Latency, Current RPS, Elapsed, Errors).
- Added "Beginner mode" toggle button in the live dashboard header. When ON, shows concise sub-labels under each KPI value. State persisted in `localStorage`.
- Added `toggleBeginnerMode()` and `applyBeginnerMode()` helper functions.
- Added `beginnerMode` module-level variable initialised from `localStorage`.

---

## Feature 3 — In-app documentation

**Files changed:**
- `src/overload/web/templates/index.html` — added "Docs" nav link and `docs.js` script tag
- `src/overload/web/static/js/app.js` — added `case 'docs': DocsPage.render(content); break;` in `navigate()`
- `src/overload/web/static/js/docs.js` — new file
- `src/overload/cli.py` — added Docs mention to startup banner

**New `docs.js`:**
- Two-pane layout: left topic list, right content pane. All navigation is client-side — no page reload, no new tab.
- 8 topics: Getting Started, Collections & Variables, CSV Data Files, Authentication, Test Patterns, Assertions, CI/CD, Reports.
- Intra-doc links use `data-topic="..."` handled by the same JS click handler.
- Content is a plain JS object of HTML strings — no build step, no external dependencies.

---

## Feature 1 — CSV data-driven testing

**Files changed / created:**
- `src/overload/collection/data_source.py` — new file
- `src/overload/collection/variables.py` — added `derive()` method
- `src/overload/engine/http_client.py` — added `data_source` param and row-index logic
- `src/overload/web/routes/api.py` — new endpoints, `/api/detect` CSV support, wiring
- `src/overload/web/static/js/collection.js` — CSV upload UI
- `src/overload/cli.py` — `--data PATH` flag on `run` and `sequential`
- `tests/test_data_source.py` — new file, 13 tests

**`DataSource` (`data_source.py`):**
- `from_csv(path_or_file)` — accepts file path string or file-like object (bytes or str); strips BOM.
- `row_for(index)` — returns rows round-robin (`index % len(rows)`); returns `{}` when no rows.

**`VariableContext.derive(extra)`:**
- Prepends a CSV-row scope at the top of the existing scope chain.
- Precedence: CSV row > runtime > environment > collection.
- Does not mutate the base context — safe for concurrent use.

**`HttpClient`:**
- New `data_source: DataSource | None = None` constructor param; defaults to `None` (no CSV = existing behaviour unchanged).
- New `_row_index` counter (monotonic, no `await` between read and increment — atomic under asyncio).
- In `execute()`: if `data_source` is set, derives a per-row context before resolving any variables. URL, headers, body, query params, and auth all get CSV values transparently.

**API (`api.py`):**
- `_state["data_source"]` added.
- `POST /api/data/upload` — CSV file upload; returns `{row_count, columns, matched_placeholders, unmatched_placeholders}`.
- `POST /api/data/load-local` — load by file path.
- `POST /api/data/clear` — detach.
- `GET /api/data/status` — check if a CSV is attached.
- `GET /api/detect` — now also surfaces `.csv` files from the working directory.
- `start_test` passes `data_source=_state.get("data_source")` into `HttpClient`.

**Collection page (`collection.js`):**
- "Data file (CSV)" drop-zone card shown after a collection is loaded.
- After upload renders matched placeholders (green ✓) and unmatched ones (amber warning).
- "Remove" button calls `POST /api/data/clear` and hides the status line.

**CLI (`cli.py`):**
- `--data PATH` added to `run` and `sequential` subcommands.
- Prints row count + column names in the banner before the run starts.

**Tests (`tests/test_data_source.py`):**
- 13 new tests (total suite: 195, all passing).
- `TestDataSourceFromCsv` — path, file-like bytes, file-like str, empty CSV, BOM stripping.
- `TestDataSourceRowFor` — round-robin wrap, empty-rows guard.
- `TestVariableContextDerive` — CSV overrides env, base context unchanged, non-overridden vars still resolve, chained derives stack.
- `TestHttpClientDataSource` — consecutive calls cycle rows (mock transport), no-data-source path works normally.

---

## Notes for Changelog

- New terminal run status: `"stopped"` (visible in Results table and run data API).
- `POST /api/test/stop` behaviour changed: cooperative cancellation with 10s grace, not immediate hard cancel.
- `POST /api/test/start` now returns 400 when `selected_requests` is an explicitly empty array.
- No breaking changes to existing API contracts — `selected_requests` and `data_source` are both optional.
- New API endpoints: `/api/data/upload`, `/api/data/load-local`, `/api/data/clear`, `/api/data/status`.
- `/api/detect` response now includes a `csv_files` array.
- New CLI flags: `--data PATH` on `run` and `sequential`.
- New "Docs" tab in the browser UI.
- Beginner mode toggle in the live dashboard (localStorage-persisted).
