"""CalmLab: how you work with coding agents, measured on your own machine.

Records when Claude Code turns start and end, and how big prompts and replies were, as
counts only. No prompt, reply, path, file name, tool name or tool output is ever stored.
"""

__version__ = "0.2.0"

EVENT_KINDS = (
    "session_start",
    "prompt_submit",
    "turn_start",
    "turn_end",
    "tool_fail",
    "needs_input",
    "session_end",
)

CHECKIN_TRIGGERS = ("end_of_day", "long_session", "self")
