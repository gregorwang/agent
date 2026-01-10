def should_use_chatlog_chain(text: str) -> bool:
    """Decide whether to force the chatlog subagent chain."""
    normalized = text.strip()
    if not normalized:
        return False
    explicit_phrases = [
        "请查找聊天记录",
        "请查询聊天记录",
        "查找聊天记录",
        "查询聊天记录",
        "结合聊天记录",
        "根据聊天记录",
        "聊天记录里",
        "聊天记录中",
    ]
    return any(phrase in normalized for phrase in explicit_phrases)
