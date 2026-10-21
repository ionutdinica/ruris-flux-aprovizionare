/*
 * Formularul facturii (în completarea static/js/formset.js).
 *
 *   - Furnizor schimbat → liniile de comandă disponibile se reîncarcă de la server
 *     (doar comenzile acelui furnizor), în toate rândurile și în rândul-model.
 *   - Linie de comandă aleasă → se propun prețul și TVA din comandă și cantitatea
 *     recepționată, încă nefacturată. Contabilul le corectează după factura reală:
 *     diferențele sunt exact ce prinde potrivirea la validare.
 */
(function () {
  "use strict";

  const form = document.querySelector("[data-invoice-form]");
  if (!form) return;

  const lineSelects = () => [
    ...form.querySelectorAll('select[name$="-order_line"]'),
    ...form.querySelector("[data-formset] template").content.querySelectorAll('select[name$="-order_line"]'),
  ];

  async function reloadOrderLines(supplierId) {
    form.querySelector("[data-no-supplier]").hidden = Boolean(supplierId);
    const url = `${form.dataset.optionsUrl}?furnizor=${encodeURIComponent(supplierId)}`;
    const response = await fetch(url, { headers: { "HX-Request": "true" } });
    if (!response.ok) return;
    const fresh = new DOMParser().parseFromString(await response.text(), "text/html").querySelector("select");
    lineSelects().forEach((select) => {
      const current = select.value;
      select.innerHTML = fresh.innerHTML;
      // O linie deja aleasă rămâne aleasă, dacă aparține și noului furnizor.
      select.value = [...select.options].some((o) => o.value === current) ? current : "";
    });
  }

  function proposeFromOrderLine(select) {
    const option = select.selectedOptions[0];
    const row = select.closest("[data-line]");
    if (!option || !option.value || !row) return;
    const set = (suffix, value) => {
      const field = row.querySelector(`[name$="-${suffix}"]`);
      if (field && value !== undefined) field.value = value;
    };
    set("unit_price", option.dataset.price);
    set("vat_rate", option.dataset.vat);
    const quantity = row.querySelector('[name$="-quantity"]');
    if (quantity && !quantity.value) set("quantity", option.dataset.remaining);
    quantity?.dispatchEvent(new Event("input", { bubbles: true })); // totalurile se recalculează
  }

  form.addEventListener("change", (event) => {
    if (event.target.id === "id_supplier") reloadOrderLines(event.target.value);
    if (event.target.name?.endsWith("-order_line")) proposeFromOrderLine(event.target);
  });
})();
