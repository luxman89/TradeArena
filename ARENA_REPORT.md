# TradeArena — Arena Page Implementation Report

## Overview

`scripts/arena.html` is a single-file web application (~90KB) that renders an interactive NYSE trading floor simulator using **Phaser 3.60.0**. It connects to the TradeArena FastAPI backend, pulls live leaderboard/signal data, and presents it as an animated pixel-art trading floor with walking traders, real-time score updates, and a battle system.

The rendering layer was fully migrated from raw HTML5 Canvas to Phaser 3. All environment art is procedurally drawn with Phaser Graphics (no tilesets used in final output).

---

## Architecture

### Single-file structure

| Section | Lines | Purpose |
|---|---|---|
| HTML/CSS | 1–255 | Layout, styling, DOM overlays (panel, modals, battle, tooltip, ticker) |
| JavaScript | 256–2200+ | Config, Phaser GameScene, game logic, UI controllers, persistence |

### Key constants

| Constant | Value | Meaning |
|---|---|---|
| `TS` | 32 | Tile size (pixels) |
| `SCALE` | 2 | Render scale multiplier |
| `ROOM_W` × `ROOM_H` | 26 × 18 | Room dimensions in tiles |
| `CFW` × `CFH` | 64 × 64 | Character frame size |
| `CHR_S` | 2.4 | Character sprite scale |
| `SPD` | 1.8 | Agent walk speed (tiles/sec) |
| `FRAMES_PER_ROW` | 13 | Frames per row in spritesheet |
| `DIR_TO_ROW` | [3,1,2,0] | Agent direction → sheet row mapping |

### Game world size

- **Pixel dimensions**: 1664 × 1152 (26×32×2 × 18×32×2)
- **Phaser scaling**: `Scale.FIT` + `CENTER_BOTH` — auto-scales to browser window

---

## Rendering Layer — Phaser 3

### GameScene lifecycle

```
preload()  → Loads char3 spritesheet + tileset images
create()   → Builds environment, overlays, screens, input handlers
update()   → Per-frame: agent movement, sprite sync, overlays, effects
```

### Environment (`_buildTradingFloor`)

All drawn with `Phaser.GameObjects.Graphics` — no external tileset images used for the floor.

**Floor**: Dark charcoal base rectangle (`0x1a1a24`) at depth -1000.

**7 Trading Desks** (`_buildDesk`):
- 4 in top-left cluster, 3 in top-right cluster
- Each desk consists of 5 Graphics objects:
  - **Desk surface**: Brown wood (`0x6b5540`) with edge highlights, 4 legs
  - **Dual monitors**: Left = green line chart with grid + red support line. Right = data table with alternating row colors, ticker symbols, price columns
  - **Keyboard + mouse**: Dark rectangle with key grid, rounded mouse
  - **Executive chair**: Multi-layered gray/purple with armrests, headrest, pedestal

**3 NYSE Trading Posts** (`_buildTradingPost`):
- Triangle layout: center-top (50%, 41%), bottom-left (25%, 82%), bottom-right (75%, 82%)
- 2-layer cylindrical structure with isometric squash (0.55):
  - **Lower cylinder**: Open desk/counter ring with wood surface, dark center hole, vertical panel lines, floor shadow
  - **Upper cylinder**: Screen tower with 6 mini screens (alternating ticker data / line charts), blue accent glow band, half-moon top cap
  - **Support posts**: 4 vertical pillars connecting layers with brackets

### Character Sprites (`_createSprites`)

Created lazily once `agents[]` is populated by `loadData()`. Each agent gets:

| Object | Type | Purpose |
|---|---|---|
| `phaserSprite` | Sprite | Character sprite from `char3` sheet, scale 2.4 |
| `phaserShadow` | Ellipse | Dark ellipse at feet |
| `phaserSelRing` | Ellipse | White filled selection ring (visible when selected) |
| `phaserFocusRing` | Ellipse | Cyan stroked focus ring (visible when keyboard-focused) |
| `phaserLabel` | Text | Name in Press Start 2P font, division-colored |
| `phaserLabelBg` | Graphics | Dark background behind nametag |
| `phaserScoreBar` | Graphics | Score progress bar under name |
| `phaserPopup` | Text | "!" popup during signal state |

**Animation**: Direct `setFrame()` each tick using formula:
```
frame = (bRow * 4 + DIR_TO_ROW[dir]) * 13 + (bCol * 3 + walkFrame)
```
No Phaser animation manager — frame index computed from agent state machine.

