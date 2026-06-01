/**
 * Diesel / rate revision UI for contract rate slabs.
 * Base value stays in Value column; revisions apply by effective date on dispatch.
 */

function parseNum(val) {
  const n = parseFloat(val);
  return Number.isFinite(n) ? n : 0;
}

function formatRateValue(val) {
  const n = parseNum(val);
  const clean = Math.round(n * 10000) / 10000;
  return parseFloat(clean.toFixed(4)).toString();
}

function getServerEffectiveRate(updatedInput) {
  if (!updatedInput) return null;
  const raw = updatedInput.dataset.effectiveRate;
  if (raw === undefined || raw === null || String(raw).trim() === "") return null;
  const n = parseNum(raw);
  return Number.isFinite(n) ? n : null;
}

function setCurrentRateDisplay(updatedInput, value, persistAsServer) {
  const shown = formatRateValue(value);
  updatedInput.value = shown;
  updatedInput.title = `Current rate: ${shown}`;
  if (persistAsServer) {
    updatedInput.dataset.effectiveRate = shown;
  }
}

function hasPendingDieselAdjustment(row) {
  const type = row.querySelector(".diesel-adj-type")?.value || "";
  const amount = parseNum(row.querySelector(".diesel-adj-amount")?.value);
  return Boolean(type) && amount > 0;
}

function formatDisplayDate(iso) {
  if (!iso) return "";
  const parts = String(iso).split("T")[0].split("-");
  if (parts.length === 3) return `${parts[2]}-${parts[1]}-${parts[0]}`;
  return iso;
}

function updateRevisionHint(row, revision) {
  let hint = row.querySelector(".rate-revision-active");
  const cell = row.querySelector(".rate-updated-value")?.parentElement;
  if (!cell) return;

  if (!revision) {
    if (hint) hint.remove();
    return;
  }

  const sign = revision.adjustment_type === "increase" ? "+" : "−";
  const html = `
    <div class="rate-revision-active small mt-1">
      <span class="text-muted">Active from ${formatDisplayDate(revision.effective_from)}:</span>
      ${sign}${revision.adjustment_amount}
      <span class="text-muted">(was ${revision.base_value})</span>
    </div>`;

  if (!hint) {
    cell.insertAdjacentHTML("beforeend", html);
  } else {
    hint.outerHTML = html;
  }
}

function fetchEffectiveRateForRow(row) {
  const contractId = document.getElementById("contract_id_for_rates")?.value;
  const valueInput = row.querySelector("input[name='value[]']") || 
                     row.querySelector("input[name='district_rate[]']") || 
                     row.querySelector("input[name^='taluka_rate_']");
  const updatedInput = row.querySelector(".rate-updated-value");
  const category = row.dataset.rateCategory || getActiveRateCategory();

  if (!contractId || !valueInput || !updatedInput) return;

  const params = new URLSearchParams({
    contract_id: contractId,
    rate_category: category,
    base_value: valueInput.value || "0",
  });

  if (category === "taluka_wise") {
    const districtInput = row.closest(".card")?.querySelector("input[name='district_name[]']") || row.closest("tr")?.querySelector("input[name='district_name[]']");
    const talukaInput = row.querySelector("input[name^='taluka_name_']");
    if (!districtInput || !talukaInput || !districtInput.value || !talukaInput.value) return;
    params.append("district_name", districtInput.value);
    params.append("taluka_name", talukaInput.value);
  } else if (category === "district_wise") {
    const districtInput = row.querySelector("input[name='district_name[]']");
    if (!districtInput || !districtInput.value) return;
    params.append("district_name", districtInput.value);
  } else {
    const fromKm = row.querySelector("input[name='from_km[]']")?.value;
    const toKm = row.querySelector("input[name='to_km[]']")?.value;
    if (!fromKm || !toKm) return;
    params.append("from_km", fromKm);
    params.append("to_km", toKm);
  }

  fetch(`/api/get-slab-effective-rate?${params.toString()}`)
    .then((r) => r.json())
    .then((data) => {
      if (!data.success) return;
      if (hasPendingDieselAdjustment(row)) return;
      setCurrentRateDisplay(updatedInput, data.effective_rate, true);
      updateRevisionHint(row, data.active_revision || null);
    })
    .catch(() => {});
}

let fetchEffectiveTimeout;
function scheduleFetchEffectiveRate(row) {
  clearTimeout(fetchEffectiveTimeout);
  fetchEffectiveTimeout = setTimeout(() => fetchEffectiveRateForRow(row), 350);
}

