"""Load TradeArena docs into a searchable knowledge base for the Discord bot."""

from __future__ import annotations

import os
from pathlib import Path


def _find_docs_root() -> Path:
    """Locate the docs/ directory relative to this file or via env var."""
    if env_root := os.getenv("TRADEARENA_DOCS_ROOT"):
        return Path(env_root)
    # Walk up from services/discord_bot/ to repo root
    here = Path(__file__).resolve().parent
    for ancestor in [here.parent.parent, Path("/opt/tradearena")]:
        candidate = ancestor / "docs"
        if candidate.is_dir():
            return candidate
    return here  # fallback


def load_knowledge_base() -> dict[str, str]:
    """Load all markdown docs into a dict keyed by relative path.

    Returns:
        {"community/faq.md": "# TradeArena FAQ ...", ...}
    """
    docs_root = _find_docs_root()
    docs: dict[str, str] = {}
    if not docs_root.is_dir():
        return docs
    for md_file in sorted(docs_root.rglob("*.md")):
        rel = md_file.relative_to(docs_root)
        try:
            docs[str(rel)] = md_file.read_text(encoding="utf-8")
        except OSError:
            continue
    return docs


def build_context_prompt(knowledge: dict[str, str]) -> str:
    """Build a system prompt from the loaded docs for answering questions."""
    sections = []
    for path, content in knowledge.items():
        sections.append(f"--- {path} ---\n{content}")
    docs_block = "\n\n".join(sections)
    return (
        "You are the TradeArena Community Manager bot. You help users with questions about "
        "TradeArena — an open-source competitive arena where trading bots submit "
        "cryptographically committed predictions and compete on a live leaderboard.\n\n"
        "Answer questions using ONLY the documentation below. If you don't know the answer, "
        "say so and suggest asking in #general or opening a GitHub issue.\n\n"
        "Be concise, friendly, and helpful. Use code blocks for commands. "
        "Never provide financial advice.\n\n"
        f"## Documentation\n\n{docs_block}"
    )


# Also load the README as top-level context
def load_readme() -> str:
    """Load the repo README."""
    for candidate in [
        Path(__file__).resolve().parent.parent.parent / "README.md",
        Path("/opt/tradearena/README.md"),
    ]:
        if candidate.is_file():
            try:
                return candidate.read_text(encoding="utf-8")
            except OSError:
                continue
    return ""
