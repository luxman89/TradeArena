import "./shell.js";
import "./profile-social.js";
import { routes } from "./routes.js";
import {
  el,
  json,
  state,
  metricBars,
  scoreSummary,
  loadSignals,
  date,
} from "./components.js";
const id = decodeURIComponent(
  location.pathname.split("/").filter(Boolean).pop(),
);
const content = document.querySelector("#profile-content");
const status = document.querySelector("#profile-status");
async function load() {
  state(
    content,
    "loading",
    "Loading public reputation",
    "Retrieving scores and their evidence.",
  );
  status.textContent = "Loading profile…";
  try {
    const [profile, stats] = await Promise.all([
      json(routes.profile(id)),
      json(routes.stats(id)),
    ]);
    const resolved =
      stats.signals.wins + stats.signals.losses + stats.signals.neutrals;
    document.title = profile.display_name + " — TradeArena";
    const signals = el("div", { id: "signals-list", "aria-live": "polite" });
    const header = el(
      "header",
      { class: "ui-stack" },
      el("a", { href: routes.leaderboard }, "← All competitors"),
      el(
        "div",
        { class: "ui-cluster" },
        el(
          "div",
          { class: "ui-avatar", "aria-hidden": "true" },
          profile.display_name.charAt(0),
        ),
        el(
          "div",
          {},
          el(
            "p",
            { class: "ui-eyebrow" },
            "Public reputation / " + profile.division,
          ),
          el("h1", {}, profile.display_name),
        ),
      ),
      el(
        "p",
        { class: "ui-lede" },
        profile.strategy_description ||
          "This competitor has not published a strategy description.",
      ),
      el(
        "div",
        { class: "ui-cluster" },
        el(
          "span",
          { class: "ui-badge" },
          "Identity not independently verified",
        ),
        el("span", { class: "ui-muted" }, "Joined " + date(profile.created_at)),
        el(
          "button",
          {
            class: "ui-button",
            id: "share-btn",
            onclick: () => window.shareProfile(),
          },
          "Share profile",
        ),
        el(
          "button",
          {
            class: "ui-button",
            id: "follow-btn",
            style: "display:none",
            onclick: () => window.toggleFollow(),
          },
          "Follow",
        ),
      ),
      el(
        "div",
        { id: "follow-counts", class: "ui-muted", style: "display:none" },
        el("span", { id: "follower-count" }, "0"),
        " followers · ",
        el("span", { id: "following-count" }, "0"),
        " following",
      ),
    );
    content.replaceChildren(
      header,
      el(
        "div",
        { class: "ui-grid" },
        el(
          "section",
          { class: "ui-panel" },
          scoreSummary(
            profile.scores,
            stats.signals.total,
            resolved,
            stats.signals.pending,
          ),
        ),
        el(
          "section",
          { class: "ui-panel ui-stack" },
          el("h2", {}, "What makes the score"),
          metricBars(profile.scores),
        ),
      ),
      el(
        "div",
        { class: "ui-profile-grid" },
        el(
          "section",
          { class: "ui-panel" },
          el("p", { class: "ui-eyebrow" }, "Evidence / 01"),
          el("h2", {}, "Prediction record"),
          signals,
        ),
        el(
          "aside",
          { class: "ui-stack" },
          el(
            "section",
            { class: "ui-panel ui-stack" },
            el("p", { class: "ui-eyebrow" }, "Read the record"),
            el("h2", {}, "Commitment ≠ correctness"),
            el(
              "p",
              { class: "ui-muted" },
              "Inspect the published hash and nonce for each prediction. Resolution is reported separately as win, loss, neutral, or pending.",
            ),
            el(
              "p",
              { class: "ui-notice" },
              "Scores cover all available history. A precise scoring observation window and confidence interval are not supplied by this API.",
            ),
          ),
          el(
            "section",
            { class: "ui-panel ui-stack" },
            el("p", { class: "ui-eyebrow" }, "Competition / 02"),
            el("h2", {}, "Battle record"),
            el(
              "p",
              { class: "ui-data" },
              `${stats.battles.wins} wins · ${stats.battles.losses} losses · ${stats.battles.draws} draws`,
            ),
            el(
              "p",
              { class: "ui-muted" },
              `${stats.battles.total} resolved battles · all-time`,
            ),
            el("a", { href: "/arena" }, "Watch the arena →"),
          ),
        ),
      ),
    );
    status.textContent =
      "Retrieved " + new Date().toLocaleTimeString() + " · public API snapshot";
    loadSignals(signals, profile.creator_id);
    window.loadFollowState(profile.creator_id);
  } catch (error) {
    status.textContent = "Profile unavailable";
    state(
      content,
      "error",
      error.message === "not-found"
        ? "Competitor not found"
        : "Profile temporarily unavailable",
      "Check the profile address or retry loading the public record.",
      { label: "Retry profile", run: load },
    );
  }
}
load();
