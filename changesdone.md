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

## Notes for Changelog

- New terminal run status: `"stopped"` (visible in Results table and run data API).
- `POST /api/test/stop` behaviour changed: cooperative cancellation with 10s grace, not immediate hard cancel.
- `POST /api/test/start` now returns 400 when `selected_requests` is an explicitly empty array.
- No breaking changes to existing API contracts — `selected_requests` field remains optional.
