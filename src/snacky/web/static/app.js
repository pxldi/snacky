// Stops a second tap from logging the same quick item twice on a slow
// connection. The forms work without this file.
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || form.method !== "post") return;
  window.setTimeout(() => {
    for (const button of form.querySelectorAll("button[type=submit]")) button.disabled = true;
  }, 0);
});

// Back/forward restores the page from cache with the buttons still disabled.
window.addEventListener("pageshow", (event) => {
  if (!event.persisted) return;
  for (const button of document.querySelectorAll("button[type=submit]")) button.disabled = false;
});

// The undo notice is only valid for a couple of minutes. Dropping the query
// keeps a reload or a bookmark from showing it again.
{
  const url = new URL(window.location.href);
  if (url.searchParams.has("undo")) {
    url.searchParams.delete("undo");
    window.history.replaceState(null, "", url.pathname + url.search + url.hash);
  }
}

// Live preview of a search result: the server prints the values for the
// default amount, this keeps them in step while the grams change.
for (const form of document.querySelectorAll("form.result")) {
  const input = form.querySelector("input[data-grams]");
  if (!input) continue;
  const protein100 = Number(form.dataset.protein100);
  const kcal100 = Number(form.dataset.kcal100);
  const show = (selector, value, digits) => {
    const out = form.querySelector(selector);
    if (out) out.textContent = value.toLocaleString("de-DE", { maximumFractionDigits: digits });
  };
  input.addEventListener("input", () => {
    const grams = Number(input.value.trim().replace(",", "."));
    if (!Number.isFinite(grams) || grams <= 0) return;
    show("[data-out-grams]", grams, 1);
    show("[data-out-protein]", (grams * protein100) / 100, 1);
    show("[data-out-kcal]", (grams * kcal100) / 100, 0);
  });
}
