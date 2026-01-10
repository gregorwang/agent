"""
UI Components for BENEDICTJUN TUI
Claude Code-style interactive terminal interface components

Components:
- ToolApprovalPrompt: Tool execution approval dialog
- SelectionMenu: Interactive selection menu with keyboard navigation
- DiffPreview: File modification diff display
- ThinkingPanel: AI thinking process display
"""

import asyncio
import json
from typing import Optional, List, Tuple, Dict, Any, Callable
from enum import Enum

from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import Window, HSplit, VSplit, FloatContainer, Float
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.formatted_text import FormattedText, to_formatted_text
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.syntax import Syntax
from rich.box import ROUNDED, MINIMAL

from .styles import COLORS, STYLES


class ApprovalResult(Enum):
    """Result of a tool approval prompt."""
    ALLOW = "allow"
    ALWAYS_ALLOW = "always"
    DENY = "deny"


class ToolApprovalPrompt:
    """
    Claude Code-style tool approval prompt.
    
    Displays a dialog asking user to approve a tool execution with options:
    - [Allow] - Allow this execution once
    - [Always Allow] - Add to allowlist for future executions
    - [Deny] - Reject the execution
    
    Usage:
        result = await ToolApprovalPrompt("Bash", {"command": "ls -la"}).run()
        if result == ApprovalResult.ALLOW:
            # proceed with execution
    """
    
    def __init__(
        self, 
        tool_name: str, 
        tool_input: Dict[str, Any],
        description: Optional[str] = None
    ):
        self.tool_name = tool_name
        self.tool_input = tool_input
        self.description = description or self._get_default_description()
        self.selected_index = 0
        self.options = [
            ("Allow", ApprovalResult.ALLOW, COLORS["allow"]),
            ("Always Allow", ApprovalResult.ALWAYS_ALLOW, COLORS["always"]),
            ("Deny", ApprovalResult.DENY, COLORS["deny"]),
        ]
    
    def _get_default_description(self) -> str:
        """Generate a default description based on tool name."""
        descriptions = {
            "Bash": "Execute shell command",
            "Edit": "Modify file contents",
            "Write": "Create or overwrite file",
            "Read": "Read file contents",
            "Glob": "Search for files",
            "Grep": "Search in file contents",
            "Task": "Delegate to subagent",
        }
        return descriptions.get(self.tool_name, f"Execute {self.tool_name}")
    
    def _format_input_preview(self) -> str:
        """Format tool input for preview display."""
        input_str = json.dumps(self.tool_input, indent=2, ensure_ascii=False)
        if len(input_str) > 300:
            input_str = input_str[:300] + "\n... (truncated)"
        return input_str
    
    def _get_formatted_text(self) -> List[Tuple[str, str]]:
        """Generate formatted text for the prompt display."""
        lines = []
        
        # Title bar
        lines.append(("class:approval-title", "\n ⚠ Tool Approval Required \n"))
        lines.append(("", "\n"))
        
        # Tool name and description
        lines.append(("", " "))
        lines.append(("class:approval-tool", self.tool_name))
        lines.append(("", f" - {self.description}\n"))
        lines.append(("", "\n"))
        
        # Input preview (dimmed)
        preview = self._format_input_preview()
        for line in preview.split("\n"):
            lines.append(("class:hint", f"   {line}\n"))
        
        lines.append(("", "\n"))
        
        # Option buttons
        lines.append(("", " "))
        for i, (label, _, color) in enumerate(self.options):
            if i == self.selected_index:
                # Selected button - highlight with the action color
                if label == "Allow":
                    lines.append(("class:approval-allow", f" {label} "))
                elif label == "Always Allow":
                    lines.append(("class:approval-always", f" {label} "))
                else:
                    lines.append(("class:approval-deny", f" {label} "))
            else:
                lines.append(("class:approval-button", f" {label} "))
            lines.append(("", "  "))
        
        lines.append(("", "\n\n"))
        lines.append(("class:hint", " ←/→ Navigate · Enter Confirm · Esc Cancel"))
        
        return lines
    
    async def run(self) -> Optional[ApprovalResult]:
        """Show the approval prompt and return the user's choice."""
        kb = KeyBindings()
        result: Optional[ApprovalResult] = None
        
        @kb.add("left")
        @kb.add("h")  # Vim-style
        def _left(event):
            self.selected_index = (self.selected_index - 1) % len(self.options)
        
        @kb.add("right")
        @kb.add("l")  # Vim-style
        def _right(event):
            self.selected_index = (self.selected_index + 1) % len(self.options)
        
        @kb.add("enter")
        def _confirm(event):
            nonlocal result
            result = self.options[self.selected_index][1]
            event.app.exit()
        
        @kb.add("escape")
        @kb.add("c-c")
        @kb.add("c-q")
        def _cancel(event):
            nonlocal result
            result = ApprovalResult.DENY
            event.app.exit()
        
        # Shortcut keys for quick selection
        @kb.add("a")
        def _quick_allow(event):
            nonlocal result
            result = ApprovalResult.ALLOW
            event.app.exit()
        
        @kb.add("A")  # Shift+A for Always Allow
        def _quick_always(event):
            nonlocal result
            result = ApprovalResult.ALWAYS_ALLOW
            event.app.exit()
        
        @kb.add("d")
        @kb.add("n")  # 'n' for No/Deny
        def _quick_deny(event):
            nonlocal result
            result = ApprovalResult.DENY
            event.app.exit()
        
        app = Application(
            layout=Layout(
                HSplit([
                    Window(
                        content=FormattedTextControl(text=self._get_formatted_text),
                        height=12,
                    )
                ])
            ),
            key_bindings=kb,
            style=STYLES,
            full_screen=False,
            mouse_support=True,
        )
        
        await app.run_async()
        return result


