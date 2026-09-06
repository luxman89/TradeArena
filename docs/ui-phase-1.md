# Phase 1: shared shell and evidence slice

The landing page, leaderboard, creator profile and arena now share a server-rendered header/footer from `scripts/ui/shell.html`. FastAPI composes the shell without a build step; browser modules progressively add navigation and data interactions. Phaser still renders the trading floor.

## Routes and API compatibility

- `/leaderboard-live` is the visual leaderboard. `/leaderboard` and `/leaderboard/{division}` remain JSON APIs, including existing pagination and season behavior. This follows the roadmap's compatibility exception until an API-version migration is agreed.
- `/traders/{id}` is the public profile alias. `/profile/{username}` remains supported, including social metadata.
- `/developers` aliases the existing developer guide.
- Shared navigation uses these UI paths. Dynamic profile links consume `scripts/ui/routes.js`.

## Components and evidence

`tokens.css` defines semantic colors, spacing, typography, motion and radii. `shell.css` contains reset, shell, layouts and reusable controls. `components.js` provides safe DOM creation, explicit request states, normalized score presentation, metric definitions, signal cards and commitment disclosure. `icons.js` contains a fixed decorative SVG vocabulary; icon-only controls must carry an accessible label.

Open `/ui/examples.html` for component examples. Use `textContent` or the `el()` helper for public data, never HTML interpolation. Hash/nonce availability must not be described as completed cryptographic verification or prediction accuracy. Scores are displayed consistently on a 0–100 scale. All-time ranking requires 20 resolved predictions; weekly ranking uses its own sample and remains explicitly provisional. No confidence interval or precise observation window is invented.

The arena inspector is a native modal dialog: single selection, focus containment, Escape and focus restoration. Its DOM competitor list mirrors the leaderboard response, so evidence is accessible without canvas hit targets. Mobile uses a compact scene preview above spectator cards and a full-height inspector. Existing authentication, submission, battle history and career flows remain incremental follow-up surfaces.

Motion defaults to the OS preference and can be set to Full, Reduced or Off in View controls. The preference is shared across pages. Reduced/Off disable CSS animation and freeze ambient Phaser simulation, tweens and sprite animation; the public record still refreshes. Audio starts muted and hidden tabs do not produce new sounds. Broader arena subsystem extraction remains Phase 4 work.

## Verification

```sh
uv sync
npm ci
npx playwright install chromium
uv run ruff check src/ sdk/ tests/
uv run ruff format --check src/ sdk/ tests/
uv run pytest tests/ -q
npm run lint:ui
npm run format:check
npm run test:ui
```

Playwright starts a local FastAPI server when port 8765 is free. Its viewport matrix is 375×812, 768×1024, 1440×900 and 1920×1080. Tests exercise navigation, filter history, loading/empty/error/stale states, public-data escaping, inspector keyboard behavior and persisted motion. Axe checks cover the three primary data surfaces and inspector. Screenshot fixtures are fictional and do not represent production performance. Separate visitor headers isolate repeated cold-cache journeys from one shared rate-limit bucket without changing production rate limits.

Screenshots and traces are generated into ignored `.ui-artifacts/`, `test-results/` and `playwright-report/` directories. CI uploads them as review artifacts; they are not committed. The release still needs real-device Safari/Firefox testing, NVDA/VoiceOver passes and field performance measurements. Automated axe checks alone do not establish WCAG conformance.
