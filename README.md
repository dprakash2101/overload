# Overload

Free, open-source load testing tool that reads Postman collections. Run tests from a browser dashboard or the terminal CLI.

**📚 [Read the Full Documentation](https://dprakash2101.github.io/overload/)**

---

## Why "Overload"?

Named Overload because that's exactly what it does to your server.

No metaphor. No brand committee. Just requests — a lot of them — all at once, until something interesting happens.

---

## Install

```bash
pip install overload-cli

# With MCP server support (for Claude Code / Codex CLI / GitHub Copilot)
pip install "overload-cli[mcp]"
```

Or in dev mode from source:

```bash
git clone https://github.com/dprakash2101/overload
cd overload
pip install -e ".[dev]"
```

---

## Two Ways to Run

### Option 1 — Browser UI (results on screen)

Run `overload` with no arguments. It starts a local server and opens a dashboard in your browser where you configure the test, watch live progress, and view charts and reports — **no terminal reading required**.

```bash
overload
# Opens http://localhost:3000 automatically
```

**Step-by-step in the browser:**

1. The app auto-detects any Postman collection JSON files in your working directory and lists them under **"Detected Files"**. Click **Load** next to the one you want.
2. Optionally load a Postman environment file the same way.
3. Pick the **Test Type** from the dropdown (Burst, Load, Stress, Spike, etc.).
4. Adjust the config fields that appear (concurrency, RPS, duration, etc.).
5. Click **Start Test**. The dashboard shows live progress: phase, request count, RPS, and a real-time latency chart.
6. When the test finishes, click **View Report** to open the full HTML report in a new tab — latency charts, timeline scatter, per-second breakdown, and the raw request log.
7. Click **Stop** at any time. Overload waits up to 10 seconds for the pattern to finish cleanly, then generates a partial HTML report from whatever data was collected — nothing is lost.

**Options:**

```bash
overload ui --port 8080          # Use a different port
overload ui --no-browser         # Start server without auto-opening browser
overload ui --host 0.0.0.0       # Bind to all interfaces (LAN access)
```

---

### Option 2 — CLI (results in terminal)

Run tests headlessly and see a progress bar + summary printed to the terminal. An HTML report is saved to disk.

```bash
overload run --collection path/to/collection.json --pattern burst
```

**Output looks like:**

```
  OVERLOAD — BURST TEST
  Collection: my_api.json
  Requests: 5
  Run ID: burst_20260529_abc123

  [####################] 100% (200 requests) — complete

  Results:
    Total: 200  OK: 198  Errors: 2
    Latency — min: 45ms  p95: 312ms  max: 891ms
    Duration: 4.2s  Avg RPS: 47.6

  Report: /path/to/reports/run_20260529_153021_abc123/report.html
```

Each run gets its own folder under `reports/` named `run_<run_id>/`, containing
`report.html`, a `meta.json` sidecar (so runs survive restarts), and — when
`--save-responses` is used — a `responses.json` with the captured response bodies.

**All CLI flags for `overload run`:**

| Flag | Default | Description |
|------|---------|-------------|
| `--collection` | *(required)* | Path to Postman collection JSON |
| `--environment` | — | Path to Postman environment JSON |
| `--pattern` | `burst` | Test type: `load`, `stress`, `spike`, `soak`, `ramp`, `burst`, `breakpoint`, `custom`, `ratelimit` |
| `--requests` | `200` | Total requests (burst / rate limit tests) |
| `--concurrency` | `20` | Max simultaneous connections |
| `--rps` | `50` | Target requests per second |
| `--duration` | `300` | Test duration in seconds |
| `--timeout` | `30` | Per-request timeout in seconds |
| `--stages` | — | Custom stages JSON: `'[{"duration":60,"rps":100}]'` |
| `--var KEY=VALUE` | — | Override a collection variable (repeatable) |
| `--save-responses` | off | Save response bodies in the report |
| `--no-verify-ssl` | off | Skip SSL certificate verification |
| `--output` | `reports` | Directory to write the HTML report |
| `--format` | `html` | Report format: `html`, `json`, `csv` |
| `--data PATH` | — | CSV file for data-driven testing — each row fills `{{placeholders}}` in URLs, headers, body, and auth round-robin |
| `--assert EXPR` | — | Assertion threshold (repeatable), e.g. `p95_latency_ms<500` |
| `--junit PATH` | — | Write JUnit XML report for CI systems |
| `--config PATH` | — | Load config from `overload.config.yaml` |
| `--open-report` | off | Open HTML report in browser after run |

**Sequential runner (run requests in order):**

```bash
overload sequential --collection my_api.json --iterations 5 --delay 500
```

| Flag | Default | Description |
|------|---------|-------------|
| `--collection` | *(required)* | Path to Postman collection JSON |
| `--environment` | — | Path to Postman environment JSON |
| `--iterations` | `1` | How many times to run the full collection |
| `--delay` | `0` | Milliseconds to wait between requests |
| `--timeout` | `30` | Per-request timeout in seconds |
| `--output` | `.` | Directory to write the HTML report |

---

## Test Types

| Type | What it does |
|------|-------------|
| **Burst** | Fires all N requests at once as fast as possible |
| **Load** | Sustained traffic — ramp up → hold at target RPS → ramp down |
| **Stress** | Steps up RPS until errors exceed the failure threshold |
| **Spike** | Baseline RPS → sudden spike → recovery, to test elasticity |
| **Soak** | Steady low RPS over a long duration (find memory leaks / drift) |
| **Ramp** | Linearly increases from start RPS to end RPS |
| **Breakpoint** | Binary search to find the exact RPS where latency or errors degrade |
| **Custom** | Define your own stages: `[{"duration": 60, "rps": 100}, ...]` |
| **Rate Limit** | 2-phase validation: sends at cap (req/min) → cooldown → exceeds cap; returns a working / not_working / too_strict verdict |
| **Sequential** | Runs each request in collection order, N iterations |

---

## CI/CD Integration

Overload can gate your CI pipeline. Add assertions and the process exits `1` on failure — the universal CI signal.

**Inline assertions:**

```bash
overload run --collection api.json --pattern load --rps 100 --duration 60 \
  --assert "p95_latency_ms<500" \
  --assert "error_rate_pct<1" \
  --junit results.xml
```

**Using a config file:**

Save your test config with assertions to `overload.config.yaml` (the browser UI can do this via **Save Config**):

```yaml
test_type: load
config:
  target_rps: 100
  hold_duration_seconds: 60
  concurrency: 20
thresholds:
  - metric: p95_latency_ms
    operator: "<"
    value: 500
  - metric: error_rate_pct
    operator: "<"
    value: 1
```

Then in CI:

```bash
overload run --collection api.json --config overload.config.yaml --junit results.xml
```

**GitHub Actions example:**

```yaml
- name: Run load test
  run: |
    pip install overload-cli
    overload run --collection tests/api.json \
      --config overload.config.yaml \
      --junit results.xml

- name: Publish test results
  uses: dorny/test-reporter@v1
  if: always()
  with:
    name: Load Test
    path: results.xml
    reporter: java-junit
```

**Available assertion metrics:** `p50_latency_ms`, `p95_latency_ms`, `p99_latency_ms`, `max_latency_ms`, `mean_latency_ms`, `error_rate_pct`, `success_rate_pct`, `avg_rps`, `total_requests`, `rate_limited_count`

**Operators:** `<`, `<=`, `>`, `>=`, `==`

---

## CSV Data-Driven Testing

Attach a CSV file and each request automatically fills its `{{placeholders}}` from a different row — round-robin across URLs, headers, body fields, query params, and auth.

**CLI:**

```bash
overload run --collection api.json --data users.csv --pattern burst --requests 500
```

**Browser UI:** drag-and-drop or upload a CSV on the Collection page after loading a collection. The UI shows which `{{placeholders}}` matched columns (green) and which didn't (amber).

**How it works:** a column named `email` in the CSV fills every `{{email}}` occurrence in the collection automatically. Row *N* is used by request *N mod row_count*, so load volume stays independent of CSV size.

---

## MCP Server (Claude Code / Codex CLI / GitHub Copilot)

Run load tests conversationally from any MCP client.

```bash
pip install "overload-cli[mcp]"
```

**Register once:**

```bash
# Claude Code
claude mcp add overload -- overload mcp

# Codex CLI
codex mcp add overload -- overload mcp
```

**GitHub Copilot (VS Code)** — add to `settings.json`:

```json
"mcpServers": {
  "overload": { "command": "overload", "args": ["mcp"] }
}
```

**Available tools:** `list_patterns`, `describe_collection`, `run_load_test`, `get_run_status`, `get_run_results`, `stop_run`.

Example conversation with Claude Code: *"Run a burst test on tests/api.json with 200 requests and fail if p95 exceeds 500 ms."*

---

## Quick Reference

```
# See results in browser (recommended)
overload

# See results in terminal
overload run --collection my_api.json --pattern burst --requests 100

# Debug mode (verbose logging)
overload --debug
# or
OVERLOAD_DEBUG=1 overload
```

---

## Working Directory

When you launch `overload` from a directory that contains Postman JSON files, the UI auto-detects and lists them. Start from your project folder:

```bash
cd path/to/my-api-tests/
overload
```

The HTML report is also saved to the working directory after each test.
