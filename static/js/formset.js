/*
 * Formulare cu linii dinamice (comenzi; refolosit la recepții și facturi).
 *
 * Zona marcată cu data-formset="<prefix>" conține un formset Django:
 *   - „Adaugă linie”  → clonează rândul-model din <template>, cu următorul index;
 *   - „Șterge”        → bifează câmpul DELETE și ascunde rândul (Django îl ignoră);
 *   - orice modificare → recalculează valorile liniilor și totalurile.
 * Totalurile de aici sunt doar o previzualizare: serverul recalculează tot la salvare.
 *
 * În plus: alegerea produsului completează cota de TVA, iar alegerea
 * furnizorului propune moneda (din atributele data-vat / data-currency).
 */
(function () {
  "use strict";

  const money = new Intl.NumberFormat("ro-RO", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const round2 = (value) => Math.round((value + Number.EPSILON) * 100) / 100;
  const numberIn = (row, suffix) => parseFloat(row.querySelector(`[name$="-${suffix}"]`)?.value) || 0;

  function recalculate(formset) {
    let net = 0;
    let vat = 0;
    formset.querySelectorAll("[data-line]").forEach((row) => {
      if (row.classList.contains("d-none")) return; // linie ștearsă
      const lineNet = round2(numberIn(row, "quantity") * numberIn(row, "unit_price"));
      net += lineNet;
      vat += round2((lineNet * numberIn(row, "vat_rate")) / 100);
      const cell = row.querySelector("[data-line-total]");
      if (cell) cell.textContent = money.format(lineNet);
    });
    const totals = { net: net, vat: vat, gross: net + vat };
    formset.querySelectorAll("[data-total]").forEach((cell) => {
      cell.textContent = money.format(totals[cell.dataset.total]);
    });
  }

  function addRow(formset) {
    const prefix = formset.dataset.formset;
    const totalForms = formset.querySelector(`#id_${prefix}-TOTAL_FORMS`);
    const html = formset.querySelector("template").innerHTML.replaceAll("__prefix__", totalForms.value);
    formset.querySelector("[data-formset-body]").insertAdjacentHTML("beforeend", html);
    totalForms.value = Number(totalForms.value) + 1;
    formset.querySelector("[data-formset-body] tr:last-child select")?.focus();
  }

  function removeRow(row) {
    const deleteBox = row.querySelector('input[name$="-DELETE"]');
    if (deleteBox) deleteBox.checked = true;
    row.classList.add("d-none");
  }

  document.addEventListener("click", (event) => {
    const add = event.target.closest("[data-formset-add]");
    const remove = event.target.closest("[data-formset-remove]");
    const formset = event.target.closest("[data-formset]");
    if (!formset || !(add || remove)) return;
    if (add) addRow(formset);
    if (remove) removeRow(remove.closest("[data-line]"));
    recalculate(formset);
  });

  document.addEventListener("change", (event) => {
    const field = event.target;
    // Produs ales → cota de TVA a produsului (dacă TVA nu e blocat).
    if (field.name?.endsWith("-product")) {
      const vat = field.selectedOptions[0]?.dataset.vat;
      const vatField = field.closest("[data-line]")?.querySelector('[name$="-vat_rate"]');
      if (vat && vatField && !vatField.disabled) vatField.value = vat;
    }
    // Furnizor ales → moneda lui implicită.
    if (field.id === "id_supplier") {
      const currency = field.selectedOptions[0]?.dataset.currency;
      const currencyField = document.getElementById("id_currency");
      if (currency && currencyField && !currencyField.disabled) currencyField.value = currency;
    }
  });

  document.addEventListener("input", (event) => {
    const formset = event.target.closest("[data-formset]");
    if (formset) recalculate(formset);
  });
  document.addEventListener("change", (event) => {
    const formset = event.target.closest("[data-formset]");
    if (formset) recalculate(formset);
  });

  document.querySelectorAll("[data-formset]").forEach(recalculate);
})();
