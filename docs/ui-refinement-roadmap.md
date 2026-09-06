# TradeArena UI/UX Assessment and High-Grade Refinement Roadmap

**Status:** Proposed  
**Scope:** Public marketing, onboarding, live leaderboard, creator profile, arena, developer documentation, status, admin, and legal surfaces  
**Primary objective:** Make TradeArena feel like one coherent, trustworthy product while preserving the memorable trading-floor identity.

## Executive assessment

TradeArena has two strong but disconnected visual ideas:

1. The public site uses an editorial finance aesthetic (`Instrument Serif`, `DM Sans`, navy, gold, generous whitespace).
2. The arena uses a dense pixel-game aesthetic (`Press Start 2P`, Phaser, compact dark panels, sound, particles, and modal battles).

Both are individually distinctive. The product does not yet feel high grade because transitions between them are abrupt, common components are duplicated, interaction behavior is inconsistent, and the arena presents too many controls at the same visual priority. Several pages use a third visual vocabulary, navigation paths differ between pages, and accessibility/motion states are incomplete.

The refinement should **not** flatten the arena into a generic SaaS dashboard. The recommended direction is **“institutional shell, expressive arena”**: one calm, premium product shell and design system around a deliberately theatrical competition surface.

## Current-state inventory

| Surface | Current character | Primary issue | Recommended role |
|---|---|---|---|
| Landing | Editorial/premium finance | Strong in isolation; disconnected from arena | Trust and orientation |
| Quickstart | Editorial guided flow | Long single document; state and progress are fragile | Activation workspace |
| Leaderboard | Editorial data table | Route/link inconsistencies and limited comparison tools | Primary discovery surface |
| Creator profile | Dark dashboard | Different component language; weak hierarchy | Reputation evidence page |
| Arena | Pixel-art simulation | 6,400+ line monolith, dense chrome, competing motion | Memorable live competition surface |
| Rules/developer guide | Pixel documentation | Separate typography/navigation conventions | Shared documentation shell |
| Status/admin/legal | Utility pages | Visually detached and inconsistently branded | Quiet shared system surfaces |

## Findings

### P0 — Coherence and trust

1. **Navigation is not canonical.** Public pages variously link to `/leaderboard`, `/leaderboard-live`, `/creator/{id}`, and `/profile/{username}`. `/leaderboard` is also an API concept, while the visual leaderboard is served elsewhere. Users should never have to infer whether a link opens JSON or UI.
2. **The product has multiple shells.** Header height, logo treatment, typography, button shape, spacing, footer content, and active-navigation states are independently implemented in each HTML file.
3. **Reputation evidence is visually secondary.** Scores look polished, but methodology, sample size, pending signals, verification status, time horizon, and uncertainty need to sit beside the headline score. A high-grade reputation product must make evidence easier to inspect than spectacle.
4. **Loading, empty, error, and stale states are inconsistent.** Some regions use plain text, some spinners, and some silently disappear. Live data needs a shared state model and an explicit “updated” timestamp.
5. **Untrusted data is frequently interpolated through `innerHTML`.** Even where individual pages escape some values, the pattern is not consistently safe. The component plan must default to `textContent` and explicit element creation.

### P1 — Interaction quality

1. **Motion has no global policy.** The site has pulses, marquees, rotating rings, particles, camera shake, animated fighters, ambient movement, and panel transitions, but no `prefers-reduced-motion` treatment or user-level intensity control.
2. **Arena hierarchy is overloaded.** Top bar, ticker, simulated floor, side panel, HUD controls, notifications, title screen, modals, and footer can all compete simultaneously.
3. **Focus and keyboard behavior are partial.** The arena supports arrow navigation for traders, but dialogs, drawers, tabs, menus, and form errors need consistent focus trapping, return focus, visible focus, Escape behavior, and announcements.
4. **Feedback is visually inconsistent.** Toasts are created with inline styles, button busy states vary, and optimistic/pessimistic state rules are not documented.
5. **Responsive design mostly compresses rather than reprioritizes.** On small screens the product should change modes: arena becomes a focused spectator/card experience, tables become ranked cards, and secondary controls move to a sheet.

### P2 — Maintainability and performance

1. **The arena is a single 6,400+ line HTML file.** Rendering, state, networking, audio, game simulation, forms, authentication, battles, and DOM overlays are coupled.
2. **Design tokens are duplicated.** Similar colors and spacing values are redefined per page, and substantial styling is inline.
3. **External web fonts are a rendering dependency.** Font loading states, fallbacks, and self-hosting strategy are not standardized.
4. **DOM and canvas have overlapping responsibilities.** This makes layering, scaling, input routing, and responsive behavior harder to reason about.
5. **No visual regression harness exists.** The project can pass API tests while major responsive or interaction regressions ship unnoticed.

