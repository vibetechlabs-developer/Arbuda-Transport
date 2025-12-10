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
  row.setAttribute("id", `slab_row_${districtCount}`)
  row.innerHTML = `
  <td><input type="number" class="form-control" name="from_km[]" required></td>
  <td><input type="number" class="form-control" name="to_km[]" required></td>
  <td>
  <div class="form-check form-check-inline">
  <input class="form-check-input" type="radio" name="choice_${rowCount}" value="mt" checked onclick="updatePlaceholder(this)">
  <label class="form-check-label">Fixed Rate</label>
  </div>
  <div class="form-check form-check-inline">
          <input class="form-check-input" type="radio" name="choice_${rowCount}" value="mt_per_km" onclick="updatePlaceholder(this)">
          <label class="form-check-label">MT/KM</label>
        </div>
      </td>
      <td>
        <input type="number" class="form-control" name="value[]" placeholder="Enter MT" required step="any">
      </td>
      <td>
        <button type="button" class="btn btn-danger btn-sm" onclick="removeRow(this)">Delete</button>
      </td>
      `;
      
      tbody.appendChild(row);
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
        <div class="mb-2">
          <label>District Name</label>
          <input type="text" class="form-control" name="district_name[]" required>
        </div>
        <table class="table table-bordered">
          <thead>
            <tr>
              <th>Taluka Name</th>
              <th>Rate</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody id="taluka_table_${districtCount}"></tbody>
        </table>
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

  row.innerHTML = `
      <td><input type="text" class="form-control" name="taluka_name_${districtId}[]" required></td>
      <td><input type="number" class="form-control" name="taluka_rate_${districtId}[]" required step="any"></td>
      <td><button type="button" class="btn btn-danger btn-sm" onclick="removeRow(this)">Delete</button></td>
    `;
  tbody.appendChild(row);
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
  row.innerHTML = `
    <td><input type="text" class="form-control" name="district_name[]" required></td>
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
    <td><button type="button" class="btn btn-danger btn-sm" onclick="removeRow(this)">Delete</button></td>
  `;
  tbody.appendChild(row);
}

function removeRow(btn) {
  btn.closest("tr").remove();
}

function updateDistrictPlaceholder(radio) {
  let input = radio.closest("tr").querySelector("input[name='district_rate[]']");
  input.placeholder = (radio.value === "mt") ? "Enter MT" : "Enter MT/KM";
}

  