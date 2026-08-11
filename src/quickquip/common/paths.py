from __future__ import annotations

from pathlib import Path

from quickquip.common.env import PROJECT_ROOT


CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
LLM_ABOUT_DIR = PROJECT_ROOT / "llm_about"
CONFIG_PERSONAS_DIR = CONFIG_DIR / "personas"
CHAT_RULES_TOML_PATH = Path("config/chat_rules.toml")
TIEBA_DATA_DIR = Path("data/tieba")
GAME_SCORES_JSON_PATH = Path("data/game_scores.json")
WORDCLOUD_MESSAGES_DIR = DATA_DIR / "wordcloud_msgs"
LOGS_DIR = DATA_DIR / "logs"

CONFIG_LLM_TOML = CONFIG_DIR / "llm.toml"
CONFIG_GENERATION_TOML = CONFIG_DIR / "generation.toml"
CONFIG_GAMES_TOML = CONFIG_DIR / "games.toml"
CONFIG_SENSITIVE_WORDS_TOML = CONFIG_DIR / "sensitive_words.toml"
CONFIG_AWAKENING_TOML = CONFIG_DIR / "awakening.toml"

LLM_DB_PATH = DATA_DIR / "llm.db"
DAILY_SUMMARIES_DB_PATH = DATA_DIR / "daily_summaries.db"
PERIOD_REPORTS_DB_PATH = DATA_DIR / "period_reports.db"
WEEKLY_REPORT_GROUPS_PATH = DATA_DIR / "weekly_report_groups.json"
MONTHLY_REPORT_GROUPS_PATH = DATA_DIR / "monthly_report_groups.json"
DAILY_MESSAGES_DIR = DATA_DIR / "daily_msgs"
GAME_ECONOMY_DB_PATH = DATA_DIR / "game_economy.db"
STATS_JSON_PATH = DATA_DIR / "stats.json"
RULE_SWITCH_JSON_PATH = DATA_DIR / "rule_switch.json"
OFFLINE_MESSAGES_DB_PATH = DATA_DIR / "offline_messages.db"
QUOTES_DB_PATH = DATA_DIR / "quotes.db"
MCP_STATUS_JSON_PATH = DATA_DIR / "mcp_status.json"
WEB_ADMIN_SESSIONS_DB_PATH = DATA_DIR / "web_admin_sessions.db"
WEB_ADMIN_ACTIONS_DB_PATH = DATA_DIR / "web_admin_actions.db"
LLM_TRACE_DB_PATH = DATA_DIR / "llm_trace.db"
LLM_USAGE_DB_PATH = DATA_DIR / "llm_usage.db"

LLM_VOCAB_YAML_PATH = LLM_ABOUT_DIR / "vocab.yaml"
LLM_IDENTITIES_YAML_PATH = LLM_ABOUT_DIR / "identities.yaml"
