/**
 * Employee session hardening: office-hours/location poll, hotkey blocks, print audit.
 */
(function () {
  if (!document.body || document.body.dataset.userRole !== "employee") {
    return;
  }

  const csrfToken =
    document.querySelector("[name=csrfmiddlewaretoken]")?.value ||
    document.cookie
      .split("; ")
      .find((r) => r.startsWith("csrftoken="))
      ?.split("=")[1];

  function sendBeacon(eventType, details) {
    fetch("/security/audit-beacon", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken || "",
      },
      body: JSON.stringify({ event_type: eventType, details: details || {} }),
      credentials: "same-origin",
    }).catch(function () {});
  }

  function checkSecurityStatus() {
    fetch("/security/office-hours-status", { credentials: "same-origin" })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        var banner = document.getElementById("office-hours-banner");
        if (data.role !== "employee") {
          if (banner) banner.remove();
          return;
        }

        var windowText =
          data.office_start && data.office_end
            ? " (" + data.office_start + " – " + data.office_end + ")"
            : "";
        var parts = [];

        if (data.location_enforced && data.location_requires_permission && !data.location_grant_active) {
          parts.push(
            "<strong>Outside office location</strong> — request " +
              "<a href='/security/preview-permission/request'>Super Admin approval</a>. " +
              "PDFs outside the office use a <strong>different password</strong> than inside."
          );
        } else if (data.location_grant_active) {
          parts.push(
            "<strong>Outside-location access approved</strong> — use permitted modules until grant expires."
          );
        }

        if (data.office_hours_enabled) {
          if (data.preview_grant_active) {
            parts.push(
              "<strong>After-hours access approved</strong>" +
                windowText +
                " — you may use modules and PDF preview."
            );
          } else if (!data.allowed && data.preview_requires_permission) {
            parts.push(
              "<strong>Outside office hours</strong>" +
                windowText +
                " — request <a href='/security/preview-permission/request'>Super Admin approval</a>."
            );
          }
        }

        if (!parts.length) {
          if (banner) banner.remove();
          return;
        }

        if (!banner) {
          banner = document.createElement("div");
          banner.id = "office-hours-banner";
          var page = document.querySelector(".layout-page");
          if (page) page.prepend(banner);
        }

        var needsAction =
          (data.location_requires_permission && !data.location_grant_active) ||
          (data.preview_requires_permission && !data.preview_grant_active);
        banner.className =
          "alert text-center mb-0 rounded-0 " +
          (needsAction ? "alert-warning" : "alert-success");
        banner.innerHTML =
          parts.join("<br>") +
          ' <a href="/security/preview-permission/my">My preview requests</a>';
      })
      .catch(function () {});
  }

  setInterval(checkSecurityStatus, 60000);
  checkSecurityStatus();

  document.addEventListener(
    "keydown",
    function (e) {
      const key = (e.key || "").toLowerCase();
      const ctrl = e.ctrlKey || e.metaKey;
      const blocked =
        (ctrl && (key === "p" || key === "s" || key === "c" || key === "u")) ||
        key === "f12" ||
        (e.ctrlKey && e.shiftKey && (key === "i" || key === "j" || key === "s"));
      if (blocked) {
        e.preventDefault();
        e.stopPropagation();
        sendBeacon("HOTKEY_BLOCKED", { key: key, ctrl: ctrl });
        return false;
      }
    },
    true
  );

  document.addEventListener("contextmenu", function (e) {
    e.preventDefault();
  });

  window.addEventListener("beforeprint", function () {
    sendBeacon("PRINT_ATTEMPT", { source: "beforeprint" });
  });

  document.addEventListener("copy", function (e) {
    e.preventDefault();
    sendBeacon("HOTKEY_BLOCKED", { action: "copy" });
  });
})();
