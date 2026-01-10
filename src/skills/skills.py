"""
Skills Manager for BENEDICTJUN Agent

This module implements a Skills system similar to Claude Code's skills feature.
Skills are reusable prompts and instructions defined in SKILL.md files that
extend the agent's capabilities for specific tasks.

Skills are stored in:
- `.claude/skills/` - Project-specific skills
- `~/.claude/skills/` - Global user skills
"""

import os
import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any


@dataclass
class Skill:
    """Represents a single Skill with its metadata and instructions."""
    
    name: str
    description: str
    instructions: str
    allowed_tools: Optional[List[str]] = None
    model: Optional[str] = None
    context: Optional[str] = None  # "fork" for forked context
    agent: Optional[str] = None  # Agent type: "Explore", "Plan", etc.
    hooks: Optional[Dict[str, Any]] = None
    user_invocable: bool = True
    path: Optional[Path] = None
    
    def __post_init__(self):
        """Validate skill name format."""
        if self.name:
            # Name should be lowercase with hyphens only
            if not re.match(r'^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$', self.name):
                # Auto-fix the name
                self.name = self.name.lower().replace('_', '-').replace(' ', '-')
    
    @property
    def summary(self) -> str:
        """Get a short summary for display."""
        desc = self.description
        if len(desc) > 60:
            desc = desc[:57] + "..."
        return f"{self.name}: {desc}"


