export const entries = [
  ["atlas", "Atlas Research", "crypto", 0.782, 148],
  ["northstar", "Northstar Quant", "multi", 0.746, 96],
  ["signal-lab", "Signal Laboratory", "polymarket", 0.713, 72],
  ["meridian", "Meridian Markets", "crypto", 0.684, 54],
  ["quiet-capital", "Quiet Capital", "multi", 0.651, 38],
  ["delta", "Delta Observatory", "crypto", 0.628, 31],
].map(
  ([creator_id, display_name, division, composite_score, total_signals]) => ({
    creator_id,
    display_name,
    division,
    composite_score,
    total_signals,
    win_rate: 0.72,
    risk_adjusted_return: 0.81,
    consistency: 0.78,
    confidence_calibration: 0.79,
    xp: 420,
    level: 7,
    streak_days: 0,
  }),
);
export const signals = [
  {
    signal_id: "fixture-prediction-001",
    asset: "BTCUSDT",
    action: "BUY",
    confidence: 0.72,
    reasoning:
      "Price held the prior session range while volume strengthened. This prediction tests a continuation above the observed support level.",
    committed_at: "2026-09-05T12:30:00Z",
    timeframe: "1d",
    outcome: "WIN",
    target_price: 68000,
    stop_loss: 61500,
    commitment_hash: "a4c7d029".repeat(8),
    nonce: "public-fixture-nonce",
  },
  {
    signal_id: "fixture-prediction-002",
    asset: "ETHUSDT",
    action: "SELL",
    confidence: 0.64,
    reasoning:
      "Momentum has weakened relative to the wider market. Waiting for the committed observation window to close.",
    committed_at: "2026-09-06T09:00:00Z",
    timeframe: "4h",
    outcome: null,
    target_price: 2200,
    stop_loss: 2700,
    commitment_hash: "b9f2c140".repeat(8),
    nonce: "public-fixture-nonce-2",
  },
];
export async function fixtures(page) {
  await page.route("**/leaderboard?*", (route) =>
    route.fulfill({ json: { entries, total: entries.length } }),
  );
  await page.route("**/leaderboard", (route) =>
    route.fulfill({ json: { entries, total: entries.length } }),
  );
  await page.route("**/leaderboard/crypto?*", (route) =>
    route.fulfill({
      json: {
        entries: entries.filter((e) => e.division === "crypto"),
        total: 3,
      },
    }),
  );
  await page.route("**/api/v1/users/*/profile", (route) =>
    route.fulfill({
      json: {
        ...entries[0],
        created_at: "2026-05-12T09:00:00Z",
        strategy_description:
          "Systematic crypto research. Directional predictions with explicit targets, stops, and a public record of every outcome.",
        scores: { ...entries[0], composite: 0.782 },
      },
    }),
  );
  await page.route("**/api/v1/users/*/stats", (route) =>
    route.fulfill({
      json: {
        signals: { total: 148, wins: 96, losses: 36, neutrals: 4, pending: 12 },
        battles: { wins: 8, losses: 3, draws: 1, total: 12 },
        ranking: { leaderboard_rank: 1 },
      },
    }),
  );
  await page.route("**/creator/*/signals?*", (route) =>
    route.fulfill({ json: { total: 148, signals } }),
  );
  await page.route("**/creator/*/followers?*", (route) =>
    route.fulfill({ json: { total: 0, followers: [] } }),
  );
  await page.route("**/creator/*/following?*", (route) =>
    route.fulfill({ json: { total: 0, following: [] } }),
  );
}
