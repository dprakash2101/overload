window.OverloadCharts = (function() {
  var chartInstances = {};

  function destroyChart(id) {
    if (chartInstances[id]) {
      chartInstances[id].destroy();
      delete chartInstances[id];
    }
  }

  function createChart(id, config) {
    var el = document.getElementById(id);
    if (!el) return null;
    destroyChart(id);
    var chart = new Chart(el, config);
    chartInstances[id] = chart;
    return chart;
  }

  var colors = {
    ok: 'rgba(14,138,95,0.7)',
    okBg: 'rgba(14,138,95,0.1)',
    bad: 'rgba(192,57,43,0.7)',
    badBg: 'rgba(192,57,43,0.1)',
    mid: 'rgba(183,96,10,0.7)',
    blue: 'rgba(29,95,168,0.7)',
    purple: 'rgba(124,58,237,0.7)',
    grid: '#e5e7eb',
    text: '#6b7280'
  };

  function statusColor(code) {
    if (code <= 0) return '#9ca3af';
    if (code < 200) return '#6366f1';
    if (code < 300) return colors.ok;
    if (code < 400) return colors.blue;
    if (code < 500) return colors.mid;
    return colors.bad;
  }

  function rpsBarChart(id, perSecond) {
    if (!perSecond || !perSecond.length) return;

    var data = perSecond;
    var maxSec = perSecond[perSecond.length - 1].second;
    if (maxSec > 120) {
      var bucketSz = maxSec > 600 ? 10 : 5;
      var agg = {};
      perSecond.forEach(function(r) {
        var k = Math.floor(r.second / bucketSz) * bucketSz;
        if (!agg[k]) agg[k] = { second: k, ok: 0, rate_limited: 0, client_errors: 0, server_errors: 0, conn_errors: 0 };
        agg[k].ok += r.ok;
        agg[k].rate_limited += r.rate_limited;
        agg[k].client_errors += (r.client_errors || 0);
        agg[k].server_errors += (r.server_errors || 0);
        agg[k].conn_errors += (r.conn_errors || 0);
      });
      data = Object.keys(agg).sort(function(a, b) { return a - b; }).map(function(k) { return agg[k]; });
    }

    createChart(id, {
      type: 'bar',
      data: {
        labels: data.map(function(r) { return fmtTime(r.second); }),
        datasets: [
          { label: '2xx', data: data.map(function(r) { return r.ok; }), backgroundColor: colors.ok, borderRadius: 2 },
          { label: '4xx', data: data.map(function(r) { return r.client_errors || 0; }), backgroundColor: colors.mid, borderRadius: 2 },
          { label: '429', data: data.map(function(r) { return r.rate_limited; }), backgroundColor: colors.purple, borderRadius: 2 },
          { label: '5xx', data: data.map(function(r) { return r.server_errors || 0; }), backgroundColor: colors.bad, borderRadius: 2 },
          { label: 'Err', data: data.map(function(r) { return r.conn_errors || 0; }), backgroundColor: '#9ca3af', borderRadius: 2 }
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { color: colors.text } } },
        scales: {
          x: { stacked: true, grid: { color: colors.grid }, ticks: { maxTicksLimit: 20 } },
          y: { stacked: true, grid: { color: colors.grid } }
        }
      }
    });
  }

  function statusDoughnut(id, statusCodes) {
    if (!statusCodes || !Object.keys(statusCodes).length) return;
    var labels = Object.keys(statusCodes).sort(function(a, b) { return Number(a) - Number(b); });
    var values = labels.map(function(k) { return statusCodes[k]; });
    var bgColors = labels.map(function(k) { return statusColor(Number(k)); });
    createChart(id, {
      type: 'doughnut',
      data: { labels: labels, datasets: [{ data: values, backgroundColor: bgColors, borderWidth: 1, borderColor: '#fff', hoverOffset: 4 }] },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: '65%',
        plugins: { legend: { position: 'right', labels: { color: colors.text, padding: 10 } } }
      }
    });
  }

  var LATENCY_BUCKETS = [10, 25, 50, 100, 200, 300, 500, 750, 1000, 2000, 5000];

  function latencyHistogram(id, timeline) {
    if (!timeline || !timeline.length) return;
    var lats = timeline.map(function(r) { return r.latency_ms; }).filter(function(v) { return v >= 0 && v < 60000; });
    if (!lats.length) return;

    var maxLat = Math.max.apply(null, lats);
    var buckets = LATENCY_BUCKETS.filter(function(b) { return b <= maxLat * 1.2; });
    if (!buckets.length) buckets = [10, 25, 50];
    var labels = [];
    var counts = [];
    var prev = 0;
    for (var i = 0; i < buckets.length; i++) {
      var b = buckets[i];
      var label = prev === 0 ? '<' + b + 'ms' : prev + '-' + b + 'ms';
      var count = 0;
      for (var j = 0; j < lats.length; j++) {
        if (lats[j] >= prev && lats[j] < b) count++;
      }
      labels.push(label);
      counts.push(count);
      prev = b;
    }
    var overCount = 0;
    for (var k = 0; k < lats.length; k++) {
      if (lats[k] >= prev) overCount++;
    }
    if (overCount > 0) {
      labels.push('>' + prev + 'ms');
      counts.push(overCount);
    }

    var barColors = counts.map(function(_, idx) {
      var ratio = idx / Math.max(labels.length - 1, 1);
      if (ratio < 0.5) return colors.ok;
      if (ratio < 0.75) return colors.mid;
      return colors.bad;
    });

    createChart(id, {
      type: 'bar',
      data: { labels: labels, datasets: [{ label: 'Requests', data: counts, backgroundColor: barColors, borderRadius: 3 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function(ctx) {
                var total = lats.length;
                var pct = total > 0 ? (ctx.raw * 100 / total).toFixed(1) : 0;
                return ctx.raw + ' requests (' + pct + '%)';
              }
            }
          }
        },
        scales: {
          x: { grid: { display: false }, ticks: { maxRotation: 45, font: { size: 10 } } },
          y: { grid: { color: colors.grid }, title: { display: true, text: 'Count', color: colors.text } }
        }
      }
    });
  }

  function fmtTime(sec) {
    if (sec < 60) return Math.round(sec * 10) / 10 + 's';
    if (sec < 3600) return Math.round(sec / 6) / 10 + 'm';
    return Math.round(sec / 360) / 10 + 'h';
  }

  function fmtLat(ms) {
    if (ms < 1000) return Math.round(ms) + 'ms';
    return (Math.round(ms / 100) / 10) + 's';
  }

  function timelineScatter(id, timeline) {
    if (!timeline || !timeline.length) return;
    var n = timeline.length;
    var maxT = Math.max(timeline[n - 1].timestamp, 0.1);

    if (n <= 50) {
      var pts = timeline.map(function(r) { return { x: r.timestamp, y: r.latency_ms }; });
      createChart(id, {
        type: 'line',
        data: {
          labels: timeline.map(function(r) { return fmtTime(r.timestamp); }),
          datasets: [{
            label: 'Latency',
            data: timeline.map(function(r) { return Math.round(r.latency_ms * 10) / 10; }),
            borderColor: colors.ok, backgroundColor: colors.okBg,
            fill: true, tension: 0.3, pointRadius: n < 20 ? 3 : 1, borderWidth: 2,
            pointBackgroundColor: timeline.map(function(r) {
              if (r.status <= 0) return '#9ca3af';
              if (r.status < 300) return colors.ok;
              if (r.status < 400) return colors.blue;
              if (r.status === 429) return colors.purple;
              if (r.status < 500) return colors.mid;
              return colors.bad;
            })
          }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: { callbacks: { label: function(ctx) { var r = timeline[ctx.dataIndex]; return r.status + ' — ' + fmtLat(r.latency_ms); } } }
          },
          scales: {
            x: { title: { display: true, text: 'Time', color: colors.text }, grid: { color: colors.grid } },
            y: { title: { display: true, text: 'Latency', color: colors.text }, grid: { color: colors.grid }, beginAtZero: true,
              ticks: { callback: function(v) { return fmtLat(v); } } }
          }
        }
      });
      return;
    }

    var bucketCount = Math.min(80, Math.max(15, Math.ceil(maxT)));
    var bucketSize = maxT / bucketCount || 1;
    var bkts = [];
    for (var b = 0; b < bucketCount; b++) bkts.push({ lats: [] });
    timeline.forEach(function(r) {
      var bi = Math.min(Math.floor(r.timestamp / bucketSize), bucketCount - 1);
      bkts[bi].lats.push(r.latency_ms);
    });

    var labels = [], avgData = [], p50Data = [], p95Data = [];
    for (var i = 0; i < bucketCount; i++) {
      labels.push(fmtTime((i + 0.5) * bucketSize));
      var sl = bkts[i].lats.slice().sort(function(a, b) { return a - b; });
      if (!sl.length) { avgData.push(null); p50Data.push(null); p95Data.push(null); continue; }
      var sum = 0; sl.forEach(function(v) { sum += v; });
      avgData.push(Math.round(sum / sl.length));
      p50Data.push(Math.round(sl[Math.floor(sl.length * 0.5)]));
      p95Data.push(Math.round(sl[Math.min(Math.floor(sl.length * 0.95), sl.length - 1)]));
    }

    createChart(id, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          { label: 'Avg', data: avgData, borderColor: colors.ok, backgroundColor: colors.okBg, fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 },
          { label: 'P50', data: p50Data, borderColor: colors.blue, tension: 0.3, pointRadius: 0, borderWidth: 1.5, borderDash: [4, 2] },
          { label: 'P95', data: p95Data, borderColor: colors.bad, tension: 0.3, pointRadius: 0, borderWidth: 1.5, borderDash: [4, 2] }
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false, spanGaps: true,
        plugins: { legend: { labels: { color: colors.text } } },
        scales: {
          x: { title: { display: true, text: 'Time', color: colors.text }, grid: { color: colors.grid }, ticks: { maxTicksLimit: 12 } },
          y: { title: { display: true, text: 'Latency', color: colors.text }, grid: { color: colors.grid }, beginAtZero: true,
            ticks: { callback: function(v) { return fmtLat(v); } } }
        }
      }
    });
  }

  function loadShapePreview(id, testType, config) {
    var points = generateShapePoints(testType, config);
    if (!points.length) return;
    createChart(id, {
      type: 'line',
      data: {
        labels: points.map(function(p) { return p.t + 's'; }),
        datasets: [{
          label: 'RPS',
          data: points.map(function(p) { return p.rps; }),
          borderColor: colors.ok,
          backgroundColor: colors.okBg,
          fill: true, tension: 0.2, pointRadius: 0
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { color: colors.grid }, ticks: { maxTicksLimit: 8 } },
          y: { grid: { color: colors.grid }, beginAtZero: true, title: { display: true, text: 'req/s', color: colors.text } }
        }
      }
    });
  }

  function liveRpsLine(id, rpsData) {
    if (!rpsData || !rpsData.length) return;

    var existing = chartInstances[id];
    if (existing && existing.data) {
      existing.data.labels = rpsData.map(function(p) { return p.t + 's'; });
      existing.data.datasets[0].data = rpsData.map(function(p) { return p.rps; });
      existing.update('none');
      return;
    }

    createChart(id, {
      type: 'line',
      data: {
        labels: rpsData.map(function(p) { return p.t + 's'; }),
        datasets: [{
          label: 'RPS',
          data: rpsData.map(function(p) { return p.rps; }),
          borderColor: colors.ok,
          backgroundColor: colors.okBg,
          fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        animation: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { color: colors.grid }, ticks: { maxTicksLimit: 10, font: { size: 9 } } },
          y: { grid: { color: colors.grid }, beginAtZero: true, title: { display: true, text: 'req/s', color: colors.text } }
        }
      }
    });
  }

  function generateShapePoints(testType, c) {
    var points = [];
    var t = 0;
    switch (testType) {
      case 'load':
        var rampUp = c.ramp_up_seconds || 30;
        var hold = c.hold_duration_seconds || 300;
        var rampDown = c.ramp_down_seconds || 10;
        var target = c.target_rps || 50;
        for (var i = 0; i <= rampUp; i += Math.max(1, Math.floor(rampUp / 10))) { points.push({ t: t + i, rps: Math.round(target * i / rampUp) }); }
        t += rampUp;
        points.push({ t: t, rps: target });
        points.push({ t: t + hold, rps: target });
        t += hold;
        for (var j = 0; j <= rampDown; j += Math.max(1, Math.floor(rampDown / 5))) { points.push({ t: t + j, rps: Math.round(target * (rampDown - j) / rampDown) }); }
        break;
      case 'stress':
        var start = c.start_rps || 10, step = c.step_rps || 20, max = c.max_rps || 500, dur = c.step_duration_seconds || 30;
        for (var rps = start; rps <= max; rps += step) { points.push({ t: t, rps: rps }); points.push({ t: t + dur, rps: rps }); t += dur; }
        break;
      case 'spike':
        var base = c.baseline_rps || 20, spike = c.spike_rps || 200;
        var bDur = c.baseline_duration_seconds || 60, sDur = c.spike_duration_seconds || 30, rDur = c.recovery_duration_seconds || 60;
        points.push({ t: 0, rps: base }, { t: bDur, rps: base }, { t: bDur + 1, rps: spike }, { t: bDur + sDur, rps: spike }, { t: bDur + sDur + 1, rps: base }, { t: bDur + sDur + rDur, rps: base });
        break;
      case 'soak':
        var soakRps = c.soak_rps || 30, soakDur = c.soak_duration_seconds || 1800;
        points.push({ t: 0, rps: soakRps }, { t: soakDur, rps: soakRps });
        break;
      case 'ramp':
        var rStart = c.ramp_start_rps || 10, rEnd = c.ramp_end_rps || 200, rStep = c.step_rps || 10, rDurS = c.step_duration_seconds || 15;
        for (var r = rStart; r <= rEnd; r += rStep) { points.push({ t: t, rps: r }); points.push({ t: t + rDurS, rps: r }); t += rDurS; }
        break;
      case 'burst':
        var n = c.total_requests || 200;
        points.push({ t: 0, rps: n }, { t: 1, rps: n }, { t: 2, rps: 0 });
        break;
      case 'breakpoint':
        var bpStart = c.start_rps || 10, bpMax = c.max_rps || 500;
        points.push({ t: 0, rps: bpStart }, { t: 60, rps: (bpStart + bpMax) / 2 }, { t: 120, rps: bpMax });
        break;
      case 'custom':
        var stages = c.stages || [];
        stages.forEach(function(s) { points.push({ t: t, rps: s.rps }); t += s.duration; points.push({ t: t, rps: s.rps }); });
        break;
    }
    return points;
  }

  function destroyAll() {
    Object.keys(chartInstances).forEach(destroyChart);
  }

  return {
    rpsBarChart: rpsBarChart,
    statusDoughnut: statusDoughnut,
    latencyHistogram: latencyHistogram,
    timelineScatter: timelineScatter,
    loadShapePreview: loadShapePreview,
    liveRpsLine: liveRpsLine,
    destroyAll: destroyAll,
    destroyChart: destroyChart,
    colors: colors,
    statusColor: statusColor
  };
})();
