# TradeArena Discord Server Structure

## Server Name
TradeArena — Competitive Trading Bot Arena

## Server Icon
Use the TradeArena logo (trading floor icon from `scripts/assets/`).

## Categories & Channels

### WELCOME
| Channel | Type | Purpose |
|---------|------|---------|
| #rules | Text (read-only) | Server rules and code of conduct |
| #announcements | Text (read-only) | Platform updates, new features, maintenance windows |
| #introductions | Text | New members introduce themselves and their bots |

### COMMUNITY
| Channel | Type | Purpose |
|---------|------|---------|
| #general | Text | General discussion about trading, bots, and the platform |
| #show-your-bot | Text | Share your bot's performance, strategy overview, and leaderboard screenshots |
| #strategies | Text | Discuss trading strategies, signals, and market analysis |
| #off-topic | Text | Non-trading discussion |

### SUPPORT
| Channel | Type | Purpose |
|---------|------|---------|
| #bot-help | Text | Help with SDK integration, API questions, CLI troubleshooting |
| #bug-reports | Text | Report bugs (template pinned: steps to reproduce, expected vs actual, logs) |
| #feature-requests | Text | Suggest new features and improvements |

### DEVELOPMENT
| Channel | Type | Purpose |
|---------|------|---------|
| #contributing | Text | Discussion for open-source contributors |
| #changelog | Text (read-only) | Automated feed from GitHub releases |

## Roles

| Role | Color | Permissions | Criteria |
|------|-------|-------------|----------|
| Admin | Red | Full server management | Core team |
| Moderator | Orange | Manage messages, mute/kick | Trusted community members |
| Contributor | Green | Access to #contributing | Merged PR to repo |
| Elite Trader | Gold | Display role | Bot in elite division on leaderboard |
| Pro Trader | Silver | Display role | Bot in pro division on leaderboard |
| Rookie | Default | Standard access | All verified members |

## Bot Integrations

1. **GitHub webhook** — Post to #changelog on new releases
2. **Leaderboard bot** (future) — Daily top-5 leaderboard snapshot to #announcements
3. **Moderation bot** (MEE6 or similar) — Auto-mod, welcome messages, role assignment

## Verification

- Require email verification before posting
- New members get Rookie role automatically
- 10-minute slow mode on #general for first 24 hours after joining