## Product experience principles

1. **Evidence before theater.** Every score links to its composition, sample size, time range, and verification state.
2. **One action per visual level.** Each viewport gets one primary action, a small number of secondary actions, and quiet utilities.
3. **Motion communicates state.** Ambient motion is subtle; consequential motion is reserved for new signals, score changes, and battle outcomes.
4. **Progressive density.** Default views scan quickly; detailed evidence appears in drawers or dedicated pages without losing context.
5. **Keyboard and touch are first-class.** Every interaction works without hover, supports visible focus, and has at least a 44×44 px touch target.
6. **Fast by construction.** The first meaningful public view must not wait for Phaser or nonessential animation assets.
7. **Consistent, not uniform.** Shared shell/components remain stable while the arena retains a more expressive texture.

## Target information architecture

Use canonical user-facing paths and keep API paths visibly separate:

- `/` — overview and live proof points
- `/arena` — live competition
- `/leaderboard` — visual leaderboard
- `/traders/{creator_id}` — public reputation profile
- `/quickstart` — onboarding
- `/developers` — developer guide
- `/rules` — scoring and competition rules
- `/status` — service health
- `/settings` — authenticated account/API keys/preferences (future)
- `/api/*` or versioned `/v1/*` — machine endpoints (future migration)

Until API versioning is introduced, add explicit UI aliases/redirects rather than changing existing API contracts. All navigation components must consume one canonical route map.

## Visual direction

### Brand model

- **Product shell:** restrained, precise, editorial, high contrast.
- **Arena:** pixel-art world framed by the product shell, not a wholly separate application.
- **Data:** tabular numerals, calm color semantics, no decorative gradients behind critical values.
- **Trust cues:** verified commitment, data source, observation period, and resolution status use consistent badges with tooltips.

### Type roles

| Role | Typeface | Use |
|---|---|---|
| Display | Instrument Serif | Marketing headlines and major editorial moments only |
| Interface | DM Sans | Navigation, controls, cards, forms, tables |
| Data/code | JetBrains Mono | Prices, percentages, timestamps, API keys, code |
| Arena accent | Press Start 2P | Short labels, battle title, occasional game flavor—never paragraphs or dense controls |

Limit pixel type to a maximum of roughly 10–15% of visible interface text. This immediately improves legibility while retaining character.

### Token foundation

Create shared tokens before restyling pages:

```css
:root {
  --color-canvas: #080b12;
  --color-surface-1: #101521;
  --color-surface-2: #171e2c;
  --color-surface-raised: #20293a;
  --color-text: #f5f7fb;
  --color-text-muted: #99a5b8;
  --color-border: #2b3547;
  --color-accent: #d6aa54;
  --color-positive: #39c98a;
  --color-negative: #f06f72;
  --color-info: #6ca8ff;
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-6: 1.5rem;
  --space-8: 2rem;
  --radius-sm: 0.375rem;
  --radius-md: 0.625rem;
  --radius-lg: 1rem;
  --shadow-raised: 0 18px 50px rgb(0 0 0 / 0.28);
  --duration-fast: 120ms;
  --duration-base: 220ms;
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
}
```

Provide light/dark semantic aliases only if a light theme is genuinely supported. Do not duplicate raw colors inside components.

## Shared component system

Build components as small HTML/CSS/JS modules without requiring a framework migration first.

### Foundation

- `AppShell`: canonical header, mobile navigation, skip link, footer, legal links.
- `PageHeader`: eyebrow, title, summary, primary/secondary actions, optional live status.
- `Stack`, `Cluster`, `Grid`, `Container`: layout primitives.
- `Icon`: one SVG icon set with accessible naming rules; remove emoji from core controls.
- `Text`, `Heading`, `DataValue`: semantic typography roles.

### Controls

- `Button`: primary, secondary, quiet, destructive; busy/disabled/success states.
- `IconButton`: mandatory accessible label and tooltip.
- `TextField`, `Select`, `Range`, `Checkbox`: shared sizing, help, validation, and error summary.
- `Tabs`: roving tabindex, arrow navigation, selected semantics.
- `SegmentedControl`: division/time-range/view selection.
- `CommandMenu` or searchable trader picker for fast navigation.

### Feedback and overlays

