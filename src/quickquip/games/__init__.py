from __future__ import annotations

from quickquip.games.registry import BaseGame as BaseGame, GameRegistry as GameRegistry, GameResult as GameResult
from quickquip.games.scores import GameScores as GameScores
from quickquip.games.scores import game_scores as game_scores
from quickquip.games.blackjack import BlackjackGame as BlackjackGame
from quickquip.games.config import (
    BlackjackConfig as BlackjackConfig,
    EconomyConfig as EconomyConfig,
    GameConfig as GameConfig,
    NiuNiuConfig as NiuNiuConfig,
    NumberBombConfig as NumberBombConfig,
    RussianRouletteConfig as RussianRouletteConfig,
    load_games_config as load_games_config,
)
from quickquip.games.economy import GameEconomyStore as GameEconomyStore
from quickquip.games.niuniu import NiuNiuStore as NiuNiuStore
from quickquip.games.number_bomb import NumberBombGame as NumberBombGame
from quickquip.games.russian_roulette import RussianRouletteGame as RussianRouletteGame
