"""
Styles and Colors for BENEDICTJUN TUI
Claude Code-inspired color palette and styling constants
"""

from prompt_toolkit.styles import Style as PromptStyle

# Claude Code-inspired color palette
COLORS = {
    # Primary colors
    "primary": "#D97757",       # Claude Code signature orange border
    "secondary": "#5B89F7",     # Blue for commands/links
    "accent": "#3B8EEA",        # Bright blue accent
    
    # Status colors
    "success": "#4EC9A1",       # Green for success
    "warning": "#FFC107",       # Yellow for warnings
    "error": "#F14C4C",         # Red for errors
    
    # Text colors
    "text": "#E4E4E4",          # Primary text
    "muted": "#666666",         # Muted/secondary text
    "dim": "#444444",           # Very dim text
    
    # Background colors
    "bg": "#000000",            # Terminal background
    "bg_elevated": "#1a1a2e",   # Elevated surface
    "bg_hover": "#333333",      # Hover state
    "bg_selected": "#2d2d2d",   # Selected item
    
    # Special colors
    "thinking": "#9B59B6",      # Purple for thinking
    "diff_add": "#2EA043",      # Diff addition
    "diff_remove": "#CF222E",   # Diff removal
    "diff_context": "#8B949E",  # Diff context
    
    # Approval prompt colors
    "allow": "#4EC9A1",         # Allow button
    "always": "#5B89F7",        # Always allow button
    "deny": "#F14C4C",          # Deny button
}

# Prompt toolkit styles for interactive components
STYLES = PromptStyle.from_dict({
    # Input prompt
    "prompt": f"bold {COLORS['text']}",
    "bottom-toolbar": f"bg:{COLORS['bg_elevated']} {COLORS['muted']}",
    
    # Completion menu
    "completion-menu": f"bg:{COLORS['bg_hover']} #eeeeee",
    "completion-menu.completion": f"bg:{COLORS['bg_hover']} #eeeeee",
    "completion-menu.completion.current": f"bg:{COLORS['primary']} #000000",
    
    # Scrollbar
    "scrollbar.background": "bg:#222222",
    "scrollbar.button": "bg:#777777",
    
    # Selection menu
    "header": f"bg:{COLORS['accent']} #ffffff bold",
    "selected": f"bg:{COLORS['bg_selected']}",
    "pointer": f"fg:{COLORS['accent']} bold",
    "badge": f"bg:{COLORS['primary']} #000000",
    "selected-badge": f"bg:{COLORS['primary']} #ffffff bold",
    "hint": f"fg:{COLORS['muted']}",
    
    # Approval prompt
    "approval-title": f"bold {COLORS['warning']}",
    "approval-tool": f"bold {COLORS['secondary']}",
    "approval-button": f"bg:{COLORS['bg_hover']} {COLORS['text']}",
    "approval-button-selected": f"bg:{COLORS['primary']} #000000 bold",
    "approval-allow": f"bg:{COLORS['allow']} #000000 bold",
    "approval-always": f"bg:{COLORS['always']} #000000 bold",
    "approval-deny": f"bg:{COLORS['deny']} #ffffff bold",
})

# Box drawing characters for Claude Code style
BOX_CHARS = {
    "top_left": "╭",
    "top_right": "╮",
    "bottom_left": "╰",
    "bottom_right": "╯",
    "horizontal": "─",
    "vertical": "│",
    "cross": "┼",
    "t_down": "┬",
    "t_up": "┴",
    "t_right": "├",
    "t_left": "┤",
}

# Spinner styles
SPINNER_FRAMES = {
    "dots": ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
    "line": ["—", "\\", "|", "/"],
    "arc": ["◜", "◠", "◝", "◞", "◡", "◟"],
    "bouncing": ["⠁", "⠂", "⠄", "⡀", "⢀", "⠠", "⠐", "⠈"],
}
