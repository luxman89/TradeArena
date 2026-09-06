const preference = matchMedia("(prefers-reduced-motion: reduce)");
const valid = ["full", "reduced", "off"];
function savedMotion() {
  try {
    return localStorage.getItem("ta-motion");
  } catch {
    return null;
  }
}
export function motion() {
  const saved = savedMotion();
  return valid.includes(saved)
    ? saved
    : preference.matches
      ? "reduced"
      : "full";
}
function applyMotion() {
  document.documentElement.dataset.motion = motion();
  document.querySelectorAll("[data-motion-control]").forEach((el) => {
    el.value = motion();
  });
  window.dispatchEvent(new CustomEvent("ta:motion", { detail: motion() }));
}
export function setMotion(value) {
  if (!valid.includes(value)) return;
  try {
    localStorage.setItem("ta-motion", value);
  } catch {
    /* Session still works. */
  }
  document.documentElement.dataset.motion = value;
  window.dispatchEvent(new CustomEvent("ta:motion", { detail: value }));
}
applyMotion();
preference.addEventListener("change", applyMotion);
window.addEventListener("storage", applyMotion);
const menu = document.querySelector(".ui-menu");
const nav = document.querySelector("#global-nav");
const mobile = matchMedia("(max-width: 767px)");
function closeMenu() {
  if (!menu) return;
  menu.hidden = !mobile.matches;
  menu.setAttribute("aria-expanded", "false");
  nav.hidden = mobile.matches;
}
if (menu) {
  closeMenu();
  mobile.addEventListener("change", closeMenu);
  menu.addEventListener("click", () => {
    nav.hidden = !nav.hidden;
    menu.setAttribute("aria-expanded", String(!nav.hidden));
  });
  nav.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && mobile.matches) {
      closeMenu();
      menu.focus();
      event.stopPropagation();
    }
  });
}
document.addEventListener("change", (event) => {
  if (event.target.matches("[data-motion-control]"))
    setMotion(event.target.value);
});
