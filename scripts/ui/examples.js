import "./shell.js";
import { el, state, scoreSummary, metricBars } from "./components.js";
const root = document.querySelector("#examples");
const values = {
  composite: 0.71,
  win_rate: 0.72,
  risk_adjusted_return: 0.68,
  consistency: 0.75,
  confidence_calibration: 0.69,
};
root.append(
  el("section", { class: "ui-panel" }, scoreSummary(values, 30, 24, 6)),
  el("section", { class: "ui-panel" }, metricBars(values)),
);
for (const [kind, title, description] of [
  ["loading", "Loading evidence", "The initial request is in progress."],
  [
    "empty",
    "No predictions yet",
    "Public commitments appear here after submission.",
  ],
  ["error", "Evidence unavailable", "Retry the request to recover."],
  [
    "stale",
    "Updates interrupted",
    "Previously loaded evidence remains visible.",
  ],
]) {
  const region = el("section", { "aria-label": title });
  state(
    region,
    kind,
    title,
    description,
    kind === "error"
      ? {
          label: "Retry example",
          run: () => {
            document.querySelector("#example-feedback").textContent =
              "Example retry completed.";
          },
        }
      : null,
  );
  root.append(region);
}