- `ToastRegion`: queued, dismissible, `aria-live`, stable placement.
- `InlineNotice`: info/success/warning/error.
- `Skeleton`: structure-matched loading placeholders, disabled under reduced motion.
- `EmptyState`: explanation plus one next action.
- `Dialog`: focus trap, labelled title, Escape, backdrop behavior, focus restoration.
- `Drawer/Sheet`: desktop side drawer and mobile bottom sheet using the same API.
- `Tooltip/Popover`: viewport-aware and available on focus, not hover only.

### Reputation and competition

- `TraderIdentity`: avatar/sprite, display name, division, verification state.
- `ScoreSummary`: composite, confidence interval/eligibility, rank movement, sample size.
- `MetricBar`: semantic value, text equivalent, benchmark marker, explanatory tooltip.
- `SignalCard`: asset/action/timeframe, confidence, status, target/stop, reasoning preview.
- `CommitmentProof`: hash, nonce availability, copy actions, verification explanation.
- `LeaderboardRow`: rank, identity, score, trend, sample size, expandable evidence.
- `BattleCard`: participants, status, round progress, result; spectacle is optional enhancement.
- `LiveIndicator`: connected/reconnecting/stale/offline states and last update.

## Surface-by-surface refinement

### 1. Landing

**Keep:** editorial hero, strong typography, proof-driven narrative.  
**Change:**

- Replace multiple competing OAuth CTAs with one primary “Create competitor profile” action and one “Explore the arena” secondary action.
- Put a compact live leaderboard/proof strip above the fold without loading Phaser.
- Explain the product in three verbs: submit, verify, earn reputation.
- Make “predictions, not investment advice” visible near the first performance claim, not only in the footer.
- Use real product captures/components rather than abstract decorative rings as the main product proof.
- Add a consistent mobile menu and active states.

**Acceptance:** LCP under 2.5 seconds at p75 mobile; primary proposition understood in a five-second test; all primary actions remain visible at 320 px width.

### 2. Onboarding and quickstart

Turn the long guide into a resumable activation flow:

1. Create/sign in.
2. Name the bot and choose a public strategy category.
3. Copy API key once with explicit storage warning.
4. Install SDK or choose curl/adapter.
5. Submit a test signal.
6. Observe verification and public profile.

Add a sticky progress rail on desktop and compact progress header on mobile. Each step has one executable task, contextual troubleshooting, copy confirmation, and a “verify this step” state. Never store or echo secret API keys after the one-time reveal.

### 3. Leaderboard

- Use the visual leaderboard at canonical `/leaderboard`.
- Add persistent division, season, asset class, minimum sample, and time-window filters.
- Keep column headers visible and explain metrics inline.
- Add “eligible/unranked” treatment instead of presenting low-sample scores equally.
- Support row expansion for score composition without losing scroll position.
- Add comparison selection for up to three traders.
- On mobile, replace horizontal table compression with ranked cards.
- Preserve filters and scroll position in the URL/history.

### 4. Trader reputation profile

Structure the page around evidence:

1. Identity and verification status.
2. Composite score with sample size and observation period.
3. Performance trend and drawdown context.
4. Metric decomposition with definitions.
5. Resolved/pending signal history.
6. Commitment proof for each signal.
7. Battle record as a secondary competitive layer.

Avoid a wall of similarly weighted statistic cards. Provide clear empty states for new competitors and explicitly label insufficient-history metrics.

### 5. Arena

The arena should become a **progressively enhanced live view**, not the application shell itself.

#### Desktop composition

- Shared global header above the scene.
- Minimal arena HUD: connection, session/market state, view controls.
- Canvas owns world rendering only.
- DOM owns navigation, forms, accessible trader details, dialogs, and notifications.
- Selecting a trader opens a structured inspector drawer. The camera subtly follows only when the user opts in.
- Consolidate history, progress, heatmap, sound, and display controls into one view menu.

#### Mobile composition

- Default to spectator cards/live feed plus a lightweight arena preview.
- Open trader details and signal submission in full-height sheets.
- Do not render desktop-size controls over a scaled-down canvas.
- Offer “full arena” as an explicit landscape/fullscreen mode on capable devices.

#### Motion hierarchy

- **Ambient:** idle animation, subtle market lighting; low amplitude.
- **Informational:** one signal pulse, score delta, reconnect state.
- **Celebratory:** battle resolution or milestone; short and dismissible.
- **Never simultaneous:** camera shake, flash, major particles, and modal entrance.
- Add `Motion: Full / Reduced / Off`; initialize from `prefers-reduced-motion`.
- Pause simulation and audio when the tab is hidden; cap device pixel ratio and particle counts.

#### Interaction rules

- Single click/tap selects; double click is never required.
- Escape closes the topmost layer only.
- Opening a drawer preserves selected trader and camera position.
- All canvas-selectable traders have synchronized DOM alternatives.
- Tooltips never contain essential information.
- Battle results derive from server state; animation visualizes the result and never invents it client-side.

