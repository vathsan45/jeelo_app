"""Bot archetypes for Risk Arena — supporting cast, kept minimal.

All probability math comes from elo.py.
"""

import random

from .elo import expected_probability

ARCHETYPES = {
    "rusher":     {"confidence_bias": 250,  "risk_multiplier": 0.6, "reaction_range": (300, 600)},
    "skipper":    {"confidence_bias": -250, "risk_multiplier": 1.8, "reaction_range": (1200, 2000)},
    "calibrated": {"confidence_bias": 0,    "risk_multiplier": 1.0, "reaction_range": (700, 1000)},
}

BOT_NAMES = {
    "rusher": "Blaze",
    "skipper": "Turtle",
    "calibrated": "Sage",
}


def bot_decide(bot_theta, archetype, theta_q, marking_scheme):
    """Decide whether the bot raises its hand, and how fast."""
    perceived_theta = bot_theta + archetype["confidence_bias"]
    p = expected_probability(perceived_theta, theta_q)
    penalty = abs(marking_scheme["incorrect"])  # penalty as positive magnitude
    breakeven = penalty / (marking_scheme["correct"] + penalty)
    attempt = p > (breakeven * archetype["risk_multiplier"])
    reaction_ms = random.randint(*archetype["reaction_range"])
    return attempt, reaction_ms


def bot_answer_correct(bot_true_theta, theta_q):
    p = expected_probability(bot_true_theta, theta_q)
    return random.random() < p
