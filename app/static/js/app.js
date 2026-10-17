// CampusRide Client-Side Interactions — CSP Safe, Zero Dependencies
(function () {
  "use strict";

  // 1. Fast Theme Init: Apply the theme cookie to <html> to prevent flash of wrong theme
  try {
    var m = document.cookie.match(/(?:^|; )cr_theme=([^;]+)/);
    if (m) {
      document.documentElement.setAttribute("data-theme", decodeURIComponent(m[1]));
    }
  } catch (e) { /* ignore */ }

  // 2. HTMX response listener for theme / language toggle
  document.addEventListener("htmx:afterRequest", function (evt) {
    try {
      var path = (evt && evt.detail && evt.detail.pathInfo) || "";
      if (path === "/me/theme" || path === "/me/lang") {
        var next = "/";
        try {
          var headers = (evt.detail && evt.detail.xhr && evt.detail.xhr.getResponseHeader)
            ? evt.detail.xhr.getResponseHeader("X-Cr-Next")
            : null;
          if (headers) next = headers;
        } catch (e) { /* ignore */ }
        next = next || window.location.pathname + window.location.search;
        window.location.assign(next);
      }
    } catch (e) { /* ignore */ }
  });

  // 3. Interactive DOM behaviors on DOMContentLoaded
  document.addEventListener("DOMContentLoaded", function () {
    // Mobile navigation toggle
    var mobileToggle = document.getElementById("cr-mobile-menu-btn");
    var nav = document.getElementById("cr-nav-menu");
    if (mobileToggle && nav) {
      mobileToggle.addEventListener("click", function () {
        var isOpen = nav.classList.toggle("open");
        mobileToggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
      });
    }

    // Instant client-side theme switch for seamless zero-latency transition
    var themeToggle = document.getElementById("cr-theme-toggle");
    if (themeToggle) {
      themeToggle.addEventListener("click", function () {
        var current = document.documentElement.getAttribute("data-theme") || "light";
        var next = current === "dark" ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", next);
        document.cookie = "cr_theme=" + next + ";path=/;max-age=31536000";
      });
    }

    // Interactive role preview tabs on homepage
    var tabRider = document.getElementById("tab-rider");
    var tabDriver = document.getElementById("tab-driver");
    var previewRouteName = document.getElementById("preview-route-name");
    var previewMetaDesc = document.getElementById("preview-meta-desc");
    var previewBtn = document.getElementById("preview-action-btn");

    if (tabRider && tabDriver) {
      tabRider.addEventListener("click", function () {
        tabRider.classList.add("active");
        tabDriver.classList.remove("active");
        if (previewRouteName) previewRouteName.textContent = "Main Gate ➔ Campus Library";
        if (previewMetaDesc) previewMetaDesc.textContent = "Departing 8:30 AM · 2 seats left · 30 BDT";
        if (previewBtn) previewBtn.textContent = "Reserve Seat";
      });

      tabDriver.addEventListener("click", function () {
        tabDriver.classList.add("active");
        tabRider.classList.remove("active");
        if (previewRouteName) previewRouteName.textContent = "Dormitories ➔ Science Annex";
        if (previewMetaDesc) previewMetaDesc.textContent = "Driving at 9:00 AM · 3 empty seats · Shared fuel";
        if (previewBtn) previewBtn.textContent = "Post Your Route";
      });
    }

    // Quick Route Preset Chips
    var routeChips = document.querySelectorAll(".cr-route-chip");
    routeChips.forEach(function (chip) {
      chip.addEventListener("click", function () {
        var fromVal = chip.getAttribute("data-from");
        var toVal = chip.getAttribute("data-to");
        var fromSelect = document.querySelector("select[name='from_place_id']");
        var toSelect = document.querySelector("select[name='to_place_id']");
        if (fromSelect && toSelect && fromVal && toVal) {
          fromSelect.value = fromVal;
          toSelect.value = toVal;
          fromSelect.scrollIntoView({ behavior: "smooth", block: "center" });
        } else {
          // If not on search page, redirect to search
          window.location.href = "/search";
        }
      });
    });

    // FAQ Accordion Toggle
    var faqQuestions = document.querySelectorAll(".cr-faq-question");
    faqQuestions.forEach(function (btn) {
      btn.addEventListener("click", function () {
        var item = btn.closest(".cr-faq-item");
        if (item) {
          var wasOpen = item.classList.contains("open");
          // Close all open FAQs for neatness
          document.querySelectorAll(".cr-faq-item.open").forEach(function (openItem) {
            openItem.classList.remove("open");
          });
          if (!wasOpen) {
            item.classList.add("open");
          }
        }
      });
    });

    // Copy Trusted Contact Token Button
    var copyBtn = document.getElementById("cr-copy-trusted-token");
    var tokenCode = document.getElementById("cr-trusted-token");
    if (copyBtn && tokenCode) {
      copyBtn.addEventListener("click", function () {
        var text = tokenCode.textContent.trim();
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(function () {
            var orig = copyBtn.textContent;
            copyBtn.textContent = "✓ Copied!";
            setTimeout(function () { copyBtn.textContent = orig; }, 2000);
          });
        }
      });
    }
  });
})();
