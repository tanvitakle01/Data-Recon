"""Chat/assistant API: one turn per request, but no longer stateless overall —
run bindings and pending confirmations live server-side, keyed by the
existing authenticated session (see ``chat_assistant.session_store`` /
``chat_assistant.confirmation_store``), while attachment-resolution progress
(``state``) still round-trips through the frontend exactly as before.
"""

from __future__ import annotations

import json
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from backend.auth.dependencies import get_current_session
from backend.auth.sessions import SessionInfo
from backend.recon_engine.chat_assistant.orchestrator import handle_message

router = APIRouter(prefix="/api/chat", tags=["chat-assistant"])


@router.post("/message")
async def post_chat_message(
    message: str = Form(""),
    state: str = Form("{}"),
    attachments: Optional[List[UploadFile]] = File(None),
    session: SessionInfo = Depends(get_current_session),
) -> dict[str, Any]:
    try:
        parsed_state = json.loads(state) if state else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid state JSON.")

    new_attachments: list[tuple[str, bytes]] = []
    for upload in attachments or []:
        content = await upload.read()
        if content:
            new_attachments.append((upload.filename or "attachment", content))

    result = handle_message(
        message=message, new_attachments=new_attachments, state=parsed_state, session_id=session.session_id
    )
    return result
