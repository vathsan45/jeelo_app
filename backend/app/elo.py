"""THE SINGLE SOURCE OF TRUTH for all rating math.

Every other module imports from here — no router or service ever touches
theta/rd fields directly or recomputes any of this logic inline.
"""

from .models import Player, PlayerModeRating, PlayerTopicRating, Question

# Questions have no stored RD; they face many players so their difficulty
# rating should move slower than a player's. A fixed pseudo-RD of 175 gives
# them an effective K of 20 (half the player's starting K) via update_rating.
QUESTION_PSEUDO_RD = 175.0


def expected_probability(theta_p, theta_q):
    return 1 / (1 + 10 ** ((theta_q - theta_p) / 400))


def update_rating(theta, rd, opponent_theta, actual_outcome, base_k=40):
    # actual_outcome: 1 if correct, 0 if wrong
    # RD scales the effective K: high uncertainty (high RD) = bigger swings allowed,
    # low uncertainty (low RD) = smaller, more stable swings
    expected = expected_probability(theta, opponent_theta)
    effective_k = base_k * (rd / 350)  # 350 is the starting/max RD, so this scales
    #                                    k down as confidence increases
    new_theta = theta + effective_k * (actual_outcome - expected)
    new_rd = max(50, rd * 0.95)  # RD shrinks slightly with every attempt, floor at 50
    return new_theta, new_rd


def get_effective_rating(player_topic_or_mode_theta, player_topic_or_mode_rd,
                         parent_theta, attempts_count):
    # SHRINKAGE: blend specific rating toward the parent (overall) rating when
    # the specific bucket doesn't have enough data yet — this is what makes the
    # multi-level Elo reliable instead of noisy on small samples
    if attempts_count >= 15:
        weight = 1.0
    else:
        weight = attempts_count / 15  # linear ramp — 0 attempts = pure parent,
        #                               15+ attempts = pure specific rating
    return weight * player_topic_or_mode_theta + (1 - weight) * parent_theta


def _get_or_create_topic_rating(db_session, player_id, topic):
    row = (
        db_session.query(PlayerTopicRating)
        .filter_by(player_id=player_id, topic=topic)
        .first()
    )
    if row is None:
        row = PlayerTopicRating(player_id=player_id, topic=topic,
                                theta=1200.0, rd=350.0, attempts_count=0)
        db_session.add(row)
        db_session.flush()
    return row


def _get_or_create_mode_rating(db_session, player_id, mode):
    row = (
        db_session.query(PlayerModeRating)
        .filter_by(player_id=player_id, mode=mode)
        .first()
    )
    if row is None:
        row = PlayerModeRating(player_id=player_id, mode=mode,
                               theta=1200.0, rd=350.0, attempts_count=0)
        db_session.add(row)
        db_session.flush()
    return row


def apply_attempt_result(player_id, question_id, mode, correct, db_session):
    """Apply ALL rating updates for one attempted question, atomically.

    Updates, in order, all computed from the same before-snapshot:
      1. player.theta_overall / rd_overall
      2. player_topic_ratings row for the question's topic (lazy-created)
      3. player_mode_ratings row for the session's mode (lazy-created;
         SKIPPED when mode == "placement")
      4. questions.theta_q (mirror-image update)

    Returns a dict of before/after values and deltas for logging.
    Commits the transaction; rolls back on any error.
    """
    outcome = 1 if correct else 0

    try:
        player = db_session.get(Player, player_id)
        question = db_session.get(Question, question_id)
        if player is None or question is None:
            raise ValueError(f"unknown player {player_id!r} or question {question_id!r}")

        theta_p_before = player.theta_overall
        theta_q_before = question.theta_q

        # 1. overall rating — always updates on any attempted question, any mode
        new_theta, new_rd = update_rating(
            player.theta_overall, player.rd_overall, theta_q_before, outcome
        )
        overall_delta = new_theta - player.theta_overall
        player.theta_overall, player.rd_overall = new_theta, new_rd

        # 2. topic rating for this question's topic
        topic_row = _get_or_create_topic_rating(db_session, player_id, question.topic)
        new_theta, new_rd = update_rating(
            topic_row.theta, topic_row.rd, theta_q_before, outcome
        )
        topic_delta = new_theta - topic_row.theta
        topic_row.theta, topic_row.rd = new_theta, new_rd
        topic_row.attempts_count += 1

        # 3. mode rating — placement is calibration, not a trackable mode skill
        mode_delta = None
        if mode != "placement":
            mode_row = _get_or_create_mode_rating(db_session, player_id, mode)
            new_theta, new_rd = update_rating(
                mode_row.theta, mode_row.rd, theta_q_before, outcome
            )
            mode_delta = new_theta - mode_row.theta
            mode_row.theta, mode_row.rd = new_theta, new_rd
            mode_row.attempts_count += 1

        # 4. question difficulty — mirror image: question "wins" when player is wrong
        new_theta_q, _ = update_rating(
            theta_q_before, QUESTION_PSEUDO_RD, theta_p_before, 1 - outcome
        )
        question_delta = new_theta_q - theta_q_before
        question.theta_q = new_theta_q

        db_session.commit()
    except Exception:
        db_session.rollback()
        raise

    return {
        "theta_p_before": theta_p_before,
        "theta_q_before": theta_q_before,
        "overall": {"theta": player.theta_overall, "rd": player.rd_overall,
                    "delta": overall_delta},
        "topic": {"name": question.topic, "theta": topic_row.theta,
                  "rd": topic_row.rd, "delta": topic_delta},
        "mode": None if mode_delta is None else {
            "name": mode, "delta": mode_delta},
        "question": {"theta_q": question.theta_q, "delta": question_delta},
    }