**Idle bob**: `Math.sin(ag.bobA * 1.4) * CHR_S` applied to sprite Y position.

### Wall-Mounted Leaderboard Screens

3 large screens rendered at the top of the room:

| Screen | Size | Max Rows | Content |
|---|---|---|---|
| TRADEARENA LEADERBOARD | 8T × 2.8T (512×179px) | 8 | All creators ranked by composite score |
| TOP SCORES | 5.5T × 2.8T (352×179px) | 6 | Same data, smaller format |
| WIN RATES | 5.5T × 2.8T (352×179px) | 6 | Sorted by win rate, shows percentage |

Each screen: dual hanging poles, thick bezel, dark body, blue glow accents, scanlines, title with shadow, divider line, dynamically updated row texts.

Updated via `gameScene.updateScreens(leaderboard)` on every 30s data refresh.

### Overlays

| Layer | Depth | Description |
|---|---|---|
| Day/night | 999 | Full-screen rectangle, color/alpha from `getDayNightOverlay()` based on system clock (sunrise 6–8, day 8–17, sunset 17–20, night 20–6) |
| Vignette | 998 | 8-step concentric edge darkening (max 18% alpha) |
| Scanlines | 997 | Horizontal lines every 4px at 1.5% alpha |

---

## Interaction System

### Click (Phaser input)

Background `pointerdown` handler in `GameScene.create()`:
1. Plays click sound + spawns ripple effect (circle tween: scale 8×, alpha 0, 220ms)
2. Checks if a sprite was hit → if not:
   - Checks 3 leaderboard screen zones → opens modal
   - Checks 7 desk proximity zones → opens nearest trader's panel
   - Otherwise → closes panel

Sprite `pointerdown`:
- Sets `selected = ag`, calls `openPanel(ag)`, plays panelOpen sound

### Hover (Phaser sprite events)

- `pointerover`: Sets tooltip agent, starts 300ms delay, then shows DOM `#canvas-tooltip` with name, rank, win rate, signal count
- `pointermove`: Updates tooltip position to follow cursor
- `pointerout`: Clears tooltip

### Keyboard navigation

Arrow keys cycle `focusedIdx` through agents with cyan focus ring. Enter opens panel. Escape closes panel.

---

## Signal Effects (Phaser-native)

| Effect | Implementation | Trigger |
|---|---|---|
| **Floating text** | Phaser Text + tween (float up 40×S, fade out, 800ms, destroy) | Score change on data refresh |
| **Particles** | 5 Phaser Rectangles per burst + position/alpha tween (600ms, destroy) | Signal emission, battle win |
| **Screen shake** | `cameras.main.shake(duration, intensity/1000)` | High-confidence signal (>0.9), large score change (>5), battle win |
| **Signal glow** | `sprite.setTint(0x10B981)` / `clearTint()` | Agent in signal state |
| **Popup "!"** | Phaser Text, visibility + alpha + y-offset from `popupT` timer | Signal start (800ms) |
| **Click ripple** | Circle + scale/alpha tween (220ms, destroy) | Any click on game area |
| **Paper particle** | Rectangle tween from top to bottom (8s, destroy) | Random ambient (60–90s interval) |

---

## Agent State Machine

```
to_desk → (arrives) → idle → (wanderT expires) → wander → (path done) → to_desk
                         ↓
                    (signal trigger)
                         ↓
                      signal → (signalT expires) → to_desk
```

- **to_desk**: BFS pathfind to assigned desk, walk at 1.8 tiles/sec
- **idle**: Idle bob animation, 3–15s wander timer
- **wander**: Walk to random walkable tile, then return to desk
- **signal**: 2.5s signal animation with glow, popup, particles

### Walkability grid

- Walls blocked (top 2 rows, left/right columns, bottom row, +1 tile inset)
- Desk footprint blocked (5×3 tiles per desk)
- Trading post circles blocked (radius 4 tiles each)
- Chair tile unblocked (agent sits there)

---

## UI Panels & Modals

### Right panel (272px slide-in)

- **Header**: Sprite preview (48×72 canvas), name, division badge, composite score, rank badge, CHALLENGE button
- **Battle stats**: 5 dimension bars with animated fill (Win Rate, Risk/Return, Consistency, Confidence, Reasoning)
- **Signal timeline**: Colored dots (green=WIN, red=LOSS, gold=NEUTRAL, gray=PENDING)
- **Recent signals**: Scrollable list with asset, action badge, confidence %, reasoning text

