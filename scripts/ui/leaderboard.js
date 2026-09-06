import "./shell.js";
import { icon } from "./icons.js";
import { routes } from "./routes.js";
import { el, json, state, score, pct, metricBars } from "./components.js";
const container = document.querySelector("#rankings");
const status = document.querySelector("#live-status");
const filter = document.querySelector("#division");
const refresh = document.querySelector("#refresh");
refresh.prepend(icon("refresh"));
let request = 0;
let lastUpdated = null;
let renderedDivision = null;
function fromURL() {
  const value = new URL(location.href).searchParams.get("division");
  filter.value = ["crypto", "polymarket", "multi", "season"].includes(value)
    ? value
    : "all";
}
fromURL();
function render(data, division) {
  const season = division === "season";
  document.querySelector("#ranking-period").textContent = season
    ? `${data.season_label} · weekly win rate`
    : "All-time · composite reputation";
  document.querySelector("#sample-note").textContent = season
    ? "Weekly ranking requires at least 1 resolved prediction submitted this week. Small samples are provisional; all-time scores use a different period."
    : "Ranking requires at least 20 resolved predictions. Submitted counts include pending predictions. Scores use the full available history.";
  document.querySelector("#total-count").textContent =
    `Showing ${data.entries.length} of ${data.total} competitors`;
  if (!data.entries.length) {
    state(
      container,
      "empty",
      "The next reputation starts here",
      "No competitors meet the sample requirement in this view. Explore another division or submit your first prediction.",
      {
        label: "Explore all divisions",
        run: () => {
          filter.value = "all";
          changeFilter();
        },
      },
    );
    return;
  }
  const list = el("ol", {
    class: "ui-ranking",
    "aria-label": "Ranked competitors",
  });
  data.entries.forEach((entry, index) => {
    const row = el(
      "div",
      { class: "ui-rank-row" },
      el(
        "span",
        { class: "ui-data ui-muted" },
        String(index + 1).padStart(2, "0"),
      ),
      el(
        "div",
        {},
        el("a", { href: routes.trader(entry.creator_id) }, entry.display_name),
        el("small", {}, entry.division),
      ),
      el(
        "div",
        {},
        el(
          "strong",
          {},
          season ? pct(entry.season_win_rate) : score(entry.composite_score),
        ),
        el("small", {}, season ? "Weekly win rate" : "Score / 100"),
      ),
      el(
        "div",
        { class: "ui-data" },
        String(season ? entry.season_resolved : entry.total_signals),
        el("small", {}, season ? "Resolved this week" : "Submitted · all-time"),
      ),
      el(
        "span",
        { class: "ui-badge" },
        season ? "Weekly · provisional" : "20+ resolved",
      ),
    );
    const details = el(
      "details",
      {},
      el("summary", {}, "Why this score?"),
      season
        ? el(
            "p",
            { class: "ui-muted" },
            `${entry.season_wins} wins / ${entry.season_resolved} resolved this week. All-time composite: ${score(entry.composite_score)} / 100.`,
          )
        : metricBars(entry),
      el(
        "a",
        { href: routes.trader(entry.creator_id) },
        "Inspect prediction evidence →",
      ),
    );
    list.append(el("li", {}, row, details));
  });
  const header = el(
    "div",
    { class: "ui-rank-head", "aria-hidden": "true" },
    el("span", {}, "Rank"),
    el("span", {}, "Competitor"),
    el("span", {}, season ? "Win rate" : "Composite"),
    el("span", {}, "Sample"),
    el("span", {}, "Ranking basis"),
  );
  container.replaceChildren(header, list);
}
async function load() {
  const token = ++request;
  const division = filter.value;
  const preserve = renderedDivision === division;
  refresh.disabled = true;
  status.textContent = preserve
    ? "Refreshing · previous results remain visible"
    : "Loading rankings…";
  status.dataset.state = "loading";
  if (!preserve)
    state(
      container,
      "loading",
      "Loading the leaderboard",
      "Retrieving committed prediction scores.",
    );
  try {
    const url =
      "/leaderboard" + (division === "all" ? "" : "/" + division) + "?limit=50";
    const data = await json(url);
    if (token !== request) return;
    // Keep expanded evidence and keyboard focus stable on background updates.
    const opened = [...container.querySelectorAll("details")].map((d, i) =>
      d.open ? i : -1,
    );
    const focused = document.activeElement;
    const focusIndex = [...container.querySelectorAll("a, summary")].indexOf(
      focused,
    );
    render(data, division);
    if (preserve) {
      opened.forEach((i) => {
        const detail = container.querySelectorAll("details")[i];
        if (detail) detail.open = true;
      });
      if (focusIndex >= 0)
        container
          .querySelectorAll("a, summary")
          [focusIndex]?.focus({ preventScroll: true });
    }
    renderedDivision = division;
    lastUpdated = new Date().toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    status.textContent = `Updated ${lastUpdated} · refreshes every 30s`;
    status.dataset.state = "success";
  } catch {
    if (token !== request) return;
    status.dataset.state = preserve ? "stale" : "error";
    status.textContent = preserve
      ? `Updates interrupted · last updated ${lastUpdated}`
      : "Rankings unavailable";
    if (!preserve)
      state(
        container,
        "error",
        "Rankings are temporarily unavailable",
        "Please retry. No scores have been substituted.",
        { label: "Retry rankings", run: load },
      );
  } finally {
    if (token === request) refresh.disabled = false;
  }
}
function changeFilter() {
  const url = new URL(location.href);
  url.searchParams.set("division", filter.value);
  history.pushState({}, "", url);
  load();
}
filter.addEventListener("change", changeFilter);
refresh.addEventListener("click", load);
window.addEventListener("popstate", () => {
  fromURL();
  load();
});
window.addEventListener("online", load);
setInterval(() => {
  if (!document.hidden && !refresh.disabled) load();
}, 30000);
load();
