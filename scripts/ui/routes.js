// /leaderboard remains a JSON contract until API versioning is introduced.
export const routes = Object.freeze({
  leaderboard: "/leaderboard-live",
  trader: (id) => "/traders/" + encodeURIComponent(id),
  profile: (id) => "/api/v1/users/" + encodeURIComponent(id) + "/profile",
  stats: (id) => "/api/v1/users/" + encodeURIComponent(id) + "/stats",
  signals: (id) => "/creator/" + encodeURIComponent(id) + "/signals?limit=10",
});