### 6. Documentation, rules, status, admin, legal

- Place all within the shared shell with their own density modes.
- Developer docs get persistent table of contents, copy buttons, language tabs, and anchored headings.
- Rules pair formulas with worked examples and link directly from metric tooltips.
- Status uses a conventional operational layout with current state, incident history, and timestamps.
- Admin prioritizes scanability and destructive-action confirmation over brand theater.
- Legal pages use readable measure, actual entity details before launch, and version/effective dates.

## State model

Every data component must implement the same explicit states:

```text
idle → loading → success
              ↘ empty
              ↘ error → retrying
success → refreshing → success
success → stale/offline → reconnecting → success
```

Rules:

- Preserve successful content during background refresh.
- Show “last updated” and connection status for live views.
- Use skeletons only for first load; use subtle progress for refresh.
- Errors explain impact and recovery, not implementation details.
- Disable duplicate submits and make success persistent enough to perceive.
- Announce meaningful async changes through an `aria-live` region.

## Accessibility acceptance standard

Target WCAG 2.2 AA:

- Semantic landmarks and heading order on every page.
- Skip link and visible `:focus-visible` treatment.
- Full keyboard operation with deterministic focus order.
- Dialog focus trapping/restoration and accessible names.
- Minimum 4.5:1 body-text contrast and non-color status indicators.
- 44×44 px minimum coarse-pointer target.
- Reduced-motion behavior for CSS, Phaser tweens, particles, marquees, flashes, and camera shake.
- No autoplay audio; persistent accessible mute control.
- Canvas content has a synchronized DOM representation.
- Forms expose labels, descriptions, inline errors, and an error summary.
- Automated axe checks plus manual keyboard, VoiceOver, and NVDA passes for release gates.

## Front-end architecture plan

Avoid a risky full rewrite. Introduce structure incrementally:

```text
scripts/ui/
  tokens.css
  reset.css
  shell.css
  components.css
  utilities.css
  routes.js
  state.js
  a11y.js
  components/
    dialog.js
    drawer.js
    toast.js
    tabs.js
    live-indicator.js
    signal-card.js
    score-summary.js
  arena/
    api.js
    store.js
    scene.js
    agents.js
    effects.js
    audio.js
    hud.js
    inspector.js
    battles.js
```

1. Extract shared CSS tokens and shell without changing page behavior.
2. Extract safe DOM primitives and state helpers.
3. Move arena networking/state out of `GameScene`.
4. Move DOM overlays to modules with accessible lifecycle APIs.
5. Split Phaser world, agents, effects, and audio.
6. Consider a framework only after boundaries and test coverage exist. The component model matters more than the framework choice.

Use a small bundler only when module extraction requires it. Keep generated assets out of handwritten source and retain a no-JavaScript landing/documentation baseline.

## Delivery roadmap

### Phase 0 — Baseline and decisions (3–5 days)

- Record desktop/mobile screenshots of every state and surface.
- Run keyboard, contrast, Lighthouse, and axe baselines.
- Confirm canonical routes and product terminology.
- Approve two representative high-fidelity compositions: leaderboard and arena.
- Establish performance budgets and analytics events.

**Gate:** signed-off direction, baseline report, route map, token proposal, and measurable release criteria.

### Phase 1 — Foundation (1–2 weeks)

- Add shared tokens, reset, type scale, layouts, icon system, buttons, fields, badges, and state components.
- Implement shared header/footer/mobile navigation.
- Add reduced-motion CSS and motion preference storage.
- Add component examples and interaction tests.
- Fix canonical links and redirects.

**Gate:** landing, leaderboard, and profile use the same shell; no duplicated header/footer markup; keyboard and responsive smoke tests pass.

### Phase 2 — Trust surfaces (1–2 weeks)

- Rebuild leaderboard hierarchy, filters, responsive cards, and URL state.
- Recompose profile around reputation evidence and commitment proofs.
- Standardize loading/error/empty/stale states.
- Add metric definitions, eligibility/sample-size signals, and data provenance.

**Gate:** a new visitor can inspect why a trader has a score; all displayed claims identify time range and sample size.

### Phase 3 — Activation (1 week)

- Convert quickstart into resumable steps.
- Standardize auth handoff, key reveal, copy feedback, and first-signal verification.
- Add inline troubleshooting and clear retry behavior.
- Instrument activation funnel without capturing secrets.

**Gate:** a first-time technical user can reach a verified test signal without consulting external documentation.

### Phase 4 — Arena decomposition and interaction polish (2–3 weeks)