function recalcRateRow(row) {
  if (!row) return;
  const valueInput = row.querySelector("input[name='value[]']") || 
                     row.querySelector("input[name='district_rate[]']") || 
                     row.querySelector("input[name^='taluka_rate_']");
  const updatedInput = row.querySelector(".rate-updated-value");
  const adjType = row.querySelector(".diesel-adj-type");
  const adjAmount = row.querySelector(".diesel-adj-amount");
  if (!valueInput || !updatedInput) return;

  const base = parseNum(valueInput.value);
  const type = adjType ? adjType.value : "";
  const amount = adjAmount ? parseNum(adjAmount.value) : 0;

  valueInput.title = `Base contract rate: ${formatRateValue(base)}`;

  if (!type || amount <= 0) {
    const serverEff = getServerEffectiveRate(updatedInput);
    const shown = serverEff !== null ? serverEff : base;
    setCurrentRateDisplay(updatedInput, shown, false);
    return;
  }

  const startFrom = getServerEffectiveRate(updatedInput) ?? base;
  let updated = startFrom;
  if (type === "decrease") {
    updated = Math.max(0, startFrom - amount);
  } else {
    updated = startFrom + amount;
  }
  setCurrentRateDisplay(updatedInput, updated, false);
  updatedInput.title = `Preview new rate: ${formatRateValue(updated)}`;
}

function initRateRowListeners(row) {
  const updatedInput = row.querySelector(".rate-updated-value");
  if (updatedInput && updatedInput.value) {
    updatedInput.dataset.effectiveRate = updatedInput.value;
    updatedInput.title = `Current rate: ${updatedInput.value}`;
  }

  const valueInput = row.querySelector("input[name='value[]']") || 
                     row.querySelector("input[name='district_rate[]']") || 
                     row.querySelector("input[name^='taluka_rate_']");
  if (valueInput) {
    valueInput.addEventListener("input", () => {
      if (hasPendingDieselAdjustment(row)) {
        recalcRateRow(row);
      } else {
        scheduleFetchEffectiveRate(row);
      }
    });
  }

  ["from_km[]", "to_km[]", "district_name[]", "taluka_name[]"].forEach((name) => {
    const el = row.querySelector(`input[name='${name}']`) || row.querySelector(`input[name^='taluka_name_']`);
    if (el) {
      el.addEventListener("input", () => scheduleFetchEffectiveRate(row));
    }
  });

  if (row.dataset.rateCategory === "taluka_wise") {
    const distCard = row.closest(".card");
    const distInput = distCard?.querySelector("input[name='district_name[]']");
    if (distInput) {
      distInput.addEventListener("input", () => scheduleFetchEffectiveRate(row));
    }
  }

  const adjType = row.querySelector(".diesel-adj-type");
  const adjAmount = row.querySelector(".diesel-adj-amount");
  const adjDate = row.querySelector(".diesel-effective-date");
  [adjType, adjAmount, adjDate].forEach((el) => {
    if (el) el.addEventListener("change", () => recalcRateRow(row));
    if (el && el.classList.contains("diesel-adj-amount")) {
      el.addEventListener("input", () => recalcRateRow(row));
    }
  });

  const radios = row.querySelectorAll("input[type='radio']");
  radios.forEach((r) =>
    r.addEventListener("change", () => scheduleFetchEffectiveRate(row))
  );

  const btn = row.querySelector(".btn-rate-history");
  if (btn) {
    btn.addEventListener("click", () => openRateRevisionHistory(btn));
  }
}

function initRateDieselRows() {
  document.querySelectorAll(".rate-slab-row").forEach((row) => {
    initRateRowListeners(row);
  });
}

function openRateRevisionHistory(btn) {
  const contractId = document.getElementById("contract_id_for_rates")?.value;
  if (!contractId) return;

  const rateCategory = btn.dataset.rateCategory || "kilometer_wise";
  const params = new URLSearchParams({
    contract_id: contractId,
    rate_category: rateCategory,
  });

  if (rateCategory === "taluka_wise") {
    const districtName = btn.dataset.districtName || "";
    const talukaName = btn.dataset.talukaName || "";
    params.append("district_name", districtName);
    params.append("taluka_name", talukaName);
  } else if (rateCategory === "district_wise") {
    const districtName = btn.dataset.districtName || "";
    params.append("district_name", districtName);
  } else {
    const fromKm = btn.dataset.fromKm || "";
    const toKm = btn.dataset.toKm || "";
    params.append("from_km", fromKm);
    params.append("to_km", toKm);
  }

  const tbody = document.getElementById("rateRevisionHistoryBody");
  const modalEl = document.getElementById("rateRevisionHistoryModal");
  if (!tbody || !modalEl) return;

  tbody.innerHTML = "<tr><td colspan='6' class='text-center'>Loading…</td></tr>";

  const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
  modal.show();

  fetch(`/api/get-rate-revision-history?${params.toString()}`)
    .then((r) => r.json())
    .then((data) => {
      if (!data.revisions || data.revisions.length === 0) {
        tbody.innerHTML =
          "<tr><td colspan='6' class='text-muted text-center'>No diesel / rate revisions recorded for this slab.</td></tr>";
        return;
      }
      tbody.innerHTML = data.revisions
        .map(
          (rev) => `
        <tr>
          <td>${rev.effective_from}</td>
          <td class="text-capitalize">${rev.adjustment_type}</td>
          <td class="text-end">${rev.adjustment_amount}</td>
          <td class="text-end">${rev.base_value}</td>
          <td class="text-end"><strong>${rev.updated_value}</strong></td>
          <td class="text-muted small">${rev.created_at}</td>
        </tr>`
        )
        .join("");
    })
    .catch(() => {
      tbody.innerHTML =
        "<tr><td colspan='6' class='text-danger text-center'>Could not load history.</td></tr>";
    });
}

