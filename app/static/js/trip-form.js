// Trip posting form: show/hide the weekly fields when the recurrence
// selector changes. External file to keep CSP `script-src 'self'`.
(function () {
  var sel = document.getElementById("rec");
  var fs = document.getElementById("weekly-fields");
  if (!sel || !fs) return;
  function apply() {
    fs.style.display = sel.value === "weekly" ? "" : "none";
  }
  sel.addEventListener("change", apply);
  apply();
})();
