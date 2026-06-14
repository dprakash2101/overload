window.DocsPage = (function() {
  var DOCS_BASE_URL = 'https://dprakash2101.github.io/overload/';

  function render(container) {
    container.innerHTML =
      '<iframe src="' + DOCS_BASE_URL + '" ' +
        'style="width:100%;height:calc(100vh - 60px);border:none;display:block" ' +
        'sandbox="allow-same-origin allow-scripts allow-popups allow-forms allow-top-navigation-by-user-activation" ' +
        'loading="lazy"></iframe>';
  }

  return { render: render };
})();