class SelectionMenu:
    """
    Claude Code-style interactive selection menu.
    
    Features:
    - Keyboard navigation (Up/Down, j/k)
    - Visual highlight for selected item
    - Optional descriptions and badges per item
    - Async-compatible
    
    Usage:
        menu = SelectionMenu(
            title="Select Model",
            items=[
                {"id": "claude-sonnet", "name": "Sonnet", "desc": "Fast"},
                {"id": "claude-opus", "name": "Opus", "desc": "Powerful"},
            ]
        )
        selected_id = await menu.run()
    """
    
    def __init__(
        self,
        title: str,
        items: List[Dict[str, Any]],
        description: Optional[str] = None,
        current_value: Optional[str] = None,
    ):
        self.title = title
        self.items = items
        self.description = description
        self.selected_index = 0
        
        # Try to find current value in items
        if current_value:
            for i, item in enumerate(items):
                if item.get("id") == current_value:
                    self.selected_index = i
                    break
    
    def _get_formatted_text(self) -> List[Tuple[str, str]]:
        """Generate formatted text for the menu display."""
        lines = []
        
        # Header
        lines.append(("", "\n"))
        lines.append(("class:header", f" {self.title} "))
        lines.append(("", "\n"))
        
        if self.description:
            lines.append(("", f" {self.description}\n"))
        
        lines.append(("", "\n"))
        
        # Menu items
        for i, item in enumerate(self.items):
            if i == self.selected_index:
                prefix = " > "
                style_base = "class:selected"
            else:
                prefix = "   "
                style_base = ""
            
            name = item.get("name", item.get("id", "?"))
            desc = item.get("desc", "")
            badge = item.get("badge", "")
            extra = item.get("extra", "")
            
            # Format: prefix | name | description | extra | badge
            name_padded = f"{name:<12}"
            
            lines.append(("class:pointer", prefix))
            lines.append((f"{style_base} bold cyan" if i == self.selected_index else "cyan", name_padded))
            
            if desc:
                lines.append((f"{style_base} class:hint", " · "))
                lines.append((style_base, f"{desc:<40}"))
            
            if extra:
                lines.append((f"{style_base} class:hint", " · "))
                lines.append((f"{style_base} green", extra))
            
            if badge:
                badge_style = "class:selected-badge" if i == self.selected_index else "class:badge"
                lines.append((badge_style, f" {badge} "))
            
            lines.append(("", "\n"))
        
        lines.append(("", "\n"))
        lines.append(("class:hint", " ↑/↓ Navigate · Enter Confirm · Esc Cancel"))
        
        return lines
    
    async def run(self) -> Optional[str]:
        """Show the selection menu and return the selected item's ID."""
        kb = KeyBindings()
        result: Optional[str] = None
        
        @kb.add("up")
        @kb.add("k")  # Vim-style
        def _up(event):
            self.selected_index = (self.selected_index - 1) % len(self.items)
        
        @kb.add("down")
        @kb.add("j")  # Vim-style
        def _down(event):
            self.selected_index = (self.selected_index + 1) % len(self.items)
        
        @kb.add("enter")
        def _confirm(event):
            nonlocal result
            result = self.items[self.selected_index].get("id")
            event.app.exit()
        
        @kb.add("escape")
        @kb.add("c-c")
        @kb.add("c-q")
        def _cancel(event):
            event.app.exit()
        
        # Number shortcuts for quick selection (1-9)
        for num in range(1, min(10, len(self.items) + 1)):
            @kb.add(str(num))
            def _quick_select(event, idx=num-1):
                nonlocal result
                if idx < len(self.items):
                    result = self.items[idx].get("id")
                    event.app.exit()
        
        app = Application(
            layout=Layout(
                HSplit([
                    Window(
                        content=FormattedTextControl(text=self._get_formatted_text),
                        height=len(self.items) + 6,
                    )
                ])
            ),
            key_bindings=kb,
            style=STYLES,
            full_screen=False,
            mouse_support=True,
        )
        
        await app.run_async()
        return result


