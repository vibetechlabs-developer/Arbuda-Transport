console.log("hello i am auth");

// Clear visual error state and inline message for a single field
function clearFieldError(input) {
  if (!input) return;
  // Remove both custom "invalid" and Bootstrap-style "is-invalid" classes
  input.classList.remove("invalid", "is-invalid");
  const group = input.closest(".input-group");
  const anchor = group || input;
  const fb = anchor.nextElementSibling;
  if (fb && fb.classList && fb.classList.contains("invalid-feedback")) {
    fb.remove();
  }
}

function registraion_validation(form) {
  function ensureFeedbackEl(input) {
    // If the input is inside an input-group, show feedback after the group
    const group = input.closest(".input-group");
    const anchor = group || input;

    let fb = anchor.nextElementSibling;
    if (!fb || !fb.classList || !fb.classList.contains("invalid-feedback")) {
      fb = document.createElement("div");
      fb.className = "invalid-feedback d-block";
      fb.setAttribute("role", "alert");
      anchor.insertAdjacentElement("afterend", fb);
    }
    return fb;
  }

  function setError(input, message) {
    if (!input) return;
    input.classList.add("invalid");
    const fb = ensureFeedbackEl(input);
    fb.textContent = message;
  }

  function clearError(input) {
    clearFieldError(input);
  }

  let status = true;
  let company_name = form.company_name;
  let gstin = form.gstin;
  let email = form.email;
  let pass = form.password;
  let rpass = form.rpassword;
  let mobile = form.mobile;
  let tc = form.tc;

  const gstPattern =
    /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/;
  const emailPattern = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
  const mobilePattern = /^[6-9][0-9]{9}$/;

  if (company_name.value.length <= 0 || company_name.value.length > 20) {
    setError(company_name, "Company name is required (max 20 characters).");
    status = false;
  } else {
    clearError(company_name);
  }
  if (gstin.value.length <= 0 || !gstPattern.test(gstin.value)) {
    setError(gstin, "Enter a valid GST number.");
    status = false;
  } else {
    clearError(gstin);
  }
  if (!emailPattern.test(email.value) || email.value.length <= 0) {
    setError(email, "Enter a valid email address.");
    status = false;
  } else {
    clearError(email);
  }

  if (pass.value.length <= 0) {
    setError(pass, "Password is required.");
    status = false;
  } else {
    clearError(pass);
  }
  if (rpass.value.length <= 0 || pass.value != rpass.value) {
    setError(
      rpass,
      rpass.value.length <= 0 ? "Confirm password is required." : "Passwords do not match."
    );
    status = false;
  } else {
    clearError(rpass);
  }
  if (mobile.value.length <= 0 || !mobilePattern.test(mobile.value)) {
    setError(mobile, "Enter a valid 10-digit mobile number.");
    status = false;
  } else {
    clearError(mobile);
  }
  if (!tc.checked) {
    setError(tc, "Please accept the privacy policy & terms.");
    status = false;
  } else {
    clearError(tc);
  }

  return status;
}

