import uuid
import logging

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import REGISTERED_AGENTS
from triage.models import StageResult, TriageRequest
from session import redis_store

logger = logging.getLogger(__name__)


async def evaluate(request: TriageRequest) -> StageResult:
    agent_info = REGISTERED_AGENTS.get(request.agent_id)
    if agent_info is None:
        return StageResult(
            stage=1,
            score=1.0,
            triggered=True,
            reason=f"Unregistered agent identity '{request.agent_id}'. No session will be established.",
            details={"agent_id": request.agent_id},
        )

    registered_role = agent_info["role"]
    if request.agent_role != registered_role:
        return StageResult(
            stage=1,
            score=1.0,
            triggered=True,
            reason=(
                f"Role spoofing detected. Agent '{request.agent_id}' claimed role "
                f"'{request.agent_role}' but is registered as '{registered_role}'."
            ),
            details={"claimed_role": request.agent_role, "registered_role": registered_role},
        )

    try:
        uuid.UUID(request.session_id)
    except ValueError:
        return StageResult(
            stage=1,
            score=1.0,
            triggered=True,
            reason=f"Invalid session_id format '{request.session_id}'. Must be a valid UUID.",
            details={"session_id": request.session_id},
        )

    redis_store.init_session(request.session_id)

    return StageResult(
        stage=1,
        score=0.0,
        triggered=False,
        reason="Agent identity verified. Session active.",
        details={"agent_id": request.agent_id, "role": registered_role, "session_id": request.session_id},
    )
