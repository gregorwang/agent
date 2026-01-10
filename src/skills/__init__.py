"""
Skills module for BENEDICTJUN Agent.

Provides the SkillManager class for discovering, loading, and activating
Claude Code-style Skills defined in SKILL.md files.
"""

from .skills import Skill, SkillManager, get_skill_manager

__all__ = ["Skill", "SkillManager", "get_skill_manager"]
