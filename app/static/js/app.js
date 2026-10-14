// CampusRide UI helpers. No inline scripts are used; this file is the only
// place that runs in the browser besides vendored HTMX.
(function () {
  "use strict";

  // Apply the theme cookie as the data-theme attribute on <html> as early as
  // possible to avoid a flash of the wrong theme.
  try {
    var m = document.cookie.match(/(?:^|; )cr_theme=([^;]+)/);
    if (m) {
      document.documentElement.setAttribute("data-theme", decodeURIComponent(m[1]));
    }
  } catch (e) { /* ignore */ }

  document.addEventListener("htmx:afterRequest", function (evt) {
    // Toggle endpoints respond with 204 + a Set-Cookie. Reload to apply
    // the new theme/language. Keep the user on the same page.
    try {
      var path = (evt && evt.detail && evt.detail.pathInfo) || "";
      if (path === "/me/theme" || path === "/me/lang") {
        var next = "/";
        try {
          var headers = (evt.detail && evt.detail.xhr && evt.detail.xhr.getResponseHeader) ? evt.detail.xhr.getResponseHeader("X-Cr-Next") : null;
          if (headers) next = headers;
        } catch (e) { /* ignore */ }
        // Fallback to current path
        next = next || window.location.pathname + window.location.search;
        window.location.assign(next);
      }
    } catch (e) { /* ignore */ }
  });
})();
