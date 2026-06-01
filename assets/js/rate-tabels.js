let rowCount = 0;


document.addEventListener("DOMContentLoaded", function () {
  // Count already existing districts from template
  rowCount = document.querySelectorAll('[id^="slab_row_"]').length;
  console.log("Initial rowCount count = " + rowCount);
});



function toggleRateType() {
  let type = document.getElementById("rate_type").value;
  document.getElementById("kmWiseTable").style.display =
    type === "Kilometer-Wise" || type === "Incometax-Wise" || type === "Cumulative-Wise" ? "block" : "none";

  document.getElementById("talukaWiseTable").style.display =
    type === "Taluka-Wise" ? "block" : "none";
        // Toggle District table
        document.getElementById("districtWiseTable").style.display =
    type === "Distric-Wise" ? "block" : "none";

}
                   
function addRow() {
  let tbody = document.getElementById("rate-table");
  let row = document.createElement("tr");
  rowCount++;
  row.classList.add("rate-slab-row");
  row.setAttribute("id", `slab_row_${rowCount}`);
  if (typeof getActiveRateCategory === "function") {
    row.dataset.rateCategory = getActiveRateCategory();
  }
  const dieselCells =
    typeof buildDieselCellsHtml === "function" ? buildDieselCellsHtml() : "";
  row.innerHTML = `
  <td><input type="number" class="form-control rate-km-input" name="from_km[]" required oninput="syncSlabDataAttrs(this.closest('tr'))"></td>
  <td><input type="number" class="form-control rate-km-input" name="to_km[]" required oninput="syncSlabDataAttrs(this.closest('tr'))"></td>
  <td class="rate-choice-cell">
    <div class="rate-choice-group">
      <label class="rate-choice-option">
        <input class="form-check-input" type="radio" name="choice_${rowCount}" value="mt" checked onclick="updatePlaceholder(this)">
        Fixed Rate
      </label>
      <label class="rate-choice-option">
        <input class="form-check-input" type="radio" name="choice_${rowCount}" value="mt_per_km" onclick="updatePlaceholder(this)">
        MT/KM
      </label>
    </div>
  </td>
  <td>
    <input type="number" class="form-control rate-value-input" name="value[]" placeholder="0.0000" required step="any">
  </td>
  ${dieselCells}
  <td class="text-center">
    <button type="button" class="btn btn-danger btn-sm" onclick="removeRow(this)">Delete</button>
  </td>
  `;

      tbody.appendChild(row);
      const historyBtn = row.querySelector(".btn-rate-history");
      if (historyBtn) {
        historyBtn.addEventListener("click", () => openRateRevisionHistory(historyBtn));
      }
      if (typeof fetchEffectiveRateForRow === "function") {
        fetchEffectiveRateForRow(row);
      } else {
        recalcRateRow(row);
      }
}

function syncSlabDataAttrs(row) {
  if (!row) return;
  const from = row.querySelector("input[name='from_km[]']");
  const to = row.querySelector("input[name='to_km[]']");
  const btn = row.querySelector(".btn-rate-history");
  if (btn && from) btn.dataset.fromKm = from.value;
  if (btn && to) btn.dataset.toKm = to.value;
}

function removeRow(btn) {
  btn.closest("tr").remove();
}

function updatePlaceholder(radio) {
  let input = radio.closest("tr").querySelector("input[name='value[]']");
  if (radio.value === "mt") {
    input.placeholder = "Enter Fixed Rate";
  } else {
    input.placeholder = "Enter MT/KM";
  }
}

// ---------- Taluka Wise ----------

let districtCount = 0;

document.addEventListener("DOMContentLoaded", function () {
  // Count already existing districts from template
  districtCount = document.querySelectorAll('[id^="district_"]').length;
  console.log("Initial district count = " + districtCount);
});

function addDistrict() {
  districtCount++;
  let container = document.getElementById("district-container");

  let districtDiv = document.createElement("div");
  districtDiv.classList.add("card", "p-3", "mb-3");
  districtDiv.setAttribute("id", `district_${districtCount}`);

  districtDiv.innerHTML = `
        <input type="hidden" name="district_index[]" value="${districtCount}">
        <div class="mb-2">
          <label>District Name</label>
          <input type="text" class="form-control" name="district_name[]" required oninput="syncAllTalukasInDistrict(this.closest('.card'), ${districtCount})">
        </div>
        <div class="rate-slab-table-wrap">
        <table class="table table-bordered rate-slab-table mb-0">
          <thead>
            <tr>
              <th class="col-value">Taluka Name</th>
              <th class="col-value">Rate</th>
              <th class="col-diesel">Diesel (+/−)</th>
              <th class="col-effective">Effective From</th>
              <th class="col-updated">Current Rate</th>
              <th class="col-history">History</th>
              <th class="col-action">Action</th>
            </tr>
          </thead>
          <tbody id="taluka_table_${districtCount}"></tbody>
        </table>
        </div>
        <div class="d-flex gap-2 mt-2">
        <button type="button" class="btn btn-success " onclick="addTaluka(${districtCount})">+ Add Taluka</button>
        <button type="button" class="btn btn-danger " onclick="removeDistrict(${districtCount})">Remove District</button>
        </div>
      `;

  container.appendChild(districtDiv);
}

