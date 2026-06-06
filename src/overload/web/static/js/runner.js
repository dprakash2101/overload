window.RunnerPage = (function() {
  var selectedType = null;
  var config = {};
  var isRunning = false;
  var currentRunId = null;
  var rpsHistory = [];
  var lastLogIdx = -1;
  var logEntries = [];
  var prevProgress = { completed: 0, time: 0 };
  var elapsedTimer = null;
  var elapsedBase = 0;
  var elapsedStartWall = 0;

  var TEST_TYPES = [
    { id: 'load', name: 'Load Test', desc: 'Sustained traffic at target RPS with ramp up/down', shape: [1,3,5,8,10,10,10,10,10,10,8,5,3] },
    { id: 'stress', name: 'Stress Test', desc: 'Increasing load until the system breaks', shape: [1,2,3,4,5,6,7,8,9,10,11,12,13] },
    { id: 'spike', name: 'Spike Test', desc: 'Sudden traffic surge to test recovery', shape: [3,3,3,3,13,13,3,3,3,3,3,3,3] },
    { id: 'soak', name: 'Soak Test', desc: 'Steady load over long duration to find leaks', shape: [5,5,5,5,5,5,5,5,5,5,5,5,5] },
    { id: 'ramp', name: 'Ramp Test', desc: 'Gradually increase RPS to find optimal point', shape: [1,2,3,4,5,6,7,8,9,10,11,12,13] },
    { id: 'burst', name: 'Burst Test', desc: 'Fire all requests at once', shape: [13,13,0,0,0,0,0,0,0,0,0,0,0] },
    { id: 'breakpoint', name: 'Breakpoint Test', desc: 'Binary search for exact degradation threshold', shape: [3,5,8,6,7,7,7,7,7,7,7,7,7] },
    { id: 'custom', name: 'Custom Test', desc: 'Define your own load stages', shape: [2,5,5,10,10,10,7,7,3,3,1,1,0] },
    { id: 'ratelimit', name: 'Rate Limit', desc: 'Verify API rate limiting works as expected', shape: [5,5,5,5,5,5,0,0,10,10,10,10,10] },
    { id: 'sequential', name: 'Sequential', desc: 'Run collection in order, N iterations', shape: [3,3,3,3,3,3,3,3,3,3,3,3,3] }
  ];

  var ASSERTION_METRICS = [
    { value: 'p50_latency_ms', label: 'P50 Latency (ms)' },
    { value: 'p95_latency_ms', label: 'P95 Latency (ms)' },
    { value: 'p99_latency_ms', label: 'P99 Latency (ms)' },
    { value: 'max_latency_ms', label: 'Max Latency (ms)' },
    { value: 'mean_latency_ms', label: 'Mean Latency (ms)' },
    { value: 'error_rate_pct', label: 'Error Rate (%)' },
    { value: 'success_rate_pct', label: 'Success Rate (%)' },
    { value: 'avg_rps', label: 'Avg RPS' },
    { value: 'total_requests', label: 'Total Requests' },
    { value: 'rate_limited_count', label: 'Rate Limited Count' }
  ];
  var ASSERTION_OPERATORS = ['<', '<=', '>', '>=', '=='];
  var thresholds = [];

  var CONFIG_FIELDS = {
    load: [
      { key: 'target_rps', label: 'Target requests/sec', type: 'range', min: 1, max: 1000, value: 50, tip: 'Sustained RPS during the hold phase. Start low and increase.' },
      { key: 'ramp_up_seconds', label: 'Ramp up duration', type: 'range', min: 0, max: 300, value: 30, unit: 's', tip: 'Time to gradually reach target RPS. Longer = more realistic.' },
      { key: 'hold_duration_seconds', label: 'Hold duration', type: 'range', min: 10, max: 3600, value: 300, unit: 's', tip: 'How long to sustain the target RPS. 300s = 5 min.' },
      { key: 'ramp_down_seconds', label: 'Ramp down duration', type: 'range', min: 0, max: 60, value: 10, unit: 's', tip: 'Gradual cooldown period after hold.' }
    ],
    stress: [
      { key: 'start_rps', label: 'Start requests/sec', type: 'range', min: 1, max: 100, value: 10, tip: 'Initial load level. Usually your known baseline.' },
      { key: 'step_rps', label: 'Step increase', type: 'range', min: 5, max: 100, value: 20, tip: 'RPS added each step. Smaller = more precise breakpoint.' },
      { key: 'step_duration_seconds', label: 'Step duration', type: 'range', min: 5, max: 120, value: 30, unit: 's', tip: 'How long to hold each step before increasing.' },
      { key: 'max_rps', label: 'Max requests/sec', type: 'range', min: 50, max: 2000, value: 500, tip: 'Upper limit. Test stops here even if no failure.' },
      { key: 'failure_threshold_pct', label: 'Failure threshold', type: 'range', min: 10, max: 100, value: 80, unit: '%', tip: 'Stop when error rate exceeds this percentage.' }
    ],
    spike: [
      { key: 'baseline_rps', label: 'Baseline requests/sec', type: 'range', min: 1, max: 200, value: 20, tip: 'Normal traffic level before and after the spike.' },
      { key: 'spike_rps', label: 'Spike requests/sec', type: 'range', min: 10, max: 2000, value: 200, tip: 'Traffic during the spike. Usually 5-10x baseline.' },
      { key: 'baseline_duration_seconds', label: 'Baseline duration', type: 'range', min: 10, max: 300, value: 60, unit: 's', tip: 'Warm-up period at baseline before spike hits.' },
      { key: 'spike_duration_seconds', label: 'Spike duration', type: 'range', min: 5, max: 120, value: 30, unit: 's', tip: 'How long the spike lasts.' },
      { key: 'recovery_duration_seconds', label: 'Recovery monitoring', type: 'range', min: 10, max: 300, value: 60, unit: 's', tip: 'Time to monitor recovery after spike ends.' }
    ],
    soak: [
      { key: 'soak_rps', label: 'Requests/sec', type: 'range', min: 1, max: 200, value: 30, tip: 'Steady RPS. Use your normal expected traffic level.' },
      { key: 'soak_duration_seconds', label: 'Duration', type: 'range', min: 60, max: 7200, value: 1800, unit: 's', tip: 'How long to sustain. 1800s = 30 min. Longer finds more leaks.' }
    ],
    ramp: [
      { key: 'ramp_start_rps', label: 'Start requests/sec', type: 'range', min: 1, max: 100, value: 10, tip: 'Starting RPS. Usually your minimum expected load.' },
      { key: 'ramp_end_rps', label: 'End requests/sec', type: 'range', min: 10, max: 1000, value: 200, tip: 'Maximum RPS to reach.' },
      { key: 'step_rps', label: 'Step size', type: 'range', min: 1, max: 50, value: 10, tip: 'RPS increment at each step.' },
      { key: 'step_duration_seconds', label: 'Step duration', type: 'range', min: 5, max: 60, value: 15, unit: 's', tip: 'Hold time at each step to measure performance.' }
    ],
    burst: [
      { key: 'total_requests', label: 'Total requests', type: 'range', min: 10, max: 5000, value: 200, tip: 'Number of requests to fire simultaneously.' }
    ],
    breakpoint: [
      { key: 'start_rps', label: 'Start requests/sec', type: 'range', min: 1, max: 100, value: 10, tip: 'Lower bound for binary search.' },
      { key: 'max_rps', label: 'Max requests/sec', type: 'range', min: 50, max: 2000, value: 500, tip: 'Upper bound for binary search.' },
      { key: 'precision_rps', label: 'Precision', type: 'range', min: 1, max: 20, value: 5, tip: 'How close to the exact breakpoint. Lower = more precise but slower.' },
      { key: 'latency_threshold_ms', label: 'Latency threshold', type: 'range', min: 100, max: 10000, value: 2000, unit: 'ms', tip: 'P95 latency above this = degradation detected.' },
      { key: 'error_threshold_pct', label: 'Error threshold', type: 'range', min: 1, max: 50, value: 10, unit: '%', tip: 'Error rate above this = degradation detected.' }
    ],
    ratelimit: [
      { key: 'rate_limit_cap', label: 'Expected rate limit', type: 'range', min: 1, max: 1000, value: 60, unit: 'req/min', tip: 'Your API\'s stated rate limit in requests per minute.' }
    ],
    sequential: [
      { key: 'iterations', label: 'Iterations', type: 'range', min: 1, max: 100, value: 1, tip: 'Times to run through the full collection.' },
      { key: 'delay_ms', label: 'Delay between requests', type: 'range', min: 0, max: 5000, value: 0, unit: 'ms', tip: 'Wait time between each request.' }
    ],
    custom: []
  };

  function render(container) {
    var coll = window.OverloadApp.getCollection();
    if (!coll) {
      container.innerHTML =
        '<h1 class="page-title">Test Runner</h1>' +
        '<div class="working-dir-banner">Run <strong>overload</strong> from the directory containing your Postman collections for auto-detection.</div>' +
        '<div class="card"><p style="color:var(--mut)">Upload a collection first.</p>' +
        '<button class="btn btn-secondary" style="margin-top:12px" onclick="window.OverloadApp.navigate(\'collection\')">Go to Collection</button></div>';
      return;
    }

    container.innerHTML =
      '<h1 class="page-title">Test Runner</h1>' +
      '<p class="page-desc">Choose a test type and configure parameters</p>' +
      '<div class="test-types" id="testTypes"></div>' +
      '<div id="testConfig" style="display:none"></div>' +
      '<div id="liveDashboard" style="display:none"></div>';

    renderTestTypes();
  }

  function renderTestTypes() {
    var container = document.getElementById('testTypes');
    container.innerHTML = TEST_TYPES.map(function(tt) {
      var shapeHtml = '<div class="test-card-shape">' +
        tt.shape.map(function(h) { return '<span style="width:7%;height:' + (h * 100 / 13) + '%"></span>'; }).join('') +
        '</div>';
      return '<div class="test-card' + (selectedType === tt.id ? ' selected' : '') + '" data-type="' + tt.id + '">' +
        '<div class="test-card-name">' + tt.name + '</div>' +
        '<div class="test-card-desc">' + tt.desc + '</div>' +
        shapeHtml +
      '</div>';
    }).join('');

    container.querySelectorAll('.test-card').forEach(function(card) {
      card.addEventListener('click', function() { selectTestType(card.dataset.type); });
    });
  }

  function selectTestType(type) {
    selectedType = type;
    config = {};
    renderTestTypes();
    renderConfig();
    document.getElementById('testConfig').style.display = 'block';
  }

  function renderConfig() {
    var fields = CONFIG_FIELDS[selectedType] || [];
    var html = '<div class="card">';
    html += '<div class="card-title">Configuration</div>';

    html += '<div class="shape-preview"><div class="chart-title">Load Shape Preview</div><canvas id="shapeChart"></canvas></div>';

    if (selectedType === 'custom') {
      html += renderStagesEditor();
    } else {
      fields.forEach(function(f) {
        var val = config[f.key] !== undefined ? config[f.key] : f.value;
        config[f.key] = val;
        html += '<div class="config-row">';
        html += '<div class="config-label">' + f.label;
        if (f.tip) html += ' <span class="tooltip" data-tip="' + esc(f.tip) + '">?</span>';
        html += '</div>';
        html += '<div class="config-input">';
        html += '<input type="range" min="' + f.min + '" max="' + f.max + '" value="' + val + '" data-key="' + f.key + '" class="config-slider">';
        html += '<input type="number" min="' + f.min + '" max="' + f.max + '" value="' + val + '" data-key="' + f.key + '" class="config-number">';
        if (f.unit) html += '<span style="color:var(--mut);font-size:12px">' + f.unit + '</span>';
        html += '</div></div>';
      });
    }

    // Common settings
    html += '<button class="advanced-toggle" id="advancedToggle">&#9660; Advanced Settings</button>';
    html += '<div class="advanced-content" id="advancedContent">';
    var concurrency = config.concurrency || 20;
    var timeout = config.timeout_seconds || 30;
    config.concurrency = concurrency;
    config.timeout_seconds = timeout;
    html += '<div class="config-row"><div class="config-label">Max concurrent connections <span class="tooltip" data-tip="Number of simultaneous HTTP connections. Higher = more parallel requests.">?</span></div><div class="config-input">';
    html += '<input type="range" min="1" max="200" value="' + concurrency + '" data-key="concurrency" class="config-slider">';
    html += '<input type="number" min="1" max="200" value="' + concurrency + '" data-key="concurrency" class="config-number">';
    html += '</div></div>';
    html += '<div class="config-row"><div class="config-label">Request timeout <span class="tooltip" data-tip="Max wait time per request before marking as timeout.">?</span></div><div class="config-input">';
    html += '<input type="range" min="1" max="120" value="' + timeout + '" data-key="timeout_seconds" class="config-slider">';
    html += '<input type="number" min="1" max="120" value="' + timeout + '" data-key="timeout_seconds" class="config-number">';
    html += '<span style="color:var(--mut);font-size:12px">s</span></div></div>';

    var saveResp = config.save_responses || false;
    config.save_responses = saveResp;
    html += '<div class="save-response-row">';
    html += '<input type="checkbox" id="saveResponsesCheck" ' + (saveResp ? 'checked' : '') + '>';
    html += '<label for="saveResponsesCheck">Save response bodies <span style="color:var(--mut)">(captures first 10KB per response — useful for debugging)</span></label>';
    html += '</div>';
    html += '</div>';

    // Assertions editor
    html += '<button class="advanced-toggle" id="assertionsToggle">&#9660; Assertions (CI Thresholds)</button>';
    html += '<div class="advanced-content" id="assertionsContent">';
    html += renderAssertionsEditor();
    html += '</div>';

    html += '<div style="margin-top:20px;display:flex;gap:12px;flex-wrap:wrap">';
    html += '<button class="btn btn-primary" id="startBtn">Start Test</button>';
    html += '<button class="btn btn-secondary" id="saveConfigBtn">Save Config</button>';
    html += '<button class="btn btn-secondary" id="loadConfigBtn">Load Config</button>';
    html += '</div>';
    html += '</div>';

    document.getElementById('testConfig').innerHTML = html;

    // Bind sliders to number inputs
    document.querySelectorAll('.config-slider').forEach(function(slider) {
      var key = slider.dataset.key;
      var number = document.querySelector('.config-number[data-key="' + key + '"]');
      slider.addEventListener('input', function() {
        number.value = slider.value;
        config[key] = parseInt(slider.value);
        updateShapePreview();
      });
      number.addEventListener('input', function() {
        var val = parseInt(number.value);
        if (!isNaN(val)) {
          slider.value = val;
          config[key] = val;
          updateShapePreview();
        }
      });
    });

    document.getElementById('saveResponsesCheck').addEventListener('change', function() {
      config.save_responses = this.checked;
    });

    document.getElementById('advancedToggle').addEventListener('click', function() {
      var content = document.getElementById('advancedContent');
      content.classList.toggle('open');
      this.innerHTML = (content.classList.contains('open') ? '&#9650;' : '&#9660;') + ' Advanced Settings';
    });

    document.getElementById('startBtn').addEventListener('click', startTest);

    document.getElementById('assertionsToggle').addEventListener('click', function() {
      var content = document.getElementById('assertionsContent');
      content.classList.toggle('open');
      this.innerHTML = (content.classList.contains('open') ? '&#9650;' : '&#9660;') + ' Assertions (CI Thresholds)';
    });

    document.getElementById('saveConfigBtn').addEventListener('click', saveConfigToFile);
    document.getElementById('loadConfigBtn').addEventListener('click', loadConfigFromFile);

    bindAssertionsEditor();
    if (selectedType === 'custom') bindStagesEditor();

    setTimeout(updateShapePreview, 50);
  }

  function renderStagesEditor() {
    var stages = config.stages || [{ duration: 60, rps: 50 }, { duration: 120, rps: 100 }, { duration: 60, rps: 50 }];
    config.stages = stages;
    var html = '<div class="card-title" style="margin-top:12px">Stages</div>';
    html += '<div class="stages-list" id="stagesList">';
    stages.forEach(function(s, i) {
      html += '<div class="stage-row" data-idx="' + i + '">';
      html += '<span style="color:var(--mut);font-size:12px;width:20px">' + (i + 1) + '.</span>';
      html += '<input type="number" value="' + s.duration + '" data-field="duration" min="1" placeholder="Duration"> <span style="color:var(--mut);font-size:12px">sec at</span> ';
      html += '<input type="number" value="' + s.rps + '" data-field="rps" min="1" placeholder="RPS"> <span style="color:var(--mut);font-size:12px">req/s</span>';
      html += '<button class="stage-remove" data-idx="' + i + '">&#10005;</button>';
      html += '</div>';
    });
    html += '</div>';
    html += '<div class="stage-add" id="addStage">+ Add Stage</div>';
    var totalDur = stages.reduce(function(s, st) { return s + st.duration; }, 0);
    var totalReqs = stages.reduce(function(s, st) { return s + st.duration * st.rps; }, 0);
    html += '<div style="color:var(--mut);font-size:12px;margin-top:8px">Total: ' + totalDur + 's (' + Math.round(totalDur / 60) + 'min), ~' + totalReqs + ' requests</div>';
    return html;
  }

  function bindStagesEditor() {
    var list = document.getElementById('stagesList');
    if (!list) return;
    list.querySelectorAll('input').forEach(function(input) {
      input.addEventListener('change', function() {
        var row = input.closest('.stage-row');
        var idx = parseInt(row.dataset.idx);
        config.stages[idx][input.dataset.field] = parseInt(input.value) || 1;
        renderConfig();
        bindStagesEditor();
      });
    });
    list.querySelectorAll('.stage-remove').forEach(function(btn) {
      btn.addEventListener('click', function() {
        config.stages.splice(parseInt(btn.dataset.idx), 1);
        renderConfig();
        bindStagesEditor();
      });
    });
    var addBtn = document.getElementById('addStage');
    if (addBtn) {
      addBtn.addEventListener('click', function() {
        config.stages.push({ duration: 60, rps: 50 });
        renderConfig();
        bindStagesEditor();
      });
    }
  }

  function renderAssertionsEditor() {
    var html = '<div class="assertions-list" id="assertionsList">';
    if (!thresholds.length) {
      html += '<div style="color:var(--mut);font-size:11px;padding:6px 0">No assertions. Add one to enable pass/fail verdicts.</div>';
    }
    thresholds.forEach(function(t, i) {
      html += '<div class="stage-row" data-idx="' + i + '">';
      html += '<select data-field="metric" class="assertion-select">';
      ASSERTION_METRICS.forEach(function(m) {
        html += '<option value="' + m.value + '"' + (t.metric === m.value ? ' selected' : '') + '>' + m.label + '</option>';
      });
      html += '</select>';
      html += '<select data-field="operator" class="assertion-op">';
      ASSERTION_OPERATORS.forEach(function(op) {
        html += '<option value="' + esc(op) + '"' + (t.operator === op ? ' selected' : '') + '>' + esc(op) + '</option>';
      });
      html += '</select>';
      html += '<input type="number" value="' + t.value + '" data-field="value" min="0" step="any" placeholder="Value" class="assertion-value">';
      html += '<button class="stage-remove" data-idx="' + i + '">&#10005;</button>';
      html += '</div>';
    });
    html += '</div>';
    html += '<div class="stage-add" id="addAssertion">+ Add Assertion</div>';
    return html;
  }

  function bindAssertionsEditor() {
    var list = document.getElementById('assertionsList');
    if (!list) return;
    list.querySelectorAll('select, input').forEach(function(el) {
      el.addEventListener('change', function() {
        var row = el.closest('.stage-row');
        var idx = parseInt(row.dataset.idx);
        var field = el.dataset.field;
        if (field === 'value') {
          thresholds[idx][field] = parseFloat(el.value) || 0;
        } else {
          thresholds[idx][field] = el.value;
        }
      });
    });
    list.querySelectorAll('.stage-remove').forEach(function(btn) {
      btn.addEventListener('click', function() {
        thresholds.splice(parseInt(btn.dataset.idx), 1);
        var container = document.getElementById('assertionsContent');
        if (container) {
          container.innerHTML = renderAssertionsEditor();
          bindAssertionsEditor();
        }
      });
    });
    var addBtn = document.getElementById('addAssertion');
    if (addBtn) {
      addBtn.addEventListener('click', function() {
        thresholds.push({ metric: 'p95_latency_ms', operator: '<', value: 500 });
        var container = document.getElementById('assertionsContent');
        if (container) {
          container.innerHTML = renderAssertionsEditor();
          bindAssertionsEditor();
        }
      });
    }
  }

  function saveConfigToFile() {
    var payload = {
      test_type: selectedType,
      config: config,
      thresholds: thresholds
    };
    fetch('/api/config/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.status === 'ok') {
        App.toast('Config saved to overload.config.yaml', 'success');
      } else {
        App.toast('Error: ' + data.message, 'error');
      }
    })
    .catch(function(err) { App.toast('Save failed: ' + err.message, 'error'); });
  }

  function loadConfigFromFile() {
    fetch('/api/config/load')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.status === 'ok' && data.config) {
        var cfg = data.config;
        if (cfg.test_type) {
          selectTestType(cfg.test_type);
        }
        if (cfg.config) {
          Object.keys(cfg.config).forEach(function(k) {
            config[k] = cfg.config[k];
          });
        }
        if (cfg.thresholds && cfg.thresholds.length) {
          thresholds = cfg.thresholds.map(function(t) {
            return { metric: t.metric, operator: t.operator, value: t.value };
          });
        }
        renderConfig();
        App.toast('Config loaded from overload.config.yaml', 'success');
      } else {
        App.toast(data.message || 'No config file found', 'error');
      }
    })
    .catch(function(err) { App.toast('Load failed: ' + err.message, 'error'); });
  }

  function updateShapePreview() {
    OverloadCharts.loadShapePreview('shapeChart', selectedType, config);
  }

  function startTest() {
    var coll = window.OverloadApp.getCollection();
    if (!coll || !coll.requests.length) {
      App.toast('No collection loaded', 'error');
      return;
    }

    var payload = {
      test_type: selectedType,
      config: config,
      thresholds: thresholds
    };

    fetch('/api/test/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.status === 'ok') {
        isRunning = true;
        currentRunId = data.run_id;
        rpsHistory = [];
        logEntries = [];
        lastLogIdx = -1;
        prevProgress = { completed: 0, time: Date.now() };
        showLiveDashboard();
        startElapsedTimer();
        window.OverloadApp.subscribeToRun(currentRunId, onProgress);
      } else {
        App.toast('Error: ' + data.message, 'error');
      }
    })
    .catch(function(err) { App.toast('Failed to start: ' + err.message, 'error'); });
  }

  function showLiveDashboard() {
    document.getElementById('testConfig').style.display = 'none';
    document.getElementById('testTypes').style.display = 'none';
    var dash = document.getElementById('liveDashboard');
    dash.style.display = 'block';
    var isRateLimit = selectedType === 'ratelimit';
    var phaseInfoHtml = isRateLimit
      ? '<div id="rlPhaseInfo" class="rl-phase-info" style="background:var(--card-bg,#fff);border:1px solid var(--border,#dde1ec);border-radius:8px;padding:14px 18px;margin-bottom:14px">' +
          '<div style="font-weight:700;font-size:13px;margin-bottom:6px" id="rlPhaseTitle">Preparing...</div>' +
          '<div style="color:var(--muted,#6b7280);font-size:11px" id="rlPhaseDesc">Rate limit validation test starting</div>' +
        '</div>'
      : '';
    dash.innerHTML =
      '<div class="card">' +
        '<div class="card-title">Running: ' + selectedType.toUpperCase() + ' — ' + currentRunId + '</div>' +
        phaseInfoHtml +
        '<div class="kpi-grid" id="liveKpis">' +
          '<div class="kpi kpi-mid"><div class="kpi-label">Total</div><div class="kpi-value" id="kpiTotal">0</div></div>' +
          '<div class="kpi kpi-ok"><div class="kpi-label">Success Rate</div><div class="kpi-value" id="kpiSuccess">-</div></div>' +
          '<div class="kpi kpi-blue"><div class="kpi-label">Avg Latency</div><div class="kpi-value" id="kpiLatency">-</div></div>' +
          '<div class="kpi kpi-ok"><div class="kpi-label">Current RPS</div><div class="kpi-value" id="kpiRps">0</div></div>' +
          '<div class="kpi kpi-mid"><div class="kpi-label">Elapsed</div><div class="kpi-value" id="kpiElapsed">0s</div></div>' +
          '<div class="kpi kpi-bad"><div class="kpi-label">Errors</div><div class="kpi-value" id="kpiErrors">0</div></div>' +
        '</div>' +
        '<div class="progress-wrap">' +
          '<div class="progress-bar"><div class="progress-fill" id="progressFill" style="width:0%"></div></div>' +
          '<div class="progress-text"><span id="progressPhase">Starting...</span><span id="progressPct">0%</span></div>' +
        '</div>' +
        '<div class="chart-grid">' +
          '<div class="chart-card"><div class="chart-title">Live RPS</div><canvas id="liveRpsChart"></canvas></div>' +
          '<div class="chart-card"><div class="chart-title">Status Codes</div><canvas id="liveStatusChart"></canvas></div>' +
        '</div>' +
        '<div class="live-log" id="liveLog">' +
          '<div class="live-log-title">Request Log</div>' +
          '<div id="liveLogEntries"><div class="live-log-empty">Waiting for requests...</div></div>' +
        '</div>' +
        '<div style="margin-top:16px"><button class="btn btn-danger" id="stopBtn">Stop Test</button></div>' +
      '</div>';

    document.getElementById('stopBtn').addEventListener('click', stopTest);
  }

  function statusBadgeClass(code) {
    if (code <= 0) return 'status-0';
    if (code < 200) return 'status-1xx';
    if (code < 300) return 'status-2xx';
    if (code < 400) return 'status-3xx';
    if (code < 500) return 'status-4xx';
    return 'status-5xx';
  }

  function onProgress(data) {
    if (!data) return;

    document.getElementById('kpiTotal').textContent = data.completed_requests;
    document.getElementById('kpiRps').textContent = data.current_rps;
    document.getElementById('kpiLatency').textContent = data.avg_latency_ms ? data.avg_latency_ms + 'ms' : '-';
    document.getElementById('kpiErrors').textContent = data.error_count || 0;

    // Sync elapsed timer base to authoritative server value
    if (data.elapsed_seconds !== undefined) {
      elapsedBase = data.elapsed_seconds;
      elapsedStartWall = Date.now();
      var el = document.getElementById('kpiElapsed');
      if (el) el.textContent = data.elapsed_seconds + 's';
    }

    var total = data.total_requests || data.completed_requests;
    var successRate = data.completed_requests > 0 && data.error_count !== undefined
      ? Math.round((data.completed_requests - data.error_count) * 100 / data.completed_requests) + '%'
      : '-';
    document.getElementById('kpiSuccess').textContent = successRate;

    var pct = total > 0 ? Math.round(data.completed_requests * 100 / total) : 0;
    if (data.phase === 'complete' || (data.phase && data.phase.indexOf('complete') === 0)) pct = 100;
    var fill = document.getElementById('progressFill');
    if (fill) fill.style.width = pct + '%';
    var pctEl = document.getElementById('progressPct');
    if (pctEl) pctEl.textContent = pct + '%';
    var phaseEl = document.getElementById('progressPhase');
    if (phaseEl) phaseEl.textContent = data.phase || '';

    // Rate limit phase info
    var rlTitle = document.getElementById('rlPhaseTitle');
    var rlDesc = document.getElementById('rlPhaseDesc');
    if (rlTitle && rlDesc && data.phase) {
      var p = data.phase;
      if (p.indexOf('Phase 1') === 0) {
        rlTitle.textContent = 'Phase 1: Under Threshold';
        rlDesc.textContent = 'Sending requests at your stated rate limit to confirm normal operation';
        rlTitle.style.color = 'var(--ok,#0e8a5f)';
      } else if (p.indexOf('Cooldown') === 0) {
        rlTitle.textContent = 'Cooldown';
        rlDesc.textContent = 'Waiting for rate limiter window to reset before exceeding the limit';
        rlTitle.style.color = 'var(--muted,#6b7280)';
      } else if (p.indexOf('Phase 2') === 0) {
        rlTitle.textContent = 'Phase 2: Exceeding Threshold';
        rlDesc.textContent = 'Sending requests above your rate limit — expecting 429 responses';
        rlTitle.style.color = 'var(--bad,#c0392b)';
      } else if (p === 'complete') {
        rlTitle.textContent = 'Test Complete';
        rlDesc.textContent = 'Rate limit validation finished — check results below';
        rlTitle.style.color = 'var(--blue,#1d5fa8)';
      }
    }

    // Live RPS chart
    if (data.current_rps > 0 || rpsHistory.length > 0) {
      rpsHistory.push({ t: Math.round(data.elapsed_seconds), rps: data.current_rps });
      if (rpsHistory.length > 120) rpsHistory = rpsHistory.slice(-120);
      OverloadCharts.liveRpsLine('liveRpsChart', rpsHistory);
    }

    // Status doughnut
    if (data.status_codes) {
      OverloadCharts.statusDoughnut('liveStatusChart', data.status_codes);
    }

    // Live log
    if (data.recent_results && data.recent_results.length) {
      var container = document.getElementById('liveLogEntries');
      var empty = container.querySelector('.live-log-empty');
      if (empty) empty.remove();

      data.recent_results.forEach(function(r) {
        if (r.idx <= lastLogIdx) return;
        lastLogIdx = r.idx;
        logEntries.push(r);

        var entry = document.createElement('div');
        entry.className = 'live-log-entry';
        var methodClass = 'method-' + r.method;
        entry.innerHTML =
          '<span class="log-idx">' + (r.idx + 1) + '</span>' +
          '<span class="log-method ' + methodClass + '">' + r.method + '</span>' +
          '<span class="status-badge ' + statusBadgeClass(r.status) + '">' + r.status + '</span>' +
          '<span class="log-name">' + esc(r.name) + '</span>' +
          '<span class="log-latency">' + r.latency + 'ms</span>';
        if (r.error) {
          entry.innerHTML += '<span style="color:var(--bad);font-size:10px;margin-left:4px">' + esc(r.error) + '</span>';
        }
        container.appendChild(entry);
      });

      // Keep only last 100 entries in DOM
      while (container.children.length > 100) {
        container.removeChild(container.firstChild);
      }

      // Auto-scroll to bottom
      var logPanel = document.getElementById('liveLog');
      if (logPanel) logPanel.scrollTop = logPanel.scrollHeight;
    }

    // Test complete
    if (data.phase === 'complete' || (data.phase && data.phase.indexOf('complete') === 0)) {
      isRunning = false;
      stopElapsedTimer();
      var stopBtn = document.getElementById('stopBtn');
      if (stopBtn) {
        stopBtn.textContent = 'View Results';
        stopBtn.className = 'btn btn-primary';
        stopBtn.onclick = function() { window.OverloadApp.navigate('results'); };
      }
      App.toast('Test complete! ' + data.completed_requests + ' requests.', 'success');

      if (thresholds.length && currentRunId) {
        fetch('/api/runs/' + currentRunId + '/data')
          .then(function(r) { return r.json(); })
          .then(function(runData) {
            if (runData.verdict) {
              var v = runData.verdict;
              var banner = document.createElement('div');
              banner.className = 'verdict-banner ' + (v.passed ? 'verdict-pass' : 'verdict-fail');
              var icon = v.passed ? '&#x2705;' : '&#x274C;';
              var html = '<div class="verdict-icon">' + icon + '</div>';
              html += '<div class="verdict-body"><div class="verdict-title">' + (v.passed ? 'PASS' : 'FAIL') + '</div>';
              html += '<div class="verdict-details">';
              v.results.forEach(function(r) {
                var mark = r.passed ? '<span style="color:var(--ok)">&#10003;</span>' : '<span style="color:var(--bad)">&#10007;</span>';
                html += '<div>' + mark + ' ' + esc(r.metric) + ': ' + r.actual + ' ' + esc(r.operator) + ' ' + r.expected + '</div>';
              });
              html += '</div></div>';
              banner.innerHTML = html;
              var dash = document.getElementById('liveDashboard');
              if (dash) dash.querySelector('.card').prepend(banner);
            }
          })
          .catch(function() {});
      }
    }
  }

  function startElapsedTimer() {
    stopElapsedTimer();
    elapsedBase = 0;
    elapsedStartWall = Date.now();
    elapsedTimer = setInterval(function() {
      var el = document.getElementById('kpiElapsed');
      if (!el) { stopElapsedTimer(); return; }
      var secs = elapsedBase + Math.round((Date.now() - elapsedStartWall) / 1000);
      el.textContent = secs + 's';
    }, 1000);
  }

  function stopElapsedTimer() {
    if (elapsedTimer) {
      clearInterval(elapsedTimer);
      elapsedTimer = null;
    }
  }

  function stopTest() {
    stopElapsedTimer();
    fetch('/api/test/stop', { method: 'POST' })
      .then(function() { App.toast('Stop signal sent', 'success'); })
      .catch(function(err) { App.toast('Error: ' + err.message, 'error'); });
  }

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function reset() {
    isRunning = false;
    currentRunId = null;
    rpsHistory = [];
    logEntries = [];
    lastLogIdx = -1;
    thresholds = [];
    stopElapsedTimer();
  }

  return { render: render, reset: reset };
})();
