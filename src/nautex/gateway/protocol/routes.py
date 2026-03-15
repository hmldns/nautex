"""WebSocket route constants shared between utility and backend.

All agw.* routes used in GatewayWsEnvelope.route must be defined here.
Copy this file to the backend to keep routes in sync.
"""

# Utility → Backend (outbound from utility)
UTILITY_HEARTBEAT = "agw.utility.heartbeat"
UTILITY_PERMISSION_REQUEST = "agw.utility.permission_request"
UTILITY_SESSION_UPDATE = "agw.utility.session_update"
UTILITY_TELEMETRY = "agw.utility.telemetry"

# Frontend/Backend → Utility (inbound to utility)
FRONTEND_PERMISSION_RESPONSE = "agw.frontend.permission_response"
FRONTEND_EXECUTE_PROMPT = "agw.frontend.execute_prompt_strict"
FRONTEND_CANCEL_SESSION = "agw.frontend.cancel_session"
FRONTEND_SEARCH_REQUEST = "agw.frontend.search_request"
