/**
 * Super Admin: poll pending preview approval count and refresh navbar badge.
 */
(function () {
  if (!document.getElementById("admin-approval-badge")) {
    return;
  }

  function renderList(items) {
    var list = document.getElementById("admin-approval-list");
    if (!list) return;
    if (!items || !items.length) {
      list.innerHTML =
        '<span class="dropdown-item text-muted small py-3">No pending requests</span>';
      return;
    }
    list.innerHTML = items
      .map(function (item) {
        return (
          '<a class="dropdown-item border-bottom py-2" href="/security/preview-permission/manage">' +
          '<div class="fw-semibold">' +
          escapeHtml(item.employee) +
          "</div>" +
          '<small class="text-muted d-block">' +
          escapeHtml(item.kind) +
          " · " +
          escapeHtml(item.requested_at) +
          "</small>" +
          '<small class="d-block text-truncate">' +
          escapeHtml(item.reason || item.document) +
          "</small></a>"
        );
      })
      .join("");
  }

  function escapeHtml(s) {
    var d = document.createElement("div");
    d.textContent = s || "";
    return d.innerHTML;
  }

  function refresh() {
    fetch("/security/admin-notifications", { credentials: "same-origin" })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        var badge = document.getElementById("admin-approval-badge");
        var count = data.pending_count || 0;
        if (badge) {
          badge.textContent = count;
          badge.style.display = count > 0 ? "" : "none";
        }
        renderList(data.items || []);
      })
      .catch(function () {});
  }

  setInterval(refresh, 45000);
})();
