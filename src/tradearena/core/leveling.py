"""XP and leveling system — 20 levels with avatar unlocks and perks.

XP is cumulative and never decreases. It is awarded on signal submission
(base XP) and on outcome resolution (bonus XP).
"""

from __future__ import annotations

# XP required to reach each level (index = level number, 1-indexed).
# Formula: xp_for_level(n) = 10 * (n-1) * n
XP_FOR_LEVEL: list[int] = [
    0,  # level 1 (starting)
    20,  # level 2
    60,  # level 3
    120,  # level 4
    200,  # level 5
    300,  # level 6
    420,  # level 7
    560,  # level 8
    720,  # level 9
    900,  # level 10
    1100,  # level 11
    1320,  # level 12
    1560,  # level 13
    1820,  # level 14
    2100,  # level 15
    2400,  # level 16
    2720,  # level 17
    3060,  # level 18
    3420,  # level 19
    3800,  # level 20
]

MAX_LEVEL = len(XP_FOR_LEVEL)  # 20

# XP awards
XP_SIGNAL_SUBMITTED = 10
XP_OUTCOME_WIN = 25
XP_OUTCOME_LOSS = 5
XP_OUTCOME_NEUTRAL = 10

# Avatar index → minimum level required to unlock
AVATAR_UNLOCK_LEVELS: dict[int, int] = {
    0: 1,  # free at start
    1: 1,  # free at start
    2: 1,  # free at start
    3: 1,  # free at start
    4: 3,
    5: 5,
    6: 8,
    7: 11,
    8: 14,
    9: 17,
}

# Level → title earned at that level
LEVEL_TITLES: dict[int, str] = {
    5: "Signal Cadet",
    10: "Market Analyst",
    15: "Floor Veteran",
    20: "Trading Legend",
}

# Level → nametag glow colour (cumulative: level 17 has gold, not blue)
LEVEL_GLOW: dict[int, str] = {
    8: "green",
    14: "blue",
    17: "gold",
}


def level_from_xp(xp: int) -> int:
    """Return the level for a given XP total (1-20)."""
    for lvl in range(MAX_LEVEL, 0, -1):
        if xp >= XP_FOR_LEVEL[lvl - 1]:
            return lvl
    return 1


def xp_to_next_level(xp: int) -> int:
    """Return XP remaining until the next level. 0 if at max level."""
    lvl = level_from_xp(xp)
    if lvl >= MAX_LEVEL:
        return 0
    return XP_FOR_LEVEL[lvl] - xp


def xp_for_current_level(xp: int) -> tuple[int, int]:
    """Return (xp_into_current_level, xp_needed_for_next_level).

    Useful for rendering progress bars.
    """
    lvl = level_from_xp(xp)
    if lvl >= MAX_LEVEL:
        return (0, 0)
    current_threshold = XP_FOR_LEVEL[lvl - 1]
    next_threshold = XP_FOR_LEVEL[lvl]
    return (xp - current_threshold, next_threshold - current_threshold)


def unlocked_avatars(level: int) -> list[int]:
    """Return sorted list of avatar indices unlocked at the given level."""
    return sorted(idx for idx, req in AVATAR_UNLOCK_LEVELS.items() if level >= req)


def title_for_level(level: int) -> str | None:
    """Return the highest title earned at the given level, or None."""
    best = None
    for lvl, title in LEVEL_TITLES.items():
        if level >= lvl:
            best = title
    return best


def glow_for_level(level: int) -> str | None:
    """Return the nametag glow colour for the given level, or None."""
    best = None
    for lvl, colour in LEVEL_GLOW.items():
        if level >= lvl:
            best = colour
    return best


def xp_for_outcome(outcome: str | None) -> int:
    """Return XP bonus for a signal outcome."""
    if outcome == "WIN":
        return XP_OUTCOME_WIN
    if outcome == "LOSS":
        return XP_OUTCOME_LOSS
    if outcome == "NEUTRAL":
        return XP_OUTCOME_NEUTRAL
    return 0
