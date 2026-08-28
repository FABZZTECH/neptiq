"""neptiq_robots — dual-agent robots.txt evaluation. Pure; Zone-U safe."""

from __future__ import annotations

from neptiq_robots.evaluate import (
    GOOGLEBOT_UA_TOKEN,
    NEPTIQ_UA_TOKEN,
    RobotsDecision,
    RobotsDocument,
    RobotsEvaluator,
    evaluate_url,
)

__all__ = [
    "GOOGLEBOT_UA_TOKEN",
    "NEPTIQ_UA_TOKEN",
    "RobotsDecision",
    "RobotsDocument",
    "RobotsEvaluator",
    "evaluate_url",
]
