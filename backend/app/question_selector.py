"""Shared adaptive question selection — used by placement, practice quiz,
and risk arena. All rating math comes from elo.py."""

import random

from .elo import get_effective_rating
from .models import Player, PlayerModeRating, PlayerTopicRating, Question


def _rating_source(db_session, player, mode, topic_filter):
    """Pick the (theta, rd) the selector should target, with shrinkage applied."""
    if mode == "risk_arena":
        row = (
            db_session.query(PlayerModeRating)
            .filter_by(player_id=player.player_id, mode="risk_arena")
            .first()
        )
        if row is not None:
            theta = get_effective_rating(row.theta, row.rd, player.theta_overall,
                                         row.attempts_count)
            return theta, row.rd
        return player.theta_overall, player.rd_overall

    if topic_filter is not None:
        row = (
            db_session.query(PlayerTopicRating)
            .filter_by(player_id=player.player_id, topic=topic_filter)
            .first()
        )
        if row is not None:
            theta = get_effective_rating(row.theta, row.rd, player.theta_overall,
                                         row.attempts_count)
            return theta, row.rd
        return player.theta_overall, player.rd_overall

    return player.theta_overall, player.rd_overall


def _weighted_random_choice(scored):
    """scored: list of (question, distance). Weight = 1/(1+distance)."""
    weights = [1 / (1 + dist) for _, dist in scored]
    return random.choices([q for q, _ in scored], weights=weights, k=1)[0]


def select_next_question(player_id, mode, topic_filter, exclude_ids, db_session):
    player = db_session.get(Player, player_id)
    if player is None:
        raise ValueError(f"unknown player {player_id!r}")

    theta, rd = _rating_source(db_session, player, mode, topic_filter)

    query = db_session.query(Question)
    if topic_filter is not None:
        query = query.filter(Question.topic == topic_filter)
    if exclude_ids:
        query = query.filter(~Question.question_id.in_(exclude_ids))
    candidates = query.all()
    if not candidates:
        return None

    target_band = max(rd, 150)  # never collapse below 150, keeps variety

    for band in (target_band, target_band * 1.5):
        scored = [(q, abs(q.theta_q - theta)) for q in candidates
                  if abs(q.theta_q - theta) <= band]
        top_candidates = sorted(scored, key=lambda x: x[1])[:6]
        if top_candidates:
            return _weighted_random_choice(top_candidates)

    return random.choice(candidates)  # band exhausted — fully random fallback