### Leaderboard modal

Clickable rows showing rank, name, score. Clicking a row opens that trader's panel.

### Battle overlay

Pokémon-style 3-round head-to-head:
- Fighter sprites rendered on separate canvases (64×96)
- HP bars with color change at <40%
- 3 rounds comparing win_rate, risk_adjusted_return, consistency with random variance
- Hit animations, damage log, winner announcement
- Results persisted to localStorage

### Battle history modal

Shows last 10 battles (winner, loser, date) from localStorage.

---

## Data Flow

```
loadData() → GET /leaderboard → update agents, topbar stats, ticker, wall screens
                               → trigger random signal animation
                               → detect score changes → floating text + particles
                               → persist scores to localStorage

openPanel() → GET /creator/{id}/signals → populate signal timeline + list
```

- **Refresh interval**: 30 seconds
- **Agent spawn**: First 4 leaderboard entries become agents (max = DESKS.length)

---

## Audio System

Web Audio API synthesized sounds (no audio files):

| Sound | Type | Trigger |
|---|---|---|
| click | Square 800Hz, 60ms | Any click |
| panelOpen | Sine 440→880Hz, 180ms | Open panel |
| panelClose | Sine 880→440Hz, 150ms | Close panel |
| signal | Square 660Hz, 100ms | Signal start |
| particle | Sine 1200→2400Hz, 80ms | Particle burst |
| scoreUp | Sine 523+659Hz chord, 300ms | Score increase |
| scoreDown | Sine 659+523Hz chord, 300ms | Score decrease |
| keyNav | Sine 600Hz, 40ms | Arrow key |
| battle | Square 220→880Hz, 250ms | Battle start |
| battleHit | Sawtooth 150Hz, 80ms | Battle round hit |
| battleWin | Square 523+659+784Hz arpeggio | Battle victory |

**Ambient**: Brown noise (lowpass 200Hz, gain 0.015) + periodic soft ticks (1000–1500Hz, random interval).

**Mute**: Toggle persisted to localStorage, restored on reload.

---

## Persistence

| Key | Storage | Data |
|---|---|---|
| `tradearena_muted` | localStorage | Boolean mute state |
| `tradearena_scores` | localStorage | Last known scores per creator |
| `tradearena_battle_history` | localStorage | Last 10 battle results |
| `tradearena_session_start` | localStorage | Session start timestamp |
| `tradearena_titleShown` | sessionStorage | Title screen dismissed flag |

---

## Title Screen

Full-screen overlay (z-index 500):
- "TRADE ARENA" in gold Press Start 2P with text-shadow
- Animated bull (green) vs bear (red) pixel art on canvas
- "VS" text with gold glow
- Bottom ticker with fake stock prices (AAPL, TSLA, BTC, ETH, etc.)
- Click or Enter/Space to dismiss → fades out, starts ambient audio
- Skipped if already shown this session (sessionStorage)

---

## Scaling & Resize

- **Phaser config**: `Scale.FIT` + `CENTER_BOTH`
- **Panel toggle**: `resize()` adjusts `#phaser-container` width by ±272px, calls `phaserGame.scale.refresh()`
- **Window resize**: Same handler via `window.addEventListener('resize', resize)`
- **Topbar**: 44px fixed height. **Ticker**: 32px fixed height. Game area = remaining space.

---

## Asset Loading

Two parallel loading systems:

1. **img{} loader**: Raw `Image()` objects for tileset/floor/wall/character sheets (legacy, used by battle/panel canvases)
2. **Phaser preload**: `this.load.spritesheet('char3', ...)` + tileset images

**Texture bridge**: `img['char3'] = this.textures.get('char3').getSourceImage()` — allows battle overlay and panel sprite canvas to use the Phaser-loaded texture.

**Boot sequence**: `tryBoot()` fires when all img{} assets loaded (or 5s timeout) → `createPhaserGame()` → Phaser creates scene → `GameScene.create()` initializes everything.

---

## Dead Code Status

All old canvas rendering code has been removed:
- `drawChar()`, `drawOverheadScreens()`, `drawPhoneRing()`, `drawRipples()`, `drawFloatingTexts()`, `drawParticles()`, old `render()` loop, old click/hover handlers, `buildFloor()` (no-op), `buildFurniture()` (no-op)

**Kept**: Offscreen `canvas`/`ctx` for `drawPanelSprite()` and battle overlay sprite rendering (these draw to separate DOM canvases, not the game canvas).
