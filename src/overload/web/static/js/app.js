window.OverloadApp = (function() {
  var currentPage = 'collection';
  var collection = null;
  var ws = null;
  var progressCallback = null;

  function init() {
    document.querySelectorAll('.nav-link').forEach(function(link) {
      link.addEventListener('click', function(e) {
        e.preventDefault();
        navigate(link.dataset.page);
      });
    });
    navigate('collection');
  }

  function navigate(page) {
    currentPage = page;
    document.querySelectorAll('.nav-link').forEach(function(link) {
      link.classList.toggle('active', link.dataset.page === page);
    });

    OverloadCharts.destroyAll();

    var content = document.getElementById('content');
    switch (page) {
      case 'collection':
        CollectionPage.render(content);
        break;
      case 'runner':
        RunnerPage.render(content);
        break;
      case 'results':
        renderResults(content);
        break;
    }
  }

  function setCollection(coll) { collection = coll; }
  function getCollection() { return collection; }

  function connectWs() {
    if (ws && ws.readyState === WebSocket.OPEN) return;
    var protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(protocol + '//' + window.location.host + '/ws');
    ws.onopen = function() { console.log('WebSocket connected'); };
    ws.onmessage = function(e) {
      try {
        var msg = JSON.parse(e.data);
        if (msg.type === 'progress' && progressCallback) {
          progressCallback(msg.data);
        }
      } catch (err) { console.error('WS parse error:', err); }
    };
    ws.onclose = function() {
      console.log('WebSocket disconnected, reconnecting in 2s...');
      setTimeout(connectWs, 2000);
    };
    ws.onerror = function() { ws.close(); };
  }

  function subscribeToRun(runId, callback) {
    progressCallback = callback;
    connectWs();
    var waitForOpen = function() {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'subscribe', run_id: runId }));
      } else {
        setTimeout(waitForOpen, 100);
      }
    };
    waitForOpen();
  }

  function renderResults(container) {
    container.innerHTML =
      '<h1 class="page-title">Results</h1>' +
      '<p class="page-desc">View test results and download reports</p>' +
      '<div id="resultsList"><p style="color:var(--mut)">Loading...</p></div>';

    fetch('/api/runs')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var runs = data.runs || [];
        if (!runs.length) {
          document.getElementById('resultsList').innerHTML = '<div class="card"><p style="color:var(--mut)">No test runs yet. Go to Test Runner to start one.</p></div>';
          return;
        }

        var html = '<div class="card"><table class="runs-table"><thead><tr><th>Run ID</th><th>Test Type</th><th>Status</th><th>Verdict</th><th>Total</th><th>Success</th><th>Errors</th><th>Avg RPS</th><th>Actions</th></tr></thead><tbody>';
        runs.reverse().forEach(function(run) {
          var statusClass = run.status === 'complete' ? 'complete' : run.status === 'stopped' ? 'complete' : run.status === 'error' ? 'error' : 'running';
          var verdictBadge = '-';
          if (run.verdict === true) verdictBadge = '<span class="verdict-badge verdict-badge-pass">PASS</span>';
          else if (run.verdict === false) verdictBadge = '<span class="verdict-badge verdict-badge-fail">FAIL</span>';
          html += '<tr>' +
            '<td><span class="run-status ' + statusClass + '"></span>' + esc(run.run_id) + '</td>' +
            '<td>' + esc(run.test_type || '-') + '</td>' +
            '<td>' + esc(run.status || '-') + '</td>' +
            '<td>' + verdictBadge + '</td>' +
            '<td>' + (run.total || '-') + '</td>' +
            '<td>' + (run.ok || '-') + '</td>' +
            '<td>' + (run.errors || '-') + '</td>' +
            '<td>' + (run.avg_rps || '-') + '</td>' +
            '<td>';
          if (run.status === 'complete' || run.status === 'stopped') {
            html += '<a href="/api/runs/' + run.run_id + '/report" target="_blank" class="btn btn-secondary" style="padding:4px 10px;font-size:11px">HTML Report</a> ';
            html += '<button class="btn btn-secondary view-details" data-run="' + run.run_id + '" style="padding:4px 10px;font-size:11px">Details</button>';
          }
          html += '</td></tr>';
        });
        html += '</tbody></table></div>';
        html += '<div id="runDetailView"></div>';

        document.getElementById('resultsList').innerHTML = html;

        document.querySelectorAll('.view-details').forEach(function(btn) {
          btn.addEventListener('click', function() { showRunDetail(btn.dataset.run); });
        });
      })
      .catch(function(err) {
        document.getElementById('resultsList').innerHTML = '<div class="card"><p style="color:var(--bad)">Error loading runs: ' + esc(err.message) + '</p></div>';
      });
  }

  function showRunDetail(runId) {
    fetch('/api/runs/' + runId + '/data')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (!data.stats) {
          document.getElementById('runDetailView').innerHTML = '<div class="card"><p style="color:var(--mut)">No data available</p></div>';
          return;
        }
        var d = data.stats;
        var html = '<div class="card"><div class="card-title">Run: ' + runId + ' — ' + (data.test_type || '') + '</div>';

        // Verdict banner
        if (data.verdict) {
          var v = data.verdict;
          html += '<div class="verdict-banner ' + (v.passed ? 'verdict-pass' : 'verdict-fail') + '">';
          html += '<div class="verdict-icon">' + (v.passed ? '&#x2705;' : '&#x274C;') + '</div>';
          html += '<div class="verdict-body"><div class="verdict-title">' + (v.passed ? 'PASS' : 'FAIL') + '</div>';
          html += '<div class="verdict-details">';
          v.results.forEach(function(r) {
            var mark = r.passed ? '<span style="color:var(--ok)">&#10003;</span>' : '<span style="color:var(--bad)">&#10007;</span>';
            html += '<div>' + mark + ' ' + esc(r.metric) + ': ' + r.actual + ' ' + esc(r.operator) + ' ' + r.expected + '</div>';
          });
          html += '</div></div></div>';
        }

        // KPIs
        html += '<div class="kpi-grid">' +
          '<div class="kpi kpi-mid"><div class="kpi-label">Total</div><div class="kpi-value">' + d.total + '</div></div>' +
          '<div class="kpi kpi-ok"><div class="kpi-label">Successful</div><div class="kpi-value">' + d.ok + '</div></div>' +
          '<div class="kpi kpi-bad"><div class="kpi-label">Errors</div><div class="kpi-value">' + d.errors + '</div></div>' +
          '<div class="kpi kpi-blue"><div class="kpi-label">Avg RPS</div><div class="kpi-value">' + d.avg_rps + '</div></div>' +
          '<div class="kpi kpi-mid"><div class="kpi-label">Duration</div><div class="kpi-value">' + d.duration_seconds + 's</div></div>' +
          '<div class="kpi kpi-ok"><div class="kpi-label">P95 Latency</div><div class="kpi-value">' + d.latency.p95 + 'ms</div></div>' +
        '</div>';

        // Charts
        html += '<div class="chart-grid">' +
          '<div class="chart-card"><div class="chart-title">Requests per Second</div><canvas id="detailRps"></canvas></div>' +
          '<div class="chart-card"><div class="chart-title">Status Distribution</div><canvas id="detailStatus"></canvas></div>' +
          '<div class="chart-card"><div class="chart-title">Latency Histogram</div><canvas id="detailLatHist"></canvas></div>' +
          '<div class="chart-card"><div class="chart-title">Timeline</div><canvas id="detailTimeline"></canvas></div>' +
        '</div>';

        // Log
        if (d.request_log && d.request_log.length) {
          html += '<div class="card-title" style="margin-top:16px">Request Log (first 200)</div>';
          html += '<div style="overflow-x:auto"><table class="log-table"><thead><tr><th>#</th><th>Time</th><th>Status</th><th>Latency</th><th>Method</th><th>Request</th></tr></thead><tbody>';
          d.request_log.slice(0, 200).forEach(function(r, i) {
            var statusClass;
            if (r.status <= 0) statusClass = 'status-0';
            else if (r.status < 200) statusClass = 'status-1xx';
            else if (r.status < 300) statusClass = 'status-2xx';
            else if (r.status < 400) statusClass = 'status-3xx';
            else if (r.status < 500) statusClass = 'status-4xx';
            else statusClass = 'status-5xx';
            html += '<tr><td style="color:var(--mut)">' + (i + 1) + '</td>' +
              '<td>' + r.timestamp + 's</td>' +
              '<td><span class="status-badge ' + statusClass + '">' + r.status + '</span></td>' +
              '<td>' + r.latency_ms + 'ms</td>' +
              '<td>' + esc(r.method) + '</td>' +
              '<td>' + esc(r.request_name) + '</td></tr>';
            if (r.response_body) {
              html += '<tr><td></td><td colspan="5"><pre style="background:var(--sur2);padding:6px 10px;border-radius:3px;font-size:10px;max-height:120px;overflow:auto;white-space:pre-wrap;word-break:break-all">' + esc(r.response_body.substring(0, 2000)) + '</pre></td></tr>';
            }
          });
          if (d.request_log.length > 200) {
            html += '<tr><td colspan="6" style="text-align:center;color:var(--mut)">Showing 200 of ' + d.request_log.length + '</td></tr>';
          }
          html += '</tbody></table></div>';
        }

        html += '</div>';
        document.getElementById('runDetailView').innerHTML = html;

        requestAnimationFrame(function() {
          OverloadCharts.rpsBarChart('detailRps', d.per_second);
          OverloadCharts.statusDoughnut('detailStatus', d.status_codes);
          OverloadCharts.latencyHistogram('detailLatHist', d.timeline);
          OverloadCharts.timelineScatter('detailTimeline', d.timeline);
        });
      })
      .catch(function(err) {
        document.getElementById('runDetailView').innerHTML = '<div class="card"><p style="color:var(--bad)">Error: ' + esc(err.message) + '</p></div>';
      });
  }

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // Toast notification
  window.App = window.App || {};
  App.toast = function(msg, type) {
    var existing = document.querySelector('.toast');
    if (existing) existing.remove();
    var el = document.createElement('div');
    el.className = 'toast ' + (type || '');
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(function() { el.remove(); }, 4000);
  };

  Chart.defaults.color = '#6b7280';
  Chart.defaults.borderColor = '#e5e7eb';
  Chart.defaults.font.size = 10;
  Chart.defaults.font.family = 'ui-monospace,monospace';

  document.addEventListener('DOMContentLoaded', init);

  return {
    navigate: navigate,
    setCollection: setCollection,
    getCollection: getCollection,
    subscribeToRun: subscribeToRun
  };
})();
