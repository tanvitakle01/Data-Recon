"""Chat/assistant API: one stateless endpoint per turn.

No server-side chat session store — the frontend persists ``state`` (see
``chat_assistant.orchestrator``) and resends it every turn, consistent with
the rest of this codebase's stateless routes (e.g. ``reconcile.py``'s
in-memory ``_FILE_STORE`` keyed by opaque id, not a session).
"""

from __future__ import annotations

import json
from typing import Any, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.recon_engine.chat_assistant.orchestrator import handle_message

router = APIRouter(prefix="/api/chat", tags=["chat-assistant"])


@router.post("/message")
async def post_chat_message(
    message: str = Form(""),
    state: str = Form("{}"),
    attachments: Optional[List[UploadFile]] = File(None),
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

    result = handle_message(message=message, new_attachments=new_attachments, state=parsed_state)
    return result
