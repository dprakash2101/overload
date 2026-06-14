window.DocsPage = (function() {
  var currentTopic = 'getting-started';

  var TOPICS = [
    { id: 'getting-started', label: 'Getting Started' },
    { id: 'collections', label: 'Collections & Variables' },
    { id: 'csv-data', label: 'CSV Data Files' },
    { id: 'auth', label: 'Authentication' },
    { id: 'patterns', label: 'Test Patterns' },
    { id: 'assertions', label: 'Assertions' },
    { id: 'cicd', label: 'CI/CD' },
    { id: 'reports', label: 'Reports' }
  ];

  var CONTENT = {
    'getting-started':
      '<h2>Getting Started</h2>' +
      '<p>Overload is a free, open-source load testing tool that reads Postman collections.</p>' +
      '<h3>Install</h3>' +
      '<pre>pip install overload</pre>' +
      '<h3>Start the UI</h3>' +
      '<pre>overload</pre>' +
      '<p>Opens the browser UI at <strong>http://localhost:3000</strong>. Upload a Postman collection, choose a test pattern, and click Start Test.</p>' +
      '<h3>CLI (headless / CI)</h3>' +
      '<pre>overload run --collection path/to/collection.json --pattern burst</pre>' +
      '<p>See <span class="doc-link" data-topic="cicd" style="color:var(--link,#1d5fa8);cursor:pointer;text-decoration:underline">CI/CD</span> for full CLI options.</p>',

    'collections':
      '<h2>Collections &amp; Variables</h2>' +
      '<p>Overload reads Postman Collection v2.0 and v2.1 JSON files. Drop the file on the Collection page or point the CLI at it with <code>--collection</code>.</p>' +
      '<h3>Variables</h3>' +
      '<p>Use <code>{{variableName}}</code> placeholders anywhere — URL, headers, body, query params, or auth fields. Resolution order (highest priority first):</p>' +
      '<ol>' +
        '<li>CSV row (if a data file is attached — see <span class="doc-link" data-topic="csv-data" style="color:var(--link,#1d5fa8);cursor:pointer;text-decoration:underline">CSV Data Files</span>)</li>' +
        '<li>Runtime / CLI vars (<code>--var key=value</code> or the Variables panel)</li>' +
        '<li>Environment file</li>' +
        '<li>Collection defaults</li>' +
      '</ol>' +
      '<h3>Dynamic variables</h3>' +
      '<p>Built-in: <code>{{$randomInt}}</code>, <code>{{$guid}}</code>, <code>{{$timestamp}}</code>, <code>{{$randomEmail}}</code>, and more.</p>' +
      '<h3>Folders</h3>' +
      '<p>Nested folders are flattened into a single request list. Auth set on a folder is inherited by its children.</p>',

    'csv-data':
      '<h2>CSV Data Files</h2>' +
      '<p>Attach a CSV to drive each request with different data. Column headers map directly to <code>{{placeholders}}</code> in your collection.</p>' +
      '<h3>Example</h3>' +
      '<p>CSV file:</p>' +
      '<pre>email,token\nalice@example.com,tok-abc\nbob@example.com,tok-xyz</pre>' +
      '<p>Collection uses <code>{{email}}</code> in the body and <code>{{token}}</code> as a Bearer auth token.</p>' +
      '<p>Request 0 uses row 0, request 1 uses row 1, request 2 wraps back to row 0 — <strong>round-robin</strong>.</p>' +
      '<h3>How to attach</h3>' +
      '<ul>' +
        '<li><strong>UI:</strong> use the "Data file (CSV)" section on the Collection page</li>' +
        '<li><strong>CLI:</strong> <code>overload run --collection c.json --data data.csv --pattern burst</code></li>' +
      '</ul>' +
      '<h3>Auth note</h3>' +
      '<p>Bearer, Basic, and API Key auth values are resolved through the same variable chain — put <code>{{token}}</code> in your collection\'s auth and supply it as a CSV column.</p>' +
      '<p>OAuth 2 tokens are resolved <em>once per run</em> (not per row).</p>' +
      '<h3>Works without CSV too</h3>' +
      '<p>CSV is always optional. If no data file is attached, all requests use collection/environment variables as usual.</p>',

    'auth':
      '<h2>Authentication</h2>' +
      '<p>Auth is configured on the collection or folder in Postman and inherited by child requests. Overload supports:</p>' +
      '<ul>' +
        '<li><strong>Bearer</strong> — <code>Authorization: Bearer {{token}}</code></li>' +
        '<li><strong>Basic</strong> — base64-encoded <code>{{username}}:{{password}}</code></li>' +
        '<li><strong>API Key</strong> — header or query parameter</li>' +
        '<li><strong>OAuth 2</strong> — fetched once per run using <code>token_url</code>, <code>client_id</code>, <code>client_secret</code> from context</li>' +
      '</ul>' +
      '<p>All auth values are just variables. Put <code>{{token}}</code> in your collection and supply the value via environment file, CSV column, or <code>--var</code>.</p>',

    'patterns':
      '<h2>Test Patterns</h2>' +
      '<table style="width:100%;border-collapse:collapse;font-size:12px">' +
        '<thead><tr>' +
          '<th style="text-align:left;padding:6px;border-bottom:1px solid var(--border)">Pattern</th>' +
          '<th style="text-align:left;padding:6px;border-bottom:1px solid var(--border)">What it does</th>' +
        '</tr></thead>' +
        '<tbody>' +
          '<tr><td style="padding:6px;border-bottom:1px solid var(--border)"><strong>Load</strong></td><td style="padding:6px;border-bottom:1px solid var(--border)">Sustained traffic at target RPS with ramp up/down. Baseline performance test.</td></tr>' +
          '<tr><td style="padding:6px;border-bottom:1px solid var(--border)"><strong>Stress</strong></td><td style="padding:6px;border-bottom:1px solid var(--border)">Incrementally increase RPS until failure threshold or max RPS is reached.</td></tr>' +
          '<tr><td style="padding:6px;border-bottom:1px solid var(--border)"><strong>Spike</strong></td><td style="padding:6px;border-bottom:1px solid var(--border)">Baseline &#x2192; sudden surge &#x2192; recover. Tests how fast the server recovers.</td></tr>' +
          '<tr><td style="padding:6px;border-bottom:1px solid var(--border)"><strong>Soak</strong></td><td style="padding:6px;border-bottom:1px solid var(--border)">Steady load over a long duration. Surfaces memory leaks and performance drift.</td></tr>' +
          '<tr><td style="padding:6px;border-bottom:1px solid var(--border)"><strong>Ramp</strong></td><td style="padding:6px;border-bottom:1px solid var(--border)">Gradually increase RPS step by step to find the optimal operating point.</td></tr>' +
          '<tr><td style="padding:6px;border-bottom:1px solid var(--border)"><strong>Burst</strong></td><td style="padding:6px;border-bottom:1px solid var(--border)">Fire all requests simultaneously. Useful for quick smoke tests.</td></tr>' +
          '<tr><td style="padding:6px;border-bottom:1px solid var(--border)"><strong>Breakpoint</strong></td><td style="padding:6px;border-bottom:1px solid var(--border)">Binary-search for the exact RPS where latency/error rate exceeds thresholds.</td></tr>' +
          '<tr><td style="padding:6px;border-bottom:1px solid var(--border)"><strong>Custom</strong></td><td style="padding:6px;border-bottom:1px solid var(--border)">Define your own load stages (duration + RPS per stage).</td></tr>' +
          '<tr><td style="padding:6px;border-bottom:1px solid var(--border)"><strong>Rate Limit</strong></td><td style="padding:6px;border-bottom:1px solid var(--border)">Verify API rate limiting: Phase 1 under cap &#x2192; Phase 2 over cap. Expects 429s in Phase 2.</td></tr>' +
          '<tr><td style="padding:6px"><strong>Sequential</strong></td><td style="padding:6px">Run each request in order, N iterations. Good for smoke tests and functional checks.</td></tr>' +
        '</tbody>' +
      '</table>',

    'assertions':
      '<h2>Assertions (CI Thresholds)</h2>' +
      '<p>Add pass/fail thresholds before starting a test. After the run, Overload evaluates each assertion and shows a PASS / FAIL verdict.</p>' +
      '<h3>Available metrics</h3>' +
      '<ul>' +
        '<li><code>p50_latency_ms</code>, <code>p95_latency_ms</code>, <code>p99_latency_ms</code>, <code>max_latency_ms</code>, <code>mean_latency_ms</code></li>' +
        '<li><code>error_rate_pct</code>, <code>success_rate_pct</code></li>' +
        '<li><code>avg_rps</code>, <code>total_requests</code></li>' +
        '<li><code>rate_limited_count</code></li>' +
      '</ul>' +
      '<h3>UI</h3>' +
      '<p>Expand the "Assertions" section in the configuration panel and click "+ Add Assertion".</p>' +
      '<h3>CLI</h3>' +
      '<pre>overload run --collection c.json --pattern load \\\n  --assert "p95_latency_ms&lt;500" \\\n  --assert "error_rate_pct&lt;1"</pre>' +
      '<p>Exit code <code>0</code> = pass, <code>1</code> = assertion failure, <code>2</code> = configuration error.</p>',

    'cicd':
      '<h2>CI/CD Integration</h2>' +
      '<p>Use the <code>overload run</code> command for headless, automated testing.</p>' +
      '<h3>Basic usage</h3>' +
      '<pre>overload run \\\n  --collection api.postman_collection.json \\\n  --environment prod.postman_environment.json \\\n  --pattern load \\\n  --rps 100 --duration 120 \\\n  --assert "p95_latency_ms&lt;500" \\\n  --output reports/</pre>' +
      '<h3>With a CSV data file</h3>' +
      '<pre>overload run --collection c.json --data users.csv --pattern burst</pre>' +
      '<h3>Exit codes</h3>' +
      '<ul>' +
        '<li><code>0</code> — all assertions passed (or none set)</li>' +
        '<li><code>1</code> — one or more assertions failed</li>' +
        '<li><code>2</code> — configuration or parse error</li>' +
      '</ul>' +
      '<h3>JUnit XML</h3>' +
      '<pre>overload run ... --junit results.xml</pre>' +
      '<h3>Save config for reuse</h3>' +
      '<p>Click "Save Config" in the UI to write <code>overload.config.yaml</code>, then use <code>--config overload.config.yaml</code> in CLI.</p>',

    'reports':
      '<h2>Reports</h2>' +
      '<p>After a test completes (or is stopped), Overload generates an HTML report with:</p>' +
      '<ul>' +
        '<li>KPI summary — total, OK, errors, avg RPS, duration, p95 latency</li>' +
        '<li>Per-second RPS timeline chart</li>' +
        '<li>Status code distribution</li>' +
        '<li>Latency histogram and scatter plot</li>' +
        '<li>Full request log (first 200 entries)</li>' +
        '<li>PASS / FAIL verdict banner (when assertions are set)</li>' +
      '</ul>' +
      '<h3>Accessing reports</h3>' +
      '<ul>' +
        '<li><strong>UI:</strong> go to the Results tab and click "HTML Report" or "Details"</li>' +
        '<li><strong>CLI:</strong> report path is printed after the run; use <code>--open-report</code> to open automatically</li>' +
      '</ul>' +
      '<h3>Export formats</h3>' +
      '<p>CLI: <code>--format html</code> (default), <code>--format json</code>, or <code>--format csv</code>.</p>' +
      '<h3>Stopped tests</h3>' +
      '<p>Clicking Stop during a run still generates a partial report from whatever data was collected up to that point.</p>'
  };

  var DOCS_BASE_URL = 'https://dprakash2101.github.io/overload/';

  var TOPIC_DOC_LINKS = {
    'getting-started': 'getting-started.html',
    'collections': 'collections.html',
    'csv-data': 'collections.html',
    'auth': 'authentication.html',
    'patterns': 'test-patterns.html',
    'assertions': 'assertions.html',
    'cicd': 'ci-cd.html',
    'reports': 'reports.html'
  };

  function render(container) {
    container.innerHTML =
      '<h1 class="page-title">Documentation</h1>' +
      '<p class="page-desc">Help and reference for Overload &mdash; <a href="' + DOCS_BASE_URL + '" target="_blank" rel="noopener" style="color:var(--link,#1d5fa8)">Full documentation &rarr;</a></p>' +
      '<div style="display:flex;gap:16px;align-items:flex-start">' +
        '<div id="docsSidebar" style="min-width:160px;max-width:180px;flex-shrink:0">' +
          '<div class="card" style="padding:8px">' +
            TOPICS.map(function(t) {
              return '<div class="doc-topic" data-topic="' + t.id + '" style="padding:8px 10px;border-radius:4px;cursor:pointer;font-size:13px">' + t.label + '</div>';
            }).join('') +
          '</div>' +
        '</div>' +
        '<div id="docsContent" class="card" style="flex:1;min-width:0"></div>' +
      '</div>';

    container.querySelectorAll('.doc-topic').forEach(function(el) {
      el.addEventListener('click', function() { showTopic(el.dataset.topic); });
    });

    container.addEventListener('click', function(e) {
      var link = e.target.closest('.doc-link');
      if (link && link.dataset.topic) {
        e.preventDefault();
        showTopic(link.dataset.topic);
      }
    });

    showTopic(currentTopic);
  }

  function showTopic(id) {
    if (!CONTENT[id]) return;
    currentTopic = id;
    var el = document.getElementById('docsContent');
    if (el) {
      var docLink = TOPIC_DOC_LINKS[id];
      var linkHtml = docLink
        ? '<p style="margin-top:16px;padding-top:12px;border-top:1px solid var(--border,#e0e0e0)">' +
          '<a href="' + DOCS_BASE_URL + docLink + '" target="_blank" rel="noopener" style="color:var(--link,#1d5fa8)">' +
          'Read full documentation &rarr;</a></p>'
        : '';
      el.innerHTML = '<div style="padding:4px 8px">' + CONTENT[id] + linkHtml + '</div>';
    }
    document.querySelectorAll('.doc-topic').forEach(function(t) {
      t.style.background = t.dataset.topic === id ? 'var(--sel,#e8ecff)' : '';
      t.style.fontWeight = t.dataset.topic === id ? '600' : '';
    });
  }

  return { render: render };
})();