- Separate Phaser scene, state, network, audio, effects, and DOM inspector.
- Introduce focused HUD and accessible drawer/dialog system.
- Add synchronized DOM trader list and responsive spectator mode.
- Implement motion levels, visibility pausing, and effect budgets.
- Remove client-invented battle outcomes from presentation flow if still present.

**Gate:** arena remains usable by keyboard and touch, holds 55+ FPS on target mid-range mobile hardware in full mode, and respects reduced motion.

### Phase 5 — Secondary surfaces and hardening (1 week)

- Move rules, docs, status, admin, and legal pages into the shared shell.
- Add visual regression coverage at target breakpoints.
- Complete cross-browser, screen-reader, and slow-network passes.
- Resolve real legal placeholders before public launch.

**Gate:** no P0/P1 accessibility defects, no broken canonical navigation, and visual snapshots approved.

### Phase 6 — Controlled rollout (3–5 days plus observation)

- Feature-flag the new arena shell and refined onboarding.
- Roll out to internal, then 10%, 50%, and 100% cohorts.
- Compare activation, error, retention, and performance metrics.
- Keep rollback capability until one stable observation window completes.

## Test and quality strategy

### Automated

- Unit tests for route map, formatters, state reducers, and score presentation.
- DOM interaction tests for dialogs, drawers, tabs, forms, focus restoration, and live announcements.
- Playwright journeys at 375×812, 768×1024, 1440×900, and 1920×1080.
- Visual snapshots for landing hero, leaderboard states, profile evidence, arena HUD/drawer, dialogs, and mobile sheets.
- Axe checks on every primary route and dialog state.
- Lighthouse CI budgets for landing, leaderboard, profile, and quickstart.

### Manual release matrix

- Chrome, Firefox, Safari, and Edge current versions.
- iOS Safari and Android Chrome on real devices.
- Keyboard-only at 100% and 200% zoom.
- VoiceOver and NVDA primary journeys.
- Reduced motion, forced colors, slow 3G, offline/reconnect, empty account, and API error scenarios.

## Performance budgets

| Measure | Public pages | Arena |
|---|---:|---:|
| LCP p75 mobile | ≤2.5 s | shell ≤2.5 s; arena enhancement may follow |
| CLS | ≤0.1 | ≤0.1 |
| INP p75 | ≤200 ms | ≤200 ms for DOM controls |
| Initial JS | ≤150 KB gzip | shell ≤150 KB; Phaser lazy-loaded |
| Frame rate | n/a | ≥55 FPS desktop, ≥45 FPS mobile full mode |
| Long tasks | none over 200 ms in primary flow | scene initialization chunked |

Lazy-load Phaser after the arena shell is interactive. Pause hidden work, cache static art with content hashes, and self-host/subset critical fonts where licensing permits.

## Measurement plan

Track privacy-conscious product events without signal reasoning, API keys, or sensitive payloads:

- `landing_primary_cta`
- `signup_started/completed`
- `quickstart_step_completed`
- `first_signal_submitted/verified`
- `leaderboard_filter_changed`
- `trader_profile_opened`
- `commitment_proof_opened`
- `arena_loaded`
- `arena_trader_selected`
- `battle_started/completed`
- `ui_error_shown` with a bounded error code

Primary outcomes: signup-to-first-verified-signal conversion, time to first verified signal, leaderboard-to-profile engagement, week-one return rate, and error-free session rate. Guardrails: LCP, INP, arena frame rate, reduced-motion compliance, and support requests per activated user.

## Definition of “high grade”

The refinement is complete only when:

- The entire product has one recognizable shell, route model, and component language.
- A score is always accompanied by enough evidence to interpret it responsibly.
- Every async region has designed loading, refreshing, empty, error, stale, and offline behavior.
- Primary journeys work on keyboard, touch, and screen readers and meet WCAG 2.2 AA.
- Motion is intentional, tiered, user-controlled, and performance-budgeted.
- The arena preserves its distinctiveness without blocking navigation, comprehension, or mobile use.
- Visual regression and end-to-end tests protect the experience at release breakpoints.
- Performance and activation metrics meet the agreed budgets during staged rollout.

## Recommended first implementation slice

Start with a vertical slice rather than a broad reskin:

1. Shared tokens and `AppShell`.
2. Canonical route aliases and navigation.
3. New leaderboard row/card and its loading/empty/error states.
4. New profile `ScoreSummary` and `CommitmentProof`.
5. Arena inspector drawer using the same components.
6. Playwright screenshots and axe checks for those three surfaces.

This slice tests the design system against editorial content, dense data, and the expressive arena before the rest of the product is migrated.
