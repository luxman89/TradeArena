import { routes } from "./routes.js";
export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value != null) node.setAttribute(key, value);
  }
  node.append(...children.filter((child) => child != null));
  return node;
}
export const pct = (value) =>
  Number.isFinite(value) ? (value * 100).toFixed(1) + "%" : "Unavailable";
export const score = (value) =>
  Number.isFinite(value) ? (value * 100).toFixed(1) : "—";
export const date = (value) =>
  value && !Number.isNaN(Date.parse(value))
    ? new Date(value).toLocaleString([], {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "Not available";
export function state(target, kind, title, message, action) {
  target.replaceChildren(
    el(
      "div",
      { class: "ui-state", "data-state": kind },
      el("h2", {}, title),
      el("p", {}, message),
      kind === "loading"
        ? el("div", { class: "ui-skeleton", "aria-hidden": "true" })
        : null,
      action
        ? el(
            "button",
            { class: "ui-button", onclick: action.run },
            action.label,
          )
        : null,
    ),
  );
}
export async function json(url, signal) {
  const response = await fetch(url, {
    signal: signal || AbortSignal.timeout(15000),
  });
  if (!response.ok)
    throw new Error(response.status === 404 ? "not-found" : "unavailable");
  return response.json();
}
export const metrics = [
  [
    "win_rate",
    "Win rate",
    "30%",
    "Share of all resolved predictions won; neutral outcomes remain in the sample.",
  ],
  [
    "risk_adjusted_return",
    "Risk-adjusted return",
    "30%",
    "Normalized confidence-weighted outcomes relative to their variability.",
  ],
  [
    "consistency",
    "Consistency",
    "25%",
    "Stability of prediction outcomes over time.",
  ],
  [
    "confidence_calibration",
    "Calibration",
    "15%",
    "How well stated confidence matches outcomes.",
  ],
];
export function metricBars(values) {
  return el(
    "div",
    { class: "ui-metrics" },
    ...metrics.map(([key, label, weight, definition]) =>
      el(
        "div",
        { class: "ui-metric" },
        el(
          "div",
          { class: "ui-cluster ui-between" },
          el("span", {}, label + " · " + weight),
          el("span", { class: "ui-data" }, pct(values[key])),
        ),
        Number.isFinite(values[key])
          ? el("meter", {
              min: "0",
              max: "1",
              value: Math.max(0, Math.min(1, values[key])),
              "aria-label": label,
            })
          : null,
        el("p", {}, definition),
      ),
    ),
  );
}
export function scoreSummary(values, total, resolved = null, pending = null) {
  const known = resolved !== null;
  return el(
    "div",
    { class: "ui-stack" },
    el("p", { class: "ui-eyebrow" }, "Composite reputation"),
    el(
      "div",
      { class: "ui-score" },
      score(values.composite ?? values.composite_score),
      el("small", {}, " / 100"),
    ),
    el(
      "div",
      { class: "ui-cluster" },
      el(
        "span",
        { class: "ui-badge" },
        known
          ? resolved >= 20
            ? "Ranking sample met"
            : "Unranked · building history"
          : "Ranked · 20+ resolved",
      ),
      el("span", { class: "ui-data ui-muted" }, `${total ?? "—"} submitted`),
    ),
    el(
      "p",
      { class: "ui-muted" },
      known
        ? `${resolved} resolved · ${pending} pending. All-time record.`
        : "All-time score. At least 20 resolved predictions required for ranking.",
    ),
    el(
      "p",
      { class: "ui-notice" },
      "A historical score, not a forecast. Small samples carry more uncertainty; no confidence interval is provided.",
    ),
    el("a", { href: "/rules" }, "How scoring works →"),
  );
}
export function signalCard(signal) {
  const commentsBody = el("div", { class: "ui-stack", "aria-live": "polite" });
  const discussion = el(
    "details",
    {},
    el("summary", {}, "Discussion"),
    commentsBody,
  );
  let commentsLoaded = false;
  async function loadComments() {
    commentsLoaded = true;
    commentsBody.textContent = "Loading discussion…";
    try {
      const data = await json(
        "/signal/" + encodeURIComponent(signal.signal_id) + "/comments?limit=5",
      );
      commentsBody.replaceChildren(
        ...(data.comments.length
          ? data.comments.map((comment) =>
              el(
                "div",
                {},
                el("strong", {}, comment.display_name),
                el("p", {}, comment.body),
                el("p", { class: "ui-meta" }, date(comment.created_at)),
              ),
            )
          : [el("p", { class: "ui-meta" }, "No comments yet.")]),
      );
    } catch {
      state(
        commentsBody,
        "error",
        "Discussion unavailable",
        "The prediction evidence is still visible.",
        { label: "Retry discussion", run: loadComments },
      );
    }
  }
  discussion.addEventListener("toggle", () => {
    if (discussion.open && !commentsLoaded) loadComments();
  });
  const proof = el(
    "details",
    {},
    el("summary", {}, "Inspect commitment proof"),
    el(
      "p",
      { class: "ui-meta" },
      "A published hash records the commitment; it does not verify accuracy. Hash and nonce availability are not a completed cryptographic verification.",
    ),
    el(
      "dl",
      { class: "ui-proof" },
      el("dt", {}, "SHA-256 commitment"),
      el("dd", {}, signal.commitment_hash || "Unavailable"),
      el("dt", {}, "Public nonce"),
      el("dd", {}, signal.nonce || "Not published"),
      el("dt", {}, "Signal ID"),
      el("dd", {}, signal.signal_id || "Unavailable"),
    ),
  );
  if (signal.commitment_hash) {
    const copy = el(
      "button",
      {
        class: "ui-button",
        onclick: async () => {
          try {
            await navigator.clipboard.writeText(signal.commitment_hash);
            copy.textContent = "Hash copied";
          } catch {
            copy.textContent = "Copy unavailable — select the hash above";
          }
        },
      },
      "Copy hash",
    );
    proof.append(copy);
  }
  return el(
    "article",
    { class: "ui-signal" },
    el(
      "div",
      { class: "ui-cluster ui-between" },
      el("h3", {}, `${signal.asset} · ${signal.action}`),
      el("span", { class: "ui-badge" }, signal.outcome || "PENDING"),
    ),
    el(
      "p",
      { class: "ui-meta" },
      `${date(signal.committed_at)} · ${signal.timeframe || "Timeframe unavailable"} · ${pct(signal.confidence)} confidence`,
    ),
    el("p", {}, signal.reasoning || "No reasoning published."),
    el(
      "p",
      { class: "ui-meta ui-data" },
      `Target ${signal.target_price ?? "—"} · Stop ${signal.stop_loss ?? "—"}`,
    ),
    proof,
    discussion,
  );
}
export async function loadSignals(target, id, isCurrent = () => true) {
  state(
    target,
    "loading",
    "Loading predictions",
    "Fetching the public commitment record.",
  );
  try {
    const data = await json(routes.signals(id));
    if (!isCurrent()) return;
    if (!data.signals.length)
      state(
        target,
        "empty",
        "No predictions yet",
        "Committed predictions will appear here after submission.",
      );
    else
      target.replaceChildren(
        el(
          "p",
          { class: "ui-meta ui-muted" },
          `Latest ${data.signals.length} of ${data.total} predictions · newest first`,
        ),
        ...data.signals.map(signalCard),
      );
  } catch {
    if (isCurrent())
      state(
        target,
        "error",
        "Predictions unavailable",
        "The score is still visible. Retry to load its evidence.",
        {
          label: "Retry predictions",
          run: () => loadSignals(target, id, isCurrent),
        },
      );
  }
}