function company_profile_validation(form) {

  let status = true;
  let company_name = form.company_name;
  let buss_type = form.buss_type;
  let indu_type = form.indu_type;
  let gst_number = form.gst_number;
  let pan_number = form.pan_number;
  let tan_number = form.tan_number;
  let cin_number = form.cin_number;
  let address = form.address;
  let state = form.state;
  let city = form.city;
  let pin = form.pin;
  let email = form.email;
  let mobile = form.phone;
  
  console.log("hello am validator" + email.value.length);
  const gstPattern =
    /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/;
  const emailPattern = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
  const mobilePattern = /^[6-9][0-9]{9}$/;
  const panRegex = /^[A-Z]{5}[0-9]{4}[A-Z]{1}$/;
  const tanRegex = /^[A-Z]{4}[0-9]{5}[A-Z]{1}$/;
  const cinRegex = /^[LU]{1}[0-9]{5}[A-Z]{2}[0-9]{4}(PLC|PTC)[0-9]{6}$/;
  const pinRegex = /^[1-9][0-9]{5}$/;


  if (company_name.value.length <= 0 || company_name.value.length > 20) {
    company_name.classList.add("invalid");
    status = false;
  }
  if (buss_type.value.length <= 0 || buss_type.value.length > 50) {
    buss_type.classList.add("invalid");
    status = false;
  }
  if (indu_type.value.length <= 0 || indu_type.value.length > 50) {
    indu_type.classList.add("invalid");
    status = false;
  }
  if (pan_number.value.length <= 0 || !panRegex.test(pan_number.value)) {
    pan_number.classList.add("invalid");
    status = false;
  }
  if (gst_number.value.length <= 0 || !gstPattern.test(gst_number.value)) {
    gst_number.classList.add("invalid");
    status = false;
  }
  if (tan_number.value.length <= 0 || !tanRegex.test(tan_number.value)) {
    tan_number.classList.add("invalid");
    status = false;
  }
  if (cin_number.value.length <= 0 || !cinRegex.test(cin_number.value)) {
    cin_number.classList.add("invalid");
    status = false;
  }
  if (!emailPattern.test(email.value) || email.value.length <= 0) {
    email.classList.add("invalid");
    status = false;
  }
  if (mobile.value.length <= 0 || !mobilePattern.test(mobile.value)) {
    mobile.classList.add("invalid");
    status = false;
  }
   if (address.value.length <= 0 || address.value.length > 100) {
    address.classList.add("invalid");
    status = false;
  }
   if (state.value.length <= 0 || state.value.length > 20) {
    state.classList.add("invalid");
    status = false;
  }
   if (city.value.length <= 0 || city.value.length > 50) {
    city.classList.add("invalid");
    status = false;
  }
   if (pin.value.length <= 0 || !pinRegex.test(pin.value)) {
    pin.classList.add("invalid");
    status = false;
  }

  return status;
}

// Automatically clear inline errors for Company Profile fields as user types
document.addEventListener("DOMContentLoaded", function () {
  var form = document.getElementById("formAuthentication");
  if (!form) return;
  var fields = form.querySelectorAll("input, textarea, select");
  fields.forEach(function (field) {
    field.addEventListener("input", function () {
      clearFieldError(field);
    });
  });
});
function client_profile_validation(form) {

  let status = true;
  let company_name = form.company_name;
  let buss_type = form.buss_type;
  let indu_type = form.indu_type;
  let gst_number = form.gst_number;
  let pan_number = form.pan_number;
  let tan_number = form.tan_number;
  let cin_number = form.cin_number;
  let cp_name = form.cp_name;
  let c_email = form.c_email;
  let c_designation = form.c_designation;
  let c_number = form.c_number;
  let office_address = form.office_address;
  let office_state = form.office_state;
  let office_city = form.office_city;
  let office_pin = form.office_pin;
  
  const gstPattern =
    /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/;
  const emailPattern = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
  const mobilePattern = /^[6-9][0-9]{9}$/;
  const panRegex = /^[A-Z]{5}[0-9]{4}[A-Z]{1}$/;
  const tanRegex = /^[A-Z]{4}[0-9]{5}[A-Z]{1}$/;
  const cinRegex = /^[LU]{1}[0-9]{5}[A-Z]{2}[0-9]{4}(PLC|PTC)[0-9]{6}$/;
  const pinRegex = /^[1-9][0-9]{5}$/;


  if (company_name.value.length <= 0 || company_name.value.length > 20) {
    company_name.classList.add("invalid");
    status = false;
  }
  if (buss_type.value.length <= 0 || buss_type.value.length > 50) {
    buss_type.classList.add("invalid");
    status = false;
  }
  if (indu_type.value.length <= 0 || indu_type.value.length > 50) {
    indu_type.classList.add("invalid");
    status = false;
  }
  if (cp_name.value.length <= 0 || cp_name.value.length > 50) {
    cp_name.classList.add("invalid");
    status = false;
  }
  if (c_email.value.length <= 0 || c_email.value.length > 50) {
    c_email.classList.add("invalid");
    status = false;
  }
  if (c_designation.value.length <= 0 || c_designation.value.length > 50) {
    c_designation.classList.add("invalid");
    status = false;
  }
  if (c_number.value.length <= 0 || !mobilePattern.test(c_number.value)) {
    c_number.classList.add("invalid");
    status = false;
  }
  if (pan_number.value.length <= 0 || !panRegex.test(pan_number.value)) {
    pan_number.classList.add("invalid");
    status = false;
  }
  if (gst_number.value.length <= 0 || !gstPattern.test(gst_number.value)) {
    gst_number.classList.add("invalid");
    status = false;
  }
  if (tan_number.value.length <= 0 || !tanRegex.test(tan_number.value)) {
    tan_number.classList.add("invalid");
    status = false;
  }
  if (cin_number.value.length <= 0 || !cinRegex.test(cin_number.value)) {
    cin_number.classList.add("invalid");
    status = false;
  }
  if (!emailPattern.test(c_email.value) || c_email.value.length <= 0) {
    c_email.classList.add("invalid");
    status = false;
  }
   if (office_address.value.length <= 0 || office_address.value.length > 100) {
    office_address.classList.add("invalid");
    status = false;
  }
   if (office_state.value.length <= 0 || office_state.value.length > 20) {
    office_state.classList.add("invalid");
    status = false;
  }
   if (office_city.value.length <= 0 || office_city.value.length > 50) {
    office_city.classList.add("invalid");
    status = false;
  }
   if (office_pin.value.length <= 0 || !pinRegex.test(office_pin.value)) {
    office_pin.classList.add("invalid");
    status = false;
  }

  return status;
}

