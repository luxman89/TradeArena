import "./shell.js";
import {
  el,
  state,
  score,
  scoreSummary,
  metricBars,
  loadSignals,
} from "./components.js";
import { routes } from "./routes.js";
const list = document.querySelector("#spectator-list");
const status = document.querySelector("#arena-status");
const panel = document.querySelector("#panel");
let selectedId = null;
let returnFocus = null;
let updated = null;
function inspect(creator) {
  selectedId = creator.creator_id;
  returnFocus = document.activeElement;
  document.querySelector("#inspector-title").textContent = creator.display_name;
  const signals = el("div", { "aria-live": "polite" });
  document
    .querySelector("#ptab-stats")
    .replaceChildren(
      el(
        "a",
        { href: routes.trader(creator.creator_id) },
        "Open full reputation profile →",
      ),
      scoreSummary(creator, creator.total_signals),
      metricBars(creator),
      el("h3", {}, "Prediction evidence"),
      signals,
    );
  window.switchPanelTab("stats");
  if (!panel.open) panel.showModal();
  panel.classList.add("open");
  document.querySelector("#p-close").focus();
  loadSignals(
    signals,
    creator.creator_id,
    () => panel.open && selectedId === creator.creator_id,
  );
}
panel.addEventListener("close", () => {
  selectedId = null;
  panel.classList.remove("open");
  if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
});
panel.addEventListener("cancel", (event) => {
  event.stopPropagation();
});
document.addEventListener("ta:inspect", (event) => inspect(event.detail));
function render(entries) {
  updated = new Date().toLocaleTimeString();
  status.textContent = `Record updated ${updated} · polls every 30s`;
  status.dataset.state = "success";
  if (!entries.length) {
    state(
      list,
      "empty",
      "The floor is waiting",
      "Competitors appear after 20 resolved predictions. Explore the methodology to get started.",
    );
    return;
  }
  const focusedId = document.activeElement?.dataset.creator;
  list.replaceChildren(
    ...entries.map((creator) =>
      el(
        "button",
        {
          class: "ui-spectator",
          "data-creator": creator.creator_id,
          onclick: () => window.openPanel({ creator }),
        },
        el("span", { class: "ui-badge" }, creator.division),
        el("span", {}, creator.display_name),
        el("strong", {}, score(creator.composite_score)),
        el(
          "span",
          { class: "ui-status" },
          `${creator.total_signals} submitted · all-time score / 100`,
        ),
        el("span", { class: "ui-status" }, "Inspect evidence →"),
      ),
    ),
  );
  if (focusedId)
    [...list.querySelectorAll("button")]
      .find((b) => b.dataset.creator === focusedId)
      ?.focus({ preventScroll: true });
}
state(
  list,
  "loading",
  "Loading competitors",
  "The public record remains available independently of the pixel floor.",
);
if (window.arenaEntries) render(window.arenaEntries);
document.addEventListener("ta:record", (event) => render(event.detail));
document.addEventListener("ta:record-error", () => {
  status.dataset.state = updated ? "stale" : "error";
  status.textContent = updated
    ? `Updates interrupted · last record ${updated}`
    : "Public record unavailable";
  if (!updated)
    state(
      list,
      "error",
      "Unable to load competitors",
      "Retry the public record above. The floor is only a visualization.",
    );
});
new ResizeObserver(() => window.resize?.()).observe(
  document.querySelector("#arena"),
);
const sound = document.querySelector("#mute-btn");
sound.textContent = "Sound off";
sound.setAttribute("aria-pressed", "false");
sound.addEventListener("click", () => {
  const enabled = sound.textContent.includes("ON");
  sound.setAttribute("aria-pressed", String(enabled));
  sound.textContent = enabled ? "Sound on" : "Sound off";
});
// Attach labels to the retained submission form.
for (const id of [
  "sig-asset",
  "sig-action",
  "sig-conf",
  "sig-reasoning",
  "sig-timeframe",
]) {
  const input = document.getElementById(id);
  const label = input.previousElementSibling;
  if (label?.tagName === "LABEL") label.htmlFor = id;
}
document.querySelector("#sig-err-msg").setAttribute("role", "alert");
