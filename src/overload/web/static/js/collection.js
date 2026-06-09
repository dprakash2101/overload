window.CollectionPage = (function() {
  var collection = null;
  var selectedRequest = null;
  var selectedIndices = null; // null = all selected; Set<number> = explicit subset
  var dataAttached = false;

  function render(container) {
    container.innerHTML =
      '<h1 class="page-title">Collection</h1>' +
      '<p class="page-desc">Upload a Postman Collection to get started</p>' +
      '<div class="working-dir-banner" id="workingDirBanner" style="display:none"></div>' +
      '<div id="detectedFiles"></div>' +
      '<div class="card" id="uploadCard">' +
        '<div class="drop-zone" id="dropZone">' +
          '<div class="drop-zone-text">Drop your Postman Collection here</div>' +
          '<div class="drop-zone-sub">.json file (v2.0 or v2.1)</div>' +
          '<input type="file" id="collectionFile" accept=".json">' +
        '</div>' +
      '</div>' +
      '<div class="card" style="display:none" id="envCard">' +
        '<div class="card-title">Environment (optional)</div>' +
        '<div class="drop-zone" id="envDropZone" style="padding:24px">' +
          '<div class="drop-zone-sub">Drop Postman Environment file</div>' +
          '<input type="file" id="envFile" accept=".json">' +
        '</div>' +
      '</div>' +
      '<div class="card" style="display:none" id="csvCard">' +
        '<div class="card-title">Data file (CSV) <span style="font-weight:400;font-size:11px;color:var(--mut)">— optional</span></div>' +
        '<div class="drop-zone" id="csvDropZone" style="padding:24px">' +
          '<div class="drop-zone-sub">Drop CSV file — column names fill <code>{{placeholders}}</code> in the collection</div>' +
          '<input type="file" id="csvFile" accept=".csv">' +
        '</div>' +
        '<div id="csvStatus" style="display:none;margin-top:8px;font-size:11px"></div>' +
      '</div>' +
      '<div id="collectionView" style="display:none"></div>';

    detectLocalFiles();
    setupDropZone();
  }

  function detectLocalFiles() {
    fetch('/api/detect')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.status !== 'ok') return;

        var banner = document.getElementById('workingDirBanner');
        if (banner && data.working_dir) {
          banner.style.display = 'flex';
          banner.innerHTML = '&#128193; Working directory: <span class="dir-path">' + esc(data.working_dir) + '</span>';
        }

        var html = '';
        var collections = data.collections || [];
        var environments = data.environments || [];

        var csvFiles = data.csv_files || [];
        if (collections.length || environments.length || csvFiles.length) {
          html += '<div class="detected-section"><div class="card">';
          html += '<div class="card-title">Found in ' + esc(data.working_dir) + '</div>';
          collections.forEach(function(c) {
            html += '<div class="detected-item" data-path="' + esc(c.path) + '" data-type="collection">';
            html += '<div class="detected-item-info">';
            html += '<div class="detected-item-icon">&#128230;</div>';
            html += '<div><div class="detected-item-name">' + esc(c.name) + '</div>';
            html += '<div class="detected-item-meta">' + esc(c.filename) + ' &mdash; ' + c.request_count + ' requests</div></div>';
            html += '</div>';
            html += '<div class="detected-item-btn">Load</div>';
            html += '</div>';
          });
          environments.forEach(function(e) {
            html += '<div class="detected-item" data-path="' + esc(e.path) + '" data-type="environment">';
            html += '<div class="detected-item-info">';
            html += '<div class="detected-item-icon">&#9881;</div>';
            html += '<div><div class="detected-item-name">' + esc(e.name) + '</div>';
            html += '<div class="detected-item-meta">' + esc(e.filename) + ' &mdash; ' + e.variable_count + ' variables (environment)</div></div>';
            html += '</div>';
            html += '<div class="detected-item-btn">Load</div>';
            html += '</div>';
          });
          csvFiles.forEach(function(f) {
            html += '<div class="detected-item" data-path="' + esc(f.path) + '" data-type="csv">';
            html += '<div class="detected-item-info">';
            html += '<div class="detected-item-icon">&#128202;</div>';
            html += '<div><div class="detected-item-name">' + esc(f.filename) + '</div>';
            html += '<div class="detected-item-meta">' + f.row_count + ' rows &mdash; columns: ' + f.columns.map(function(c) { return esc(c); }).join(', ') + '</div></div>';
            html += '</div>';
            html += '<div class="detected-item-btn">Use</div>';
            html += '</div>';
          });
          html += '</div></div>';
        }

        var container = document.getElementById('detectedFiles');
        if (container) {
          container.innerHTML = html;
          container.querySelectorAll('.detected-item').forEach(function(el) {
            el.addEventListener('click', function() {
              var path = el.dataset.path;
              var type = el.dataset.type;
              if (type === 'collection') loadLocalCollection(path);
              else if (type === 'environment') loadLocalEnvironment(path);
              else if (type === 'csv') loadLocalCsv(path);
            });
          });
        }
      })
      .catch(function() {});
  }

  function loadLocalCollection(path) {
    fetch('/api/collection/load-local', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: path })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.status === 'ok') {
        collection = data.collection;
        window.OverloadApp.setCollection(collection);
        renderCollection();
        App.toast('Collection loaded: ' + collection.name, 'success');
      } else {
        App.toast('Error: ' + data.message, 'error');
      }
    })
    .catch(function(err) { App.toast('Failed to load: ' + err.message, 'error'); });
  }

  function loadLocalEnvironment(path) {
    fetch('/api/environment/load-local', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: path })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.status === 'ok') {
        App.toast('Environment loaded: ' + Object.keys(data.variables).length + ' variables', 'success');
        if (collection) renderCollection();
      } else {
        App.toast('Error: ' + data.message, 'error');
      }
    })
    .catch(function(err) { App.toast('Failed to load: ' + err.message, 'error'); });
  }

  function loadLocalCsv(path) {
    fetch('/api/data/load-local', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: path })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.status === 'ok') {
        dataAttached = true;
        var csvCard = document.getElementById('csvCard');
        if (csvCard) csvCard.style.display = 'block';
        renderCsvStatus(data);
        App.toast('Data loaded: ' + data.row_count + ' rows, ' + data.columns.length + ' columns', 'success');
      } else {
        App.toast('Error: ' + data.message, 'error');
      }
    })
    .catch(function(err) { App.toast('Failed to load CSV: ' + err.message, 'error'); });
  }

  function setupDropZone() {
    var zone = document.getElementById('dropZone');
    var input = document.getElementById('collectionFile');
    var envZone = document.getElementById('envDropZone');
    var envInput = document.getElementById('envFile');

    zone.addEventListener('click', function() { input.click(); });
    zone.addEventListener('dragover', function(e) { e.preventDefault(); zone.classList.add('dragover'); });
    zone.addEventListener('dragleave', function() { zone.classList.remove('dragover'); });
    zone.addEventListener('drop', function(e) {
      e.preventDefault();
      zone.classList.remove('dragover');
      if (e.dataTransfer.files.length) uploadCollection(e.dataTransfer.files[0]);
    });
    input.addEventListener('change', function() { if (input.files.length) uploadCollection(input.files[0]); });

    envZone.addEventListener('click', function() { envInput.click(); });
    envZone.addEventListener('dragover', function(e) { e.preventDefault(); envZone.classList.add('dragover'); });
    envZone.addEventListener('dragleave', function() { envZone.classList.remove('dragover'); });
    envZone.addEventListener('drop', function(e) {
      e.preventDefault();
      envZone.classList.remove('dragover');
      if (e.dataTransfer.files.length) uploadEnvironment(e.dataTransfer.files[0]);
    });
    envInput.addEventListener('change', function() { if (envInput.files.length) uploadEnvironment(envInput.files[0]); });

    var csvZone = document.getElementById('csvDropZone');
    var csvInput = document.getElementById('csvFile');
    if (csvZone && csvInput) {
      csvZone.addEventListener('click', function() { csvInput.click(); });
      csvZone.addEventListener('dragover', function(e) { e.preventDefault(); csvZone.classList.add('dragover'); });
      csvZone.addEventListener('dragleave', function() { csvZone.classList.remove('dragover'); });
      csvZone.addEventListener('drop', function(e) {
        e.preventDefault();
        csvZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) uploadCsv(e.dataTransfer.files[0]);
      });
      csvInput.addEventListener('change', function() { if (csvInput.files.length) uploadCsv(csvInput.files[0]); });
    }
  }

  function uploadCollection(file) {
    var formData = new FormData();
    formData.append('file', file);

    fetch('/api/collection/upload', { method: 'POST', body: formData })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.status === 'ok') {
          collection = data.collection;
          window.OverloadApp.setCollection(collection);
          renderCollection();
          App.toast('Collection loaded: ' + collection.name, 'success');
        } else {
          App.toast('Error: ' + data.message, 'error');
        }
      })
      .catch(function(err) { App.toast('Upload failed: ' + err.message, 'error'); });
  }

  function uploadEnvironment(file) {
    var formData = new FormData();
    formData.append('file', file);

    fetch('/api/environment/upload', { method: 'POST', body: formData })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.status === 'ok') {
          App.toast('Environment loaded: ' + Object.keys(data.variables).length + ' variables', 'success');
          if (collection) renderCollection();
        } else {
          App.toast('Error: ' + data.message, 'error');
        }
      })
      .catch(function(err) { App.toast('Upload failed: ' + err.message, 'error'); });
  }

  function uploadCsv(file) {
    var formData = new FormData();
    formData.append('file', file);
    fetch('/api/data/upload', { method: 'POST', body: formData })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.status === 'ok') {
          dataAttached = true;
          renderCsvStatus(data);
          App.toast('Data loaded: ' + data.row_count + ' rows, ' + data.columns.length + ' columns', 'success');
        } else {
          App.toast('Error: ' + data.message, 'error');
        }
      })
      .catch(function(err) { App.toast('Upload failed: ' + err.message, 'error'); });
  }

  function renderCsvStatus(data) {
    var el = document.getElementById('csvStatus');
    if (!el) return;
    var html = '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">';
    html += '<span style="color:var(--ok)">&#10003; ' + data.row_count + ' rows, ' + data.columns.length + ' columns</span>';
    if (data.matched_placeholders && data.matched_placeholders.length) {
      html += '<span style="color:var(--ok)">Matched: ' + data.matched_placeholders.map(function(p) { return '<code>{{' + esc(p) + '}}</code>'; }).join(', ') + '</span>';
    }
    if (data.unmatched_placeholders && data.unmatched_placeholders.length) {
      html += '<span style="color:var(--warn,#b45309)">No column for: ' + data.unmatched_placeholders.map(function(p) { return '<code>{{' + esc(p) + '}}</code>'; }).join(', ') + '</span>';
    }
    html += '<button class="btn btn-secondary" id="clearCsvBtn" style="padding:2px 8px;font-size:11px;margin-left:auto">Remove</button>';
    html += '</div>';
    el.innerHTML = html;
    el.style.display = 'block';
    var clearBtn = document.getElementById('clearCsvBtn');
    if (clearBtn) {
      clearBtn.addEventListener('click', function() {
        fetch('/api/data/clear', { method: 'POST' })
          .then(function() {
            dataAttached = false;
            el.style.display = 'none';
            el.innerHTML = '';
            App.toast('Data file removed', 'success');
          });
      });
    }
  }

  function renderCollection() {
    document.getElementById('uploadCard').style.display = 'none';
    document.getElementById('envCard').style.display = 'block';
    document.getElementById('csvCard').style.display = 'block';
    var detected = document.getElementById('detectedFiles');
    if (detected) detected.style.display = 'none';

    selectedIndices = null; // reset to all-selected on new collection load

    var view = document.getElementById('collectionView');
    view.style.display = 'block';

    var selectionHtml =
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">' +
        '<button class="btn btn-secondary" id="selectAllBtn" style="padding:2px 8px;font-size:11px">All</button>' +
        '<button class="btn btn-secondary" id="selectNoneBtn" style="padding:2px 8px;font-size:11px">None</button>' +
        '<span id="selectionCount" style="color:var(--mut);font-size:11px">' + collection.requests.length + ' of ' + collection.requests.length + ' selected</span>' +
      '</div>';

    var html =
      '<div class="card">' +
        '<div class="card-title">' + esc(collection.name) + ' (' + collection.requests.length + ' requests)</div>' +
        selectionHtml +
        '<div class="tree" id="collectionTree">' + renderTree(collection.requests) + '</div>' +
      '</div>';

    if (collection.variables && collection.variables.length) {
      html +=
        '<div class="card">' +
          '<div class="card-title">Variables</div>' +
          '<table class="var-table">' +
            '<thead><tr><th>Name</th><th>Value</th></tr></thead>' +
            '<tbody>' +
            collection.variables.map(function(v, i) {
              return '<tr><td>' + esc(v.key) + '</td><td><input type="text" value="' + esc(v.value) + '" data-var-key="' + esc(v.key) + '" class="var-input"></td></tr>';
            }).join('') +
            '</tbody>' +
          '</table>' +
        '</div>';
    }

    html += '<div style="display:flex;gap:8px;margin-top:12px;justify-content:space-between;align-items:center">';
    html += '<button class="btn btn-secondary" id="resetBtn">Change Collection</button>';
    html += '<button class="btn btn-primary" id="continueBtn">Continue to Test Runner &rarr;</button>';
    html += '</div>';

    html += '<div id="requestDetail"></div>';

    view.innerHTML = html;

    view.querySelectorAll('.tree-request').forEach(function(el) {
      el.addEventListener('click', function(e) {
        if (e.target.classList.contains('req-checkbox')) return;
        var idx = parseInt(el.dataset.idx);
        showRequestDetail(idx);
      });
    });

    view.querySelectorAll('.req-checkbox').forEach(function(cb) {
      cb.addEventListener('change', function(e) {
        e.stopPropagation();
        var idx = parseInt(cb.dataset.idx);
        initSelectedIndices();
        if (cb.checked) selectedIndices.add(idx);
        else selectedIndices.delete(idx);
        updateFolderCheckbox(cb);
        updateSelectionCount();
      });
    });

    view.querySelectorAll('.folder-checkbox').forEach(function(fcb) {
      fcb.addEventListener('change', function(e) {
        e.stopPropagation();
        initSelectedIndices();
        var folderEl = fcb.closest('.tree-folder');
        folderEl.querySelectorAll('.req-checkbox').forEach(function(cb) {
          var idx = parseInt(cb.dataset.idx);
          cb.checked = fcb.checked;
          if (fcb.checked) selectedIndices.add(idx);
          else selectedIndices.delete(idx);
        });
        updateSelectionCount();
      });
    });

    var selectAllBtn = document.getElementById('selectAllBtn');
    if (selectAllBtn) {
      selectAllBtn.addEventListener('click', function() {
        selectedIndices = null;
        view.querySelectorAll('.req-checkbox').forEach(function(cb) { cb.checked = true; });
        view.querySelectorAll('.folder-checkbox').forEach(function(fcb) { fcb.checked = true; fcb.indeterminate = false; });
        updateSelectionCount();
      });
    }

    var selectNoneBtn = document.getElementById('selectNoneBtn');
    if (selectNoneBtn) {
      selectNoneBtn.addEventListener('click', function() {
        initSelectedIndices();
        selectedIndices.clear();
        view.querySelectorAll('.req-checkbox').forEach(function(cb) { cb.checked = false; });
        view.querySelectorAll('.folder-checkbox').forEach(function(fcb) { fcb.checked = false; fcb.indeterminate = false; });
        updateSelectionCount();
      });
    }

    view.querySelectorAll('.var-input').forEach(function(input) {
      input.addEventListener('change', function() {
        var key = input.dataset.varKey;
        var vars = {};
        vars[key] = input.value;
        fetch('/api/variables/update', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ variables: vars })
        });
      });
    });

    document.getElementById('continueBtn').addEventListener('click', function() {
      window.OverloadApp.navigate('runner');
    });

    document.getElementById('resetBtn').addEventListener('click', function() {
      collection = null;
      window.OverloadApp.setCollection(null);
      render(document.getElementById('content'));
    });
  }

  function initSelectedIndices() {
    if (selectedIndices === null) {
      selectedIndices = new Set();
      for (var i = 0; i < collection.requests.length; i++) selectedIndices.add(i);
    }
  }

  function updateSelectionCount() {
    var el = document.getElementById('selectionCount');
    if (!el) return;
    var total = collection.requests.length;
    var count = selectedIndices === null ? total : selectedIndices.size;
    el.textContent = count + ' of ' + total + ' selected';
  }

  function updateFolderCheckbox(changedCb) {
    var folderEl = changedCb.closest('.tree-folder');
    if (!folderEl) return;
    var fcb = folderEl.querySelector('.folder-checkbox');
    if (!fcb) return;
    var cbs = folderEl.querySelectorAll('.req-checkbox');
    var checkedCount = 0;
    cbs.forEach(function(cb) { if (cb.checked) checkedCount++; });
    if (checkedCount === 0) { fcb.checked = false; fcb.indeterminate = false; }
    else if (checkedCount === cbs.length) { fcb.checked = true; fcb.indeterminate = false; }
    else { fcb.checked = false; fcb.indeterminate = true; }
  }

  function renderTree(requests) {
    var folders = {};
    var rootRequests = [];

    requests.forEach(function(req, idx) {
      if (req.folder_path && req.folder_path.length) {
        var key = req.folder_path.join('/');
        if (!folders[key]) folders[key] = { path: req.folder_path, requests: [] };
        folders[key].requests.push({ req: req, idx: idx });
      } else {
        rootRequests.push({ req: req, idx: idx });
      }
    });

    var html = '';

    Object.keys(folders).forEach(function(key) {
      var folder = folders[key];
      var name = folder.path[folder.path.length - 1];
      html += '<div class="tree-folder">';
      html += '<div class="tree-folder-name">';
      html += '<input type="checkbox" class="folder-checkbox" checked style="margin-right:4px;cursor:pointer" onclick="event.stopPropagation()">';
      html += '<span class="tree-folder-icon">&#9660;</span> ' + esc(name);
      html += '</div>';
      html += '<div class="tree-children">';
      folder.requests.forEach(function(item) {
        html += renderRequestItem(item.req, item.idx);
      });
      html += '</div></div>';
    });

    rootRequests.forEach(function(item) {
      html += renderRequestItem(item.req, item.idx);
    });

    return html;
  }

  function renderRequestItem(req, idx) {
    var isChecked = selectedIndices === null || selectedIndices.has(idx);
    return '<div class="tree-request" data-idx="' + idx + '">' +
      '<input type="checkbox" class="req-checkbox" data-idx="' + idx + '"' + (isChecked ? ' checked' : '') + ' style="margin-right:6px;cursor:pointer" onclick="event.stopPropagation()">' +
      '<span class="method-badge method-' + req.method + '">' + req.method + '</span>' +
      '<span>' + esc(req.name) + '</span>' +
    '</div>';
  }

  function showRequestDetail(idx) {
    var req = collection.requests[idx];
    selectedRequest = idx;

    document.querySelectorAll('.tree-request').forEach(function(el) {
      el.classList.toggle('selected', parseInt(el.dataset.idx) === idx);
    });

    var html = '<div class="request-detail">';
    html += '<div class="request-detail-header">';
    html += '<span class="method-badge method-' + req.method + '">' + req.method + '</span>';
    html += '<strong>' + esc(req.name) + '</strong>';
    html += '</div>';
    html += '<pre>' + esc(req.url_raw) + '</pre>';

    if (req.headers && Object.keys(req.headers).length) {
      html += '<div class="card-title" style="margin-top:12px">Headers</div>';
      html += '<pre>' + Object.keys(req.headers).map(function(k) { return esc(k) + ': ' + esc(req.headers[k]); }).join('\n') + '</pre>';
    }

    if (req.body && req.body.mode !== 'none') {
      html += '<div class="card-title" style="margin-top:12px">Body (' + req.body.mode + ')</div>';
      var bodyContent = typeof req.body.content === 'string' ? req.body.content : JSON.stringify(req.body.content, null, 2);
      html += '<pre>' + esc(bodyContent) + '</pre>';
    }

    if (req.auth) {
      html += '<div class="card-title" style="margin-top:12px">Auth (' + req.auth.type + ')</div>';
      html += '<pre>' + esc(JSON.stringify(req.auth.params, null, 2)) + '</pre>';
    }

    html += '</div>';
    document.getElementById('requestDetail').innerHTML = html;
  }

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function getCollection() { return collection; }

  function getSelectedIndices() {
    if (selectedIndices === null) return null;
    return Array.from(selectedIndices).sort(function(a, b) { return a - b; });
  }

  function getDataAttached() { return dataAttached; }

  return { render: render, getCollection: getCollection, getSelectedIndices: getSelectedIndices, getDataAttached: getDataAttached };
})();
