from fastapi import APIRouter, Depends

from ..auth import get_current_player
from ..database import get_db
from ..elo import get_effective_rating
from ..models import Player, PlayerModeRating, PlayerTopicRating, Question

router = APIRouter(prefix="/players", tags=["players"])


@router.get("/me")
def get_me(player: Player = Depends(get_current_player), db=Depends(get_db)):
    topics = [t[0] for t in db.query(Question.topic).distinct().all()]
    topic_ratings = {}
    for topic in topics:
        row = (
            db.query(PlayerTopicRating)
            .filter_by(player_id=player.player_id, topic=topic)
            .first()
        )
        if row is None:
            topic_ratings[topic] = {
                "theta_effective": player.theta_overall,
                "rd": player.rd_overall,
                "attempts_count": 0,
            }
        else:
            topic_ratings[topic] = {
                "theta_effective": get_effective_rating(
                    row.theta, row.rd, player.theta_overall, row.attempts_count
                ),
                "rd": row.rd,
                "attempts_count": row.attempts_count,
            }

    mode_rows = db.query(PlayerModeRating).filter_by(player_id=player.player_id).all()
    mode_ratings = {
        r.mode: {
            "theta_effective": get_effective_rating(
                r.theta, r.rd, player.theta_overall, r.attempts_count
            ),
            "rd": r.rd,
            "attempts_count": r.attempts_count,
        }
        for r in mode_rows
    }

    return {
        "player_id": player.player_id,
        "name": player.name,
        "theta_overall": player.theta_overall,
        "rd_overall": player.rd_overall,
        "topic_ratings": topic_ratings,
        "mode_ratings": mode_ratings,
    }