function addTaluka(districtId) {
  let tbody = document.getElementById(`taluka_table_${districtId}`);
  let row = document.createElement("tr");
  row.classList.add("rate-slab-row");
  row.dataset.rateCategory = "taluka_wise";

  const dieselCells = typeof buildDieselCellsHtml === "function" ? buildDieselCellsHtml() : "";

  row.innerHTML = `
      <td><input type="text" class="form-control" name="taluka_name_${districtId}[]" required oninput="syncTalukaDataAttrs(this.closest('tr'), ${districtId})"></td>
      <td><input type="number" class="form-control" name="taluka_rate_${districtId}[]" required step="any"></td>
      ${dieselCells}
      <td><button type="button" class="btn btn-danger btn-sm" onclick="removeRow(this)">Delete</button></td>
    `;
  tbody.appendChild(row);
  if (typeof initRateRowListeners === "function") {
    initRateRowListeners(row);
  }
}

function syncTalukaDataAttrs(row, districtId) {
  if (!row) return;
  const talukaNameInput = row.querySelector(`input[name='taluka_name_${districtId}[]']`);
  const districtNameInput = row.closest(".card")?.querySelector("input[name='district_name[]']");
  const btn = row.querySelector(".btn-rate-history");
  if (btn && talukaNameInput) btn.dataset.talukaName = talukaNameInput.value;
  if (btn && districtNameInput) btn.dataset.districtName = districtNameInput.value;
}

function syncAllTalukasInDistrict(card, districtId) {
  if (!card) return;
  const districtNameInput = card.querySelector("input[name='district_name[]']");
  if (!districtNameInput) return;
  card.querySelectorAll(".rate-slab-row").forEach((row) => {
    const btn = row.querySelector(".btn-rate-history");
    if (btn) btn.dataset.districtName = districtNameInput.value;
  });
}

function removeDistrict(id) {
  document.getElementById(`district_${id}`).remove();
}

// distric wise

let districtCount1 = 0;
document.addEventListener("DOMContentLoaded", function () {
  // Count already existing districts from template
  districtCount1 = document.querySelectorAll('[id^="district_"]').length;
  console.log("Initial district count = " + districtCount1);
});

function addDistrictRow() {
  districtCount1++;
  let tbody = document.getElementById("district-table-body");
  let row = document.createElement("tr");
  row.classList.add("rate-slab-row");
  row.dataset.rateCategory = "district_wise";

  const dieselCells = typeof buildDieselCellsHtml === "function" ? buildDieselCellsHtml() : "";

  row.innerHTML = `
    <td><input type="text" class="form-control" name="district_name[]" required oninput="syncDistrictDataAttrs(this.closest('tr'))"></td>
    <td>
      <div class="form-check form-check-inline">
        <input class="form-check-input" type="radio" name="district_choice_${districtCount1}" value="mt" checked onclick="updateDistrictPlaceholder(this)">
        <label class="form-check-label">MT</label>
      </div>
      <div class="form-check form-check-inline">
        <input class="form-check-input" type="radio" name="district_choice_${districtCount1}" value="mt_per_km" onclick="updateDistrictPlaceholder(this)">
        <label class="form-check-label">MT/KM</label>
      </div>
    </td>
    <td><input type="number" class="form-control" name="district_rate[]" placeholder="Enter MT" required step="any"></td>
    ${dieselCells}
    <td><button type="button" class="btn btn-danger btn-sm" onclick="removeRow(this)">Delete</button></td>
  `;
  tbody.appendChild(row);
  if (typeof initRateRowListeners === "function") {
    initRateRowListeners(row);
  }
}

function syncDistrictDataAttrs(row) {
  if (!row) return;
  const districtNameInput = row.querySelector("input[name='district_name[]']");
  const btn = row.querySelector(".btn-rate-history");
  if (btn && districtNameInput) btn.dataset.districtName = districtNameInput.value;
}

function removeRow(btn) {
  btn.closest("tr").remove();
}

function updateDistrictPlaceholder(radio) {
  let input = radio.closest("tr").querySelector("input[name='district_rate[]']");
  input.placeholder = (radio.value === "mt") ? "Enter MT" : "Enter MT/KM";
}

  