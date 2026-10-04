// shop/static/shop/admin/product_attributes.js
// При смене категории подгружает поля характеристик, не перезагружая страницу.
document.addEventListener("DOMContentLoaded", () => {
  const select = document.getElementById("id_category");
  if (!select || !document.getElementById("attributes-box")) return;

  select.addEventListener("change", async () => {
    const box = document.getElementById("attributes-box");
    const url = new URL(box.dataset.url, window.location.origin);
    url.searchParams.set("category", select.value);
    if (box.dataset.productId) url.searchParams.set("product", box.dataset.productId);

    box.style.opacity = "0.5";
    try {
      const response = await fetch(url, { headers: { "X-Requested-With": "fetch" } });
      if (!response.ok) throw new Error(response.status);
      box.outerHTML = await response.text();
    } catch (e) {
      box.style.opacity = "1";
      console.error("Не удалось загрузить характеристики", e);
    }
  });
});
