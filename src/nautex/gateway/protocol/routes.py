"""WebSocket route constants shared between gateway node and backend.

All agw.* routes used in GatewayWsEnvelope.route must be defined here.
Copy this file to the backend to keep routes in sync.
"""

# Node → Backend (outbound from AGW node)
NODE_REGISTER = "agw.node.register"
NODE_SESSION_DECLARED = "agw.node.session_declared"
NODE_HEARTBEAT = "agw.node.heartbeat"
NODE_PERMISSION_REQUEST = "agw.node.permission_request"
NODE_SESSION_UPDATE = "agw.node.session_update"
NODE_TELEMETRY = "agw.node.telemetry"
NODE_AGENT_LIFECYCLE = "agw.node.agent_lifecycle"
NODE_AGENT_SETTING_CHANGE = "agw.node.agent_setting_change"

# Backend → Node (inbound to AGW node)
BACKEND_REGISTRATION_ACK = "agw.backend.registration_ack"
BACKEND_SESSION_ACKNOWLEDGED = "agw.backend.session_acknowledged"

# Backend → Node (commands)
BACKEND_SPAWN_AGENT = "agw.backend.spawn_agent"
BACKEND_STOP_AGENT = "agw.backend.stop_agent"
BACKEND_APPLY_SETTINGS = "agw.backend.apply_settings"

# Frontend/Backend → Node (inbound to AGW node)
FRONTEND_PERMISSION_RESPONSE = "agw.frontend.permission_response"
FRONTEND_EXECUTE_PROMPT = "agw.frontend.execute_prompt_strict"
FRONTEND_CANCEL_SESSION = "agw.frontend.cancel_session"
FRONTEND_SEARCH_REQUEST = "agw.frontend.search_request"