function getActiveRateCategory() {
  const rateType = document.getElementById("rate_type")?.value;
  const map = {
    "Kilometer-Wise": "kilometer_wise",
    "Slab-Wise": "kilometer_wise",
    "Incometax-Wise": "incometax_wise",
    "Cumulative-Wise": "cumulative_wise",
    "Taluka-Wise": "taluka_wise",
    "Distric-Wise": "district_wise"
  };
  return map[rateType] || "kilometer_wise";
}

function buildDieselCellsHtml() {
  const category = getActiveRateCategory();
  return `
    <td class="diesel-adj-cell">
      <div class="diesel-adj-inline">
        <select name="diesel_adj_type[]" class="form-select form-select-sm diesel-adj-type" onchange="recalcRateRow(this.closest('tr'))" title="Increase or decrease">
          <option value="">None</option>
          <option value="increase">+ Inc</option>
          <option value="decrease">− Dec</option>
        </select>
        <input type="number" step="any" name="diesel_adj_amount[]" class="form-control form-control-sm diesel-adj-amount"
          placeholder="Amount" oninput="recalcRateRow(this.closest('tr'))" title="Adjustment amount">
      </div>
    </td>
    <td>
      <input type="date" name="diesel_effective_date[]" class="form-control form-control-sm rate-effective-date diesel-effective-date"
        onchange="recalcRateRow(this.closest('tr'))" title="Applies from this date">
    </td>
    <td>
      <input type="text" class="form-control form-control-sm rate-updated-value" readonly tabindex="-1"
        data-effective-rate="" title="Current rate applicable today">
    </td>
    <td class="text-center">
      <button type="button" class="btn btn-outline-info btn-sm btn-rate-history"
        data-rate-category="${category}">View</button>
    </td>`;
}

function setupRateDieselSubmitValidation() {
  const form = document.getElementById("formAuthentication");
  if (!form) return;

  form.addEventListener("submit", function (e) {
    const rows = document.querySelectorAll(".rate-slab-row");
    let hasError = false;
    let errorMsg = "";

    rows.forEach(function (row, idx) {
      const typeEl = row.querySelector(".diesel-adj-type");
      const amountEl = row.querySelector(".diesel-adj-amount");
      const dateEl = row.querySelector(".diesel-effective-date");

      if (typeEl && amountEl && dateEl) {
        const type = typeEl.value;
        const amount = parseFloat(amountEl.value);
        const dateVal = dateEl.value;

        // If type is selected or amount is entered, but effective date is missing
        if ((type || amount > 0) && !dateVal) {
          hasError = true;
          row.style.outline = "2px solid #ff3e1d"; // Highlight row with error border
          row.style.outlineOffset = "-2px";
          
          let desc = "Row #" + (idx + 1);
          const fromKm = row.querySelector("input[name='from_km[]']")?.value;
          const toKm = row.querySelector("input[name='to_km[]']")?.value;
          const distInput = row.querySelector("input[name='district_name[]']") || row.closest(".card")?.querySelector("input[name='district_name[]']");
          const dist = distInput ? distInput.value : "";
          const talukaInput = row.querySelector("input[name^='taluka_name_']");
          const taluka = talukaInput ? talukaInput.value : "";

          if (fromKm && toKm) {
            desc = `Kilometer slab ${fromKm} - ${toKm} km`;
          } else if (dist && taluka) {
            desc = `District '${dist}', Taluka '${taluka}'`;
          } else if (dist) {
            desc = `District '${dist}'`;
          }
          errorMsg = `Please specify the "Effective From" date for the diesel adjustment on: ${desc}.`;
        } else {
          row.style.outline = ""; // Reset
        }
      }
    });

    if (hasError) {
      e.preventDefault();
      e.stopPropagation();
      alert(errorMsg);
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initRateDieselRows();
  setupRateDieselSubmitValidation();
});
