from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models as m
from ..db import get_session

SessionDep = Depends(get_session)


def get_player_or_404(player_id: int, session: Session = SessionDep) -> m.Player:
    player = session.get(m.Player, player_id)
    if not player:
        raise HTTPException(404, f"player {player_id} not found")
    return player


def get_game_or_404(game_id: int, session: Session = SessionDep) -> m.Game:
    game = session.get(m.Game, game_id)
    if not game:
        raise HTTPException(404, f"game {game_id} not found")
    return game
