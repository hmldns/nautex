"""Per-agent adapter — inherits common ACP base.

Agent-specific quirks can be overridden here.
"""

from ..acp_adapter import ACPAgentAdapter
class CursorAdapter(ACPAgentAdapter): pass