function contract_validation(form) {

  let status = true;
  let client_name = form.client_name;
  let tender_id = form.tender_id;
  let tender_value = form.tender_value;
  let contract_no = form.contract_no;
  let tender_title = form.tender_title;
  let payment_terms = form.payment_terms;
  let scope_work = form.scope_work;
  let d_location = form.d_location;
  let contract_end = form.contract_end;
  let project_type = form.project_type;
  let contract_start = form.contract_start;
  let cstatus = form.status


  if (client_name.value.length <= 0 || client_name.value.length > 20) {
    client_name.classList.add("invalid");
    status = false;
  }
  if (tender_id.value.length <= 0 || tender_id.value.length > 50) {
    tender_id.classList.add("invalid");
    status = false;
  }
  if (tender_value.value.length <= 0 || tender_value.value.length > 50) {
    tender_value.classList.add("invalid");
    status = false;
  }
  if (contract_no.value.length <= 0 || contract_no.value.length > 50) {
    contract_no.classList.add("invalid");
    status = false;
  }
  if (tender_title.value.length <= 0 || tender_title.value.length > 50) {
    tender_title.classList.add("invalid");
    status = false;
  }
  if (payment_terms.value.length <= 0 || payment_terms.value.length > 50) {
    payment_terms.classList.add("invalid");
    status = false;
  }
  if (scope_work.value.length <= 0 || scope_work.value.length > 50) {
    scope_work.classList.add("invalid");
    status = false;
  }
  if (d_location.value.length <= 0 || d_location.value.length > 50) {
    d_location.classList.add("invalid");
    status = false;
  }
  if (project_type.value.length <= 0 || project_type.value.length > 50) {
    project_type.classList.add("invalid");
    status = false;
  }
  if (!contract_end.value) {
    contract_end.classList.add("invalid");
    status = false;
  }
  if (!contract_start.value) {
    contract_start.classList.add("invalid");
    status = false;
  }

  let isGenderSelected = false;

  for (let i = 0; i < cstatus.length; i++) {
    if (cstatus[i].checked) {
      isGenderSelected = true;
      break;
    }
  }

  if (!isGenderSelected) {
    for (let i = 0; i < cstatus.length; i++) {
    cstatus[i].classList.add('invalid')
  }
    return false;
  }
 
  return status;
}