class SkillManager:
    """
    Manages skill discovery, loading, and activation.
    
    Skills are discovered from:
    1. Project directory: .claude/skills/
    2. Global directory: ~/.claude/skills/
    
    Each skill is a directory containing a SKILL.md file with YAML frontmatter.
    """
    
    def __init__(
        self,
        project_path: Optional[Path] = None,
        global_path: Optional[Path] = None
    ):
        """
        Initialize the SkillManager.
        
        Args:
            project_path: Path to project skills directory (default: .claude/skills/)
            global_path: Path to global skills directory (default: ~/.claude/skills/)
        """
        self.project_path = project_path or Path(".claude/skills")
        self.global_path = global_path or Path.home() / ".claude" / "skills"
        
        self._skills: Dict[str, Skill] = {}
        self._active_skill: Optional[Skill] = None
        
        # Discover skills on initialization
        self.discover_skills()
    
    def discover_skills(self) -> List[Skill]:
        """
        Discover all available skills from project and global directories.
        
        Returns:
            List of discovered Skill objects
        """
        self._skills.clear()
        
        # Discover from project directory first (higher priority)
        if self.project_path.exists():
            for skill_dir in self.project_path.iterdir():
                if skill_dir.is_dir():
                    skill = self._load_skill_from_dir(skill_dir)
                    if skill:
                        self._skills[skill.name] = skill
        
        # Discover from global directory
        if self.global_path.exists():
            for skill_dir in self.global_path.iterdir():
                if skill_dir.is_dir():
                    # Don't override project-level skills
                    skill = self._load_skill_from_dir(skill_dir)
                    if skill and skill.name not in self._skills:
                        self._skills[skill.name] = skill
        
        return list(self._skills.values())
    
    def _load_skill_from_dir(self, skill_dir: Path) -> Optional[Skill]:
        """
        Load a skill from a directory containing SKILL.md.
        
        Args:
            skill_dir: Path to the skill directory
            
        Returns:
            Skill object if successfully loaded, None otherwise
        """
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            return None
        
        return self.load_skill(skill_file)
    
    def load_skill(self, skill_path: Path) -> Optional[Skill]:
        """
        Load and parse a single SKILL.md file.
        
        The file format is:
        ---
        name: skill-name
        description: Brief description
        allowed-tools: Tool1, Tool2 (optional)
        model: claude-sonnet-4-5 (optional)
        ---
        # Skill Instructions
        
        Markdown content with instructions...
        
        Args:
            skill_path: Path to the SKILL.md file
            
        Returns:
            Skill object if successfully parsed, None otherwise
        """
        try:
            content = skill_path.read_text(encoding="utf-8")
            
            # Parse YAML frontmatter
            frontmatter_match = re.match(
                r'^---\s*\n(.*?)\n---\s*\n(.*)$',
                content,
                re.DOTALL
            )
            
            if not frontmatter_match:
                # No frontmatter, use directory name as skill name
                return Skill(
                    name=skill_path.parent.name,
                    description="No description provided",
                    instructions=content,
                    path=skill_path
                )
            
            frontmatter_str = frontmatter_match.group(1)
            instructions = frontmatter_match.group(2).strip()
            
            # Parse YAML
            try:
                metadata = yaml.safe_load(frontmatter_str) or {}
            except yaml.YAMLError:
                metadata = {}
            
            # Extract fields
            name = metadata.get("name", skill_path.parent.name)
            description = metadata.get("description", "No description provided")
            
            # Parse allowed-tools (can be comma-separated string or list)
            allowed_tools = metadata.get("allowed-tools")
            if isinstance(allowed_tools, str):
                allowed_tools = [t.strip() for t in allowed_tools.split(",")]
            
            return Skill(
                name=name,
                description=description,
                instructions=instructions,
                allowed_tools=allowed_tools,
                model=metadata.get("model"),
                context=metadata.get("context"),
                agent=metadata.get("agent"),
                hooks=metadata.get("hooks"),
                user_invocable=metadata.get("user-invocable", True),
                path=skill_path
            )
            
        except Exception as e:
            print(f"Warning: Failed to load skill from {skill_path}: {e}")
            return None
    
    def get_skill_by_name(self, name: str) -> Optional[Skill]:
        """
        Get a skill by its name.
        
        Args:
            name: The skill name
            
        Returns:
            Skill object if found, None otherwise
        """
        return self._skills.get(name)
    
    def list_skills(self) -> List[Skill]:
        """
        List all available skills.
        
        Returns:
            List of Skill objects
        """
        return list(self._skills.values())
    
    def match_skills(self, user_prompt: str) -> List[Skill]:
        """
        Match skills based on user prompt using keyword matching.
        
        This is a simple implementation that matches based on keywords
        in the skill description. A more sophisticated implementation
        could use embeddings or Claude to determine relevance.
        
        Args:
            user_prompt: The user's input prompt
            
        Returns:
            List of matching Skill objects, sorted by relevance
        """
        prompt_lower = user_prompt.lower()
        matches = []
        
        # Define keyword mappings for common patterns
        keyword_patterns = {
            "commit": ["commit", "git", "提交", "commit message"],
            "review": ["review", "审查", "code review", "代码审查", "cr"],
            "debug": ["debug", "调试", "bug", "error", "错误", "问题"],
            "doc": ["document", "文档", "readme", "docstring", "注释"],
            "test": ["test", "测试", "unit test", "单元测试", "用例"],
            "explain": ["explain", "解释", "how does", "什么是", "怎么"],
        }
        
        for skill in self._skills.values():
            if not skill.user_invocable:
                continue
                
            score = 0
            skill_name = skill.name.lower()
            skill_desc = skill.description.lower()
            
            # Direct name match
            if skill_name in prompt_lower:
                score += 10
            
            # Check description keywords
            for key_cat, keywords in keyword_patterns.items():
                if key_cat in skill_name or key_cat in skill_desc:
                    for keyword in keywords:
                        if keyword in prompt_lower:
                            score += 5
                            break
            
            # Simple word overlap with description
            prompt_words = set(prompt_lower.split())
            desc_words = set(skill_desc.split())
            overlap = len(prompt_words & desc_words)
            score += overlap
            
            if score > 0:
                matches.append((score, skill))
        
        # Sort by score descending
        matches.sort(key=lambda x: x[0], reverse=True)
        return [skill for _, skill in matches]
    
    def activate_skill(self, skill: Skill) -> str:
        """
        Activate a skill and return its full instructions.
        
        Args:
            skill: The Skill to activate
            
        Returns:
            The skill's instruction text to be injected into the prompt
        """
        self._active_skill = skill
        
        # Build the skill context
        context_parts = [
            f"# Active Skill: {skill.name}",
            "",
            skill.instructions,
        ]
        
        if skill.allowed_tools:
            context_parts.extend([
                "",
                f"**Allowed tools for this skill:** {', '.join(skill.allowed_tools)}"
            ])
        
        return "\n".join(context_parts)
    
    def deactivate_skill(self) -> None:
        """Deactivate the current skill."""
        self._active_skill = None
    
    @property
    def active_skill(self) -> Optional[Skill]:
        """Get the currently active skill."""
        return self._active_skill
    
    def get_skill_prompt_injection(self, user_prompt: str) -> Optional[str]:
        """
        Get the skill instructions to inject based on user prompt.
        
        This automatically matches and activates relevant skills.
        
        Args:
            user_prompt: The user's input prompt
            
        Returns:
            Skill instructions to inject, or None if no match
        """
        # If a skill is already active, keep using it
        if self._active_skill:
            return self.activate_skill(self._active_skill)
        
        # Try to match a skill
        matches = self.match_skills(user_prompt)
        if matches:
            # Activate the best match
            return self.activate_skill(matches[0])
        
        return None
    
    def create_skill(
        self,
        name: str,
        description: str,
        instructions: str,
        project_level: bool = True,
        allowed_tools: Optional[List[str]] = None,
        model: Optional[str] = None
    ) -> Skill:
        """
        Create a new skill.
        
        Args:
            name: Skill name (lowercase with hyphens)
            description: Brief description
            instructions: Markdown instructions
            project_level: If True, create in project directory; else global
            allowed_tools: Optional list of allowed tools
            model: Optional model override
            
        Returns:
            The created Skill object
        """
        base_path = self.project_path if project_level else self.global_path
        skill_dir = base_path / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        
        # Build frontmatter
        frontmatter = {"name": name, "description": description}
        if allowed_tools:
            frontmatter["allowed-tools"] = ", ".join(allowed_tools)
        if model:
            frontmatter["model"] = model
        
        # Write SKILL.md
        skill_file = skill_dir / "SKILL.md"
        content = f"---\n{yaml.dump(frontmatter, allow_unicode=True)}---\n\n{instructions}"
        skill_file.write_text(content, encoding="utf-8")
        
        # Load and register the skill
        skill = self.load_skill(skill_file)
        if skill:
            self._skills[skill.name] = skill
        
        return skill


# Convenience function for global access
_skill_manager: Optional[SkillManager] = None


def get_skill_manager(
    project_path: Optional[Path] = None,
    global_path: Optional[Path] = None
) -> SkillManager:
    """
    Get or create the global SkillManager instance.
    
    Args:
        project_path: Optional project skills path
        global_path: Optional global skills path
        
    Returns:
        SkillManager instance
    """
    global _skill_manager
    if _skill_manager is None:
        _skill_manager = SkillManager(project_path, global_path)
    return _skill_manager
