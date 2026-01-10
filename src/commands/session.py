"""
Session Command Handlers

Handles session-related commands:
- /session - Show current session info
- /reset - Clear session and context
- /resume - Resume a previous session
- /fork - Fork current session
- /sessions - List recent sessions
"""

from rich.table import Table
from rich.box import ROUNDED

from .base import CommandHandler, CommandResult, AppState
from src.ui.components import SelectionMenu
from src.ui.styles import COLORS


class SessionHandler(CommandHandler):
    """Handles /session command - show current session info."""
    
    commands = ["/session"]
    
    async def handle(self, command: str, arg: str) -> CommandResult:
        sid = self.state.session_manager.get_current_session_id()
        info = self.state.session_manager.get_session_info(sid) if sid else None
        
        if info:
            self.console.print(f"[cyan]Session:[/cyan] {sid}")
            self.console.print(f"[cyan]Name:[/cyan] {info.name or '(unnamed)'}")
            self.console.print(f"[cyan]Messages:[/cyan] {info.message_count}")
        else:
            self.console.print(f"[cyan]Session:[/cyan] {sid or '(none)'}")
        
        return CommandResult.success()


class ResetHandler(CommandHandler):
    """Handles /reset command - clear session and context."""
    
    commands = ["/reset"]
    
    async def handle(self, command: str, arg: str) -> CommandResult:
        self.state.session_manager.clear_current_session()
        self.state.context_manager.clear()
        self.console.print(f"[{COLORS['success']}]✓ Session and context cleared[/{COLORS['success']}]")
        return CommandResult.success()


class ResumeHandler(CommandHandler):
    """Handles /resume command - resume a previous session."""
    
    commands = ["/resume"]
    
    async def handle(self, command: str, arg: str) -> CommandResult:
        if arg:
            self.state.resume_session_id = arg.strip()
            self.state.session_manager.set_current_session_id(self.state.resume_session_id)
            self._show_resume_info(self.state.resume_session_id)
        else:
            # Show list of sessions
            sessions = self.state.session_manager.list_sessions(limit=10)
            if sessions:
                items = []
                for sess in sessions:
                    last_used = sess.last_used.strftime("%m-%d %H:%M") if sess.last_used else "?"
                    # Check transcript for actual message count
                    msg_count = sess.message_count
                    if self.state.session_transcript:
                        transcript_count = self.state.session_transcript.get_message_count(sess.session_id)
                        if transcript_count > 0:
                            msg_count = transcript_count
                    items.append({
                        "id": sess.session_id,
                        "name": sess.name or "(unnamed)",
                        "desc": sess.session_id[:24] + ("..." if len(sess.session_id) > 24 else ""),
                        "extra": f"messages: {msg_count}",
                        "badge": last_used,
                    })
                menu = SelectionMenu(
                    title="Resume Session",
                    items=items,
                    description="Select a session to resume (↑/↓ + Enter).",
                    current_value=self.state.session_manager.get_current_session_id(),
                )
                selected_id = await menu.run()
                if selected_id:
                    self.state.resume_session_id = selected_id
                    self.state.session_manager.set_current_session_id(selected_id)
                    self._show_resume_info(selected_id)
                else:
                    self.console.print(f"[{COLORS['muted']}]Cancelled[/{COLORS['muted']}]")
            else:
                self.console.print(f"[{COLORS['muted']}]No sessions found[/{COLORS['muted']}]")
        
        return CommandResult.success()
    
    def _show_resume_info(self, session_id: str) -> None:
        """Show resume confirmation and transcript preview."""
        self.console.print(f"[{COLORS['success']}]✓ Resuming session: {session_id}[/{COLORS['success']}]")
        
        # Show transcript preview if available
        if self.state.session_transcript and self.state.session_transcript.transcript_exists(session_id):
            messages = self.state.session_transcript.load_messages(session_id)
            if messages:
                self.console.print(f"[{COLORS['muted']}]  → Loaded {len(messages)} messages from history[/{COLORS['muted']}]")
                # Show last message as preview
                if len(messages) > 0:
                    preview = messages[-1].content[:50] + "..." if len(messages[-1].content) > 50 else messages[-1].content
                    self.console.print(f"[{COLORS['muted']}]  Last: {messages[-1].role}: {preview}[/{COLORS['muted']}]")


class ForkHandler(CommandHandler):
    """Handles /fork command - fork current session."""
    
    commands = ["/fork"]
    
    async def handle(self, command: str, arg: str) -> CommandResult:
        forked_id = self.state.session_manager.fork_session()
        self.console.print(f"[{COLORS['success']}]✓ Forked to new session: {forked_id}[/{COLORS['success']}]")
        self.state.resume_session_id = forked_id
        return CommandResult.success()


class SessionsHandler(CommandHandler):
    """Handles /sessions command - list recent sessions."""
    
    commands = ["/sessions"]
    
    async def handle(self, command: str, arg: str) -> CommandResult:
        sessions = self.state.session_manager.list_sessions(limit=10)
        if sessions:
            from tui_agent import render_session_table
            self.console.print(render_session_table(sessions, "Recent Sessions"))
        else:
            self.console.print(f"[{COLORS['muted']}]No sessions found[/{COLORS['muted']}]")
        
        return CommandResult.success()


# Export all handlers
SESSION_HANDLERS = [
    SessionHandler,
    ResetHandler,
    ResumeHandler,
    ForkHandler,
    SessionsHandler,
]
