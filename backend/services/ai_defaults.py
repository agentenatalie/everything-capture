AI_DEFAULT_BASE_URL = ""
AI_MODEL_OPTIONS = [
    "deepseek-v3.2",
    "deepseek-v3.2-thinking",
    "glm-4.7",
    "minimax-m2.1",
    "kimi-k2.5",
    "glm-5",
    "minimax-m2.5",
]
AI_DEFAULT_MODEL = AI_MODEL_OPTIONS[0]

AI_AGENT_DEFAULT_CAN_MANAGE_FOLDERS = True
AI_AGENT_DEFAULT_CAN_PARSE_CONTENT = True
AI_AGENT_DEFAULT_CAN_SYNC_OBSIDIAN = True
AI_AGENT_DEFAULT_CAN_SYNC_NOTION = True
AI_AGENT_DEFAULT_CAN_EXECUTE_COMMANDS = True
AI_AGENT_DEFAULT_CAN_WEB_SEARCH = True


def coerce_bool(value, default: bool) -> bool:
    if value is None:
        return default
    return bool(value)
