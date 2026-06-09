from .games import register_games_commands
from .history import register_history_commands
from .llm import register_llm_commands
from .media import register_media_commands
from .memory import register_memory_commands
from .niuniu import register_niuniu_commands
from .rules import register_rules_commands
from .session import register_session_commands
from .tieba import register_tieba_commands
from .utility import register_utility_commands

__all__ = [
    "register_games_commands",
    "register_history_commands",
    "register_llm_commands",
    "register_media_commands",
    "register_memory_commands",
    "register_niuniu_commands",
    "register_rules_commands",
    "register_session_commands",
    "register_tieba_commands",
    "register_utility_commands",
]