class DiffPreview:
    """
    Display file modifications as a diff preview.
    
    Features:
    - Syntax-highlighted diff display
    - Line numbers
    - Context lines around changes
    
    Usage:
        DiffPreview.show(original_content, new_content, filename)
    """
    
    @staticmethod
    def generate_diff(
        original: str,
        modified: str,
        filename: str = "file",
        context_lines: int = 3
    ) -> str:
        """Generate a unified diff between two strings."""
        import difflib
        
        original_lines = original.splitlines(keepends=True)
        modified_lines = modified.splitlines(keepends=True)
        
        diff = difflib.unified_diff(
            original_lines,
            modified_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            n=context_lines,
        )
        
        return "".join(diff)
    
    @staticmethod
    def show(
        original: str,
        modified: str,
        filename: str = "file",
        console: Optional[Console] = None
    ) -> None:
        """Display a diff preview to the console."""
        if console is None:
            console = Console()
        
        diff_text = DiffPreview.generate_diff(original, modified, filename)
        
        if not diff_text:
            console.print(f"[dim]No changes in {filename}[/dim]")
            return
        
        # Create styled diff output
        styled = Text()
        for line in diff_text.splitlines():
            if line.startswith("+++") or line.startswith("---"):
                styled.append(line + "\n", style="bold")
            elif line.startswith("@@"):
                styled.append(line + "\n", style=f"bold {COLORS['secondary']}")
            elif line.startswith("+"):
                styled.append(line + "\n", style=f"{COLORS['diff_add']}")
            elif line.startswith("-"):
                styled.append(line + "\n", style=f"{COLORS['diff_remove']}")
            else:
                styled.append(line + "\n", style=COLORS['diff_context'])
        
        console.print(Panel(
            styled,
            title=f"[bold]Changes to {filename}[/bold]",
            title_align="left",
            border_style=COLORS["primary"],
            box=ROUNDED,
        ))


class ThinkingPanel:
    """
    Display AI thinking process in a collapsible panel.
    
    Features:
    - Animated "thinking" header
    - Truncated preview with expand option
    - Purple accent color for distinction
    """
    
    def __init__(
        self,
        content: str,
        max_preview_lines: int = 5,
        expanded: bool = False
    ):
        self.content = content
        self.max_preview_lines = max_preview_lines
        self.expanded = expanded
    
    def render(self, console: Optional[Console] = None) -> Panel:
        """Render the thinking panel."""
        if console is None:
            console = Console()
        
        lines = self.content.splitlines()
        
        if not self.expanded and len(lines) > self.max_preview_lines:
            preview_lines = lines[:self.max_preview_lines]
            display_text = "\n".join(preview_lines)
            display_text += f"\n\n[dim]... ({len(lines) - self.max_preview_lines} more lines)[/dim]"
        else:
            display_text = self.content
        
        styled = Text(display_text, style=f"italic {COLORS['thinking']}")
        
        return Panel(
            styled,
            title="[bold purple]💭 Thinking[/bold purple]",
            title_align="left",
            border_style="purple",
            box=MINIMAL,
        )
    
    def show(self, console: Optional[Console] = None) -> None:
        """Display the thinking panel to the console."""
        if console is None:
            console = Console()
        console.print(self.render())


class ConfirmPrompt:
    """
    Simple yes/no confirmation prompt.
    
    Usage:
        confirmed = await ConfirmPrompt("Delete all files?").run()
    """
    
    def __init__(
        self,
        message: str,
        default: bool = False,
        yes_text: str = "Yes",
        no_text: str = "No"
    ):
        self.message = message
        self.default = default
        self.selected = 0 if default else 1
        self.options = [(yes_text, True), (no_text, False)]
    
    def _get_formatted_text(self) -> List[Tuple[str, str]]:
        lines = []
        lines.append(("", "\n"))
        lines.append(("class:approval-title", f" {self.message} "))
        lines.append(("", "\n\n "))
        
        for i, (label, _) in enumerate(self.options):
            if i == self.selected:
                lines.append(("class:approval-allow" if i == 0 else "class:approval-deny", f" {label} "))
            else:
                lines.append(("class:approval-button", f" {label} "))
            lines.append(("", "  "))
        
        lines.append(("", "\n\n"))
        lines.append(("class:hint", " ←/→ Navigate · Enter Confirm"))
        
        return lines
    
    async def run(self) -> bool:
        """Show the confirm prompt and return True for yes, False for no."""
        kb = KeyBindings()
        result = self.default
        
        @kb.add("left")
        @kb.add("right")
        @kb.add("h")
        @kb.add("l")
        def _toggle(event):
            self.selected = 1 - self.selected
        
        @kb.add("enter")
        def _confirm(event):
            nonlocal result
            result = self.options[self.selected][1]
            event.app.exit()
        
        @kb.add("escape")
        @kb.add("c-c")
        def _cancel(event):
            nonlocal result
            result = False
            event.app.exit()
        
        @kb.add("y")
        def _yes(event):
            nonlocal result
            result = True
            event.app.exit()
        
        @kb.add("n")
        def _no(event):
            nonlocal result
            result = False
            event.app.exit()
        
        app = Application(
            layout=Layout(
                HSplit([
                    Window(
                        content=FormattedTextControl(text=self._get_formatted_text),
                        height=5,
                    )
                ])
            ),
            key_bindings=kb,
            style=STYLES,
            full_screen=False,
            mouse_support=True,
        )
        
        await app.run_async()
        return result
