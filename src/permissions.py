"""
Permission Manager for BENEDICTJUN TUI
Manages tool execution permissions and allowlists
"""

import json
from pathlib import Path
from typing import Dict, Set, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PermissionEntry:
    """Represents a permission entry for a tool."""
    tool_name: str
    pattern: Optional[str] = None  # Optional pattern for more granular control
    added_at: Optional[str] = None
    description: Optional[str] = None


class PermissionManager:
    """
    Manages tool execution permissions similar to Claude Code.
    
    Features:
    - Track allowed and denied tools
    - Support "Always Allow" persistence
    - Pattern-based permissions (e.g., allow specific commands)
    - Load/save from settings file
    
    Usage:
        pm = PermissionManager()
        
        # Check if tool needs approval
        if pm.should_ask_permission("Bash", {"command": "rm -rf /"}):
            # Show approval prompt
            pass
        
        # Add to allowlist
        pm.add_to_allowlist("Bash")
    """
    
    # Tools that always require approval (cannot be auto-allowed)
    ALWAYS_ASK_TOOLS = frozenset({
        # None by default - user can configure
    })
    
    # Tools that are safe by default (never ask)
    SAFE_TOOLS = frozenset({
        "Read",
        "Glob",
        "Grep",
    })
    
    # Potentially dangerous tools that should ask by default
    DANGEROUS_TOOLS = frozenset({
        "Bash",
        "Edit",
        "Write",
        "Task",
    })
    
    def __init__(
        self,
        settings_path: Optional[Path] = None,
        allowlist: Optional[Set[str]] = None,
        denylist: Optional[Set[str]] = None,
        ask_by_default: bool = True,
    ):
        """
        Initialize the permission manager.
        
        Args:
            settings_path: Path to persist permissions
            allowlist: Initial set of allowed tools
            denylist: Initial set of denied tools
            ask_by_default: If True, ask for unknown tools
        """
        self.settings_path = settings_path or Path("permissions.json")
        self.allowlist: Set[str] = allowlist or set()
        self.denylist: Set[str] = denylist or set()
        self.ask_by_default = ask_by_default
        self.pattern_allowlist: Dict[str, List[str]] = {}  # tool -> patterns
        
        # Try to load existing settings
        self._load()
    
    def _load(self) -> None:
        """Load permissions from settings file."""
        if not self.settings_path.exists():
            return
        
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            self.allowlist = set(data.get("allowlist", []))
            self.denylist = set(data.get("denylist", []))
            self.pattern_allowlist = data.get("patterns", {})
            self.ask_by_default = data.get("ask_by_default", True)
        except (json.JSONDecodeError, IOError):
            pass
    
    def _save(self) -> None:
        """Save permissions to settings file."""
        data = {
            "allowlist": list(self.allowlist),
            "denylist": list(self.denylist),
            "patterns": self.pattern_allowlist,
            "ask_by_default": self.ask_by_default,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        
        try:
            self.settings_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except IOError:
            pass
    
    def should_ask_permission(
        self,
        tool_name: str,
        tool_input: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Determine if a tool execution requires user approval.
        
        Args:
            tool_name: Name of the tool
            tool_input: Optional input parameters
            
        Returns:
            True if approval is needed, False if allowed
        """
        # Check if in always-ask list
        if tool_name in self.ALWAYS_ASK_TOOLS:
            return True
        
        # Check if explicitly denied
        if tool_name in self.denylist:
            return True  # Ask to potentially override
        
        # Check if explicitly allowed
        if tool_name in self.allowlist:
            return False
        
        # Check if it's a safe tool
        if tool_name in self.SAFE_TOOLS:
            return False
        
        # Check pattern-based permissions
        if tool_input and tool_name in self.pattern_allowlist:
            patterns = self.pattern_allowlist[tool_name]
            input_str = json.dumps(tool_input)
            for pattern in patterns:
                if pattern in input_str:
                    return False
        
        # For dangerous tools, always ask
        if tool_name in self.DANGEROUS_TOOLS:
            return True
        
        # Default behavior
        return self.ask_by_default
    
    def add_to_allowlist(self, tool_name: str, save: bool = True) -> None:
        """Add a tool to the allowlist."""
        self.allowlist.add(tool_name)
        self.denylist.discard(tool_name)
        if save:
            self._save()
    
    def remove_from_allowlist(self, tool_name: str, save: bool = True) -> None:
        """Remove a tool from the allowlist."""
        self.allowlist.discard(tool_name)
        if save:
            self._save()
    
    def add_to_denylist(self, tool_name: str, save: bool = True) -> None:
        """Add a tool to the denylist."""
        self.denylist.add(tool_name)
        self.allowlist.discard(tool_name)
        if save:
            self._save()
    
    def add_pattern(
        self,
        tool_name: str,
        pattern: str,
        save: bool = True
    ) -> None:
        """Add a pattern-based permission for a tool."""
        if tool_name not in self.pattern_allowlist:
            self.pattern_allowlist[tool_name] = []
        if pattern not in self.pattern_allowlist[tool_name]:
            self.pattern_allowlist[tool_name].append(pattern)
        if save:
            self._save()
    
    def remove_pattern(
        self,
        tool_name: str,
        pattern: str,
        save: bool = True
    ) -> None:
        """Remove a pattern-based permission."""
        if tool_name in self.pattern_allowlist:
            if pattern in self.pattern_allowlist[tool_name]:
                self.pattern_allowlist[tool_name].remove(pattern)
            if not self.pattern_allowlist[tool_name]:
                del self.pattern_allowlist[tool_name]
        if save:
            self._save()
    
    def get_status(self) -> Dict[str, Any]:
        """Get current permission status."""
        return {
            "allowlist": sorted(self.allowlist),
            "denylist": sorted(self.denylist),
            "patterns": self.pattern_allowlist.copy(),
            "ask_by_default": self.ask_by_default,
            "safe_tools": sorted(self.SAFE_TOOLS),
            "dangerous_tools": sorted(self.DANGEROUS_TOOLS),
        }
    
    def reset(self, save: bool = True) -> None:
        """Reset all permissions to defaults."""
        self.allowlist.clear()
        self.denylist.clear()
        self.pattern_allowlist.clear()
        self.ask_by_default = True
        if save:
            self._save()
    
    def describe_tool_risk(self, tool_name: str) -> str:
        """Get a human-readable description of the tool's risk level."""
        if tool_name in self.SAFE_TOOLS:
            return "Safe (read-only)"
        elif tool_name in self.DANGEROUS_TOOLS:
            if tool_name == "Bash":
                return "High risk (executes shell commands)"
            elif tool_name in ("Edit", "Write"):
                return "Medium risk (modifies files)"
            elif tool_name == "Task":
                return "Medium risk (delegates to subagent)"
        return "Unknown risk level"
    
    def format_permission_table(self) -> str:
        """Format permissions for display."""
        lines = []
        lines.append("╭──────────────────────────────────────────╮")
        lines.append("│           Permission Settings            │")
        lines.append("├──────────────────────────────────────────┤")
        
        # Allowlist
        if self.allowlist:
            lines.append("│ ✓ Always Allowed:                        │")
            for tool in sorted(self.allowlist):
                lines.append(f"│   • {tool:<36} │")
        
        # Denylist
        if self.denylist:
            lines.append("│ ✗ Denied:                                │")
            for tool in sorted(self.denylist):
                lines.append(f"│   • {tool:<36} │")
        
        # Default behavior
        behavior = "Ask for approval" if self.ask_by_default else "Auto-allow"
        lines.append(f"│ Default: {behavior:<31} │")
        lines.append("╰──────────────────────────────────────────╯")
        
        return "\n".join(lines)
