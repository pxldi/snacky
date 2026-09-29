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
