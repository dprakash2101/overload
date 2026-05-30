window.CollectionPage = (function() {
  var collection = null;
  var selectedRequest = null;

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

        if (collections.length) {
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
              else loadLocalEnvironment(path);
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

  function renderCollection() {
    document.getElementById('uploadCard').style.display = 'none';
    document.getElementById('envCard').style.display = 'block';
    var detected = document.getElementById('detectedFiles');
    if (detected) detected.style.display = 'none';

    var view = document.getElementById('collectionView');
    view.style.display = 'block';

    var html =
      '<div class="card">' +
        '<div class="card-title">' + esc(collection.name) + ' (' + collection.requests.length + ' requests)</div>' +
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
      el.addEventListener('click', function() {
        var idx = parseInt(el.dataset.idx);
        showRequestDetail(idx);
      });
    });

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
      html += '<div class="tree-folder-name"><span class="tree-folder-icon">&#9660;</span> ' + esc(name) + '</div>';
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
    return '<div class="tree-request" data-idx="' + idx + '">' +
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

  return { render: render, getCollection: getCollection };
})();
