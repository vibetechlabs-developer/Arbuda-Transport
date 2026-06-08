/**
 * Super Admin: reveal / copy saved PDF passwords on Security Settings.
 */
(function () {
  function getCookie(name) {
    const match = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[1]) : "";
  }

  function hideRevealed(block) {
    block.querySelector(".pdf-pw-revealed").classList.add("d-none");
    block.querySelector(".pdf-pw-reveal-error").classList.add("d-none");
    block.querySelector(".pdf-pw-copy-btn").classList.add("d-none");
    block.querySelector(".pdf-pw-hide-btn").classList.add("d-none");
    const revealBtn = block.querySelector(".pdf-pw-reveal-btn");
    if (revealBtn && block.dataset.hasPassword === "1") {
      revealBtn.disabled = false;
    }
  }

  document.querySelectorAll(".pdf-pw-block").forEach(function (block) {
    const revealBtn = block.querySelector(".pdf-pw-reveal-btn");
    const copyBtn = block.querySelector(".pdf-pw-copy-btn");
    const hideBtn = block.querySelector(".pdf-pw-hide-btn");
    const revealed = block.querySelector(".pdf-pw-revealed");
    const valueEl = block.querySelector(".pdf-pw-value");
    const errorEl = block.querySelector(".pdf-pw-reveal-error");

    if (!revealBtn) {
      return;
    }

    revealBtn.addEventListener("click", function () {
      if (block.dataset.hasPassword !== "1") {
        return;
      }
      const url = block.dataset.revealUrl;
      if (!url) {
        return;
      }

      revealBtn.disabled = true;
      errorEl.classList.add("d-none");
      revealed.classList.add("d-none");

      fetch(url, {
        method: "GET",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok || !result.data.ok) {
            errorEl.textContent = result.data.error || "Could not load password.";
            errorEl.classList.remove("d-none");
            revealBtn.disabled = false;
            return;
          }
          valueEl.textContent = result.data.password;
          revealed.classList.remove("d-none");
          copyBtn.classList.remove("d-none");
          hideBtn.classList.remove("d-none");
          revealBtn.disabled = true;
        })
        .catch(function () {
          errorEl.textContent = "Network error. Please try again.";
          errorEl.classList.remove("d-none");
          revealBtn.disabled = false;
        });
    });

    hideBtn.addEventListener("click", function () {
      hideRevealed(block);
    });

    copyBtn.addEventListener("click", function () {
      const text = valueEl.textContent;
      if (!text) {
        return;
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () {
          copyBtn.textContent = "Copied!";
          setTimeout(function () {
            copyBtn.innerHTML = '<i class="bx bx-copy me-1"></i> Copy';
          }, 2000);
        });
        return;
      }
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        copyBtn.textContent = "Copied!";
        setTimeout(function () {
          copyBtn.innerHTML = '<i class="bx bx-copy me-1"></i> Copy';
        }, 2000);
      } catch (e) {
        /* ignore */
      }
      document.body.removeChild(ta);
    });
  });
})();
