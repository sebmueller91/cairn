"""The in-app agent (ADR 0017): conversations, and the apply/reject step
that turns a proposal into ledger changes. Applying is the only write
path here, and it is a person's click, never the agent's own call."""

import json
import threading
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.agent_service import (
    AgentNotConfigured,
    AgentUpstreamError,
    load_messages,
    run_turn,
)
from app.agent_tools import ProposalInvalid, apply_changes
from app.auth import get_scope, require_write_scope
from app.config import get_settings
from app.database import get_db
from app.models import AgentConversation, AgentProposal
from app.schemas import (
    AgentChanges,
    AgentConversationRead,
    AgentMessageCreate,
    AgentProposalRead,
    AgentStatus,
    AgentTranscriptItem,
)

router = APIRouter(prefix="/api/agent", tags=["agent"])

# Applying a proposal refreshes the snapshots right away rather than at
# 23:00, so balances move when the user expects them to. Serialized: two
# overlapping rebuilds would fight over the same table.
_rebuild_lock = threading.Lock()


def _rebuild_snapshots() -> None:
    from app.scheduler import run_snapshot_rebuild_job

    with _rebuild_lock:
        run_snapshot_rebuild_job()


def _reject(code: str, params: dict | None = None, status_code: int = 422):
    raise HTTPException(status_code=status_code, detail={"code": code, "params": params or {}})


def _get_conversation(db: Session, conversation_id: int) -> AgentConversation:
    conversation = db.get(AgentConversation, conversation_id)
    if conversation is None:
        _reject("conversation_not_found", {"id": conversation_id}, status.HTTP_404_NOT_FOUND)
    return conversation


def _proposal_read(p: AgentProposal) -> AgentProposalRead:
    return AgentProposalRead(
        id=p.id,
        summary=p.summary,
        status=p.status,
        preview=json.loads(p.preview_json),
        error=json.loads(p.error_json) if p.error_json else None,
        import_batch_id=p.import_batch_id,
    )


def _transcript(db: Session, conversation: AgentConversation) -> list[AgentTranscriptItem]:
    proposals = {
        p.tool_use_id: p
        for p in db.query(AgentProposal).filter(AgentProposal.conversation_id == conversation.id)
    }
    items: list[AgentTranscriptItem] = []
    for message in load_messages(conversation):
        blocks = message["content"]
        if isinstance(blocks, str):
            blocks = [{"type": "text", "text": blocks}]
        if message["role"] == "user":
            texts = [
                b["text"] for b in blocks
                if b["type"] == "text" and not b["text"].startswith("[App notice")
            ]
            images = sum(1 for b in blocks if b["type"] == "image")
            if texts or images:
                items.append(AgentTranscriptItem(role="user", text="\n".join(texts), image_count=images))
            continue
        for b in blocks:
            if b["type"] == "text" and b["text"].strip():
                items.append(AgentTranscriptItem(role="assistant", text=b["text"]))
            elif b["type"] == "tool_use" and b["id"] in proposals:
                items.append(
                    AgentTranscriptItem(
                        role="assistant", text="", proposal=_proposal_read(proposals[b["id"]])
                    )
                )
    return items


def _read(db: Session, conversation: AgentConversation, with_items: bool = True) -> AgentConversationRead:
    return AgentConversationRead(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        input_tokens=conversation.input_tokens,
        output_tokens=conversation.output_tokens,
        items=_transcript(db, conversation) if with_items else [],
    )


@router.get("/status", response_model=AgentStatus)
def agent_status(_scope=Depends(get_scope)) -> AgentStatus:
    settings = get_settings()
    return AgentStatus(configured=bool(settings.anthropic_api_key), model=settings.agent_model)


@router.get("/conversations", response_model=list[AgentConversationRead])
def list_conversations(db: Session = Depends(get_db), _scope=Depends(get_scope)):
    rows = db.query(AgentConversation).order_by(AgentConversation.id.desc()).limit(50)
    return [_read(db, c, with_items=False) for c in rows]


@router.post("/conversations", response_model=AgentConversationRead, status_code=201)
def create_conversation(db: Session = Depends(get_db), _scope=Depends(require_write_scope)):
    conversation = AgentConversation(messages_json="[]", input_tokens=0, output_tokens=0)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return _read(db, conversation)


@router.get("/conversations/{conversation_id}", response_model=AgentConversationRead)
def get_conversation(
    conversation_id: int, db: Session = Depends(get_db), _scope=Depends(get_scope)
):
    return _read(db, _get_conversation(db, conversation_id))


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: int, db: Session = Depends(get_db), _scope=Depends(require_write_scope)
) -> None:
    conversation = _get_conversation(db, conversation_id)
    db.query(AgentProposal).filter(AgentProposal.conversation_id == conversation.id).delete()
    db.delete(conversation)
    db.commit()


@router.post("/conversations/{conversation_id}/messages", response_model=AgentConversationRead)
def send_message(
    conversation_id: int,
    body: AgentMessageCreate,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
):
    conversation = _get_conversation(db, conversation_id)
    if not body.text.strip() and not body.images:
        _reject("empty_message")
    try:
        run_turn(db, conversation, body.text, body.images)
    except AgentNotConfigured:
        _reject("agent_not_configured", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    except AgentUpstreamError as e:
        db.commit()  # keep the user's message; the history is still valid
        _reject(e.code, e.params, status.HTTP_502_BAD_GATEWAY)
    db.refresh(conversation)
    return _read(db, conversation)


def _pending_proposal(db: Session, proposal_id: int) -> AgentProposal:
    proposal = db.get(AgentProposal, proposal_id)
    if proposal is None:
        _reject("proposal_not_found", {"id": proposal_id}, status.HTTP_404_NOT_FOUND)
    if proposal.status != "pending":
        _reject("proposal_already_decided", {"status": proposal.status}, status.HTTP_409_CONFLICT)
    return proposal


@router.post("/proposals/{proposal_id}/apply", response_model=AgentProposalRead)
def apply_proposal(
    proposal_id: int,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
):
    proposal = _pending_proposal(db, proposal_id)
    stored = json.loads(proposal.changes_json)
    external_ids = stored.pop("external_ids")
    changes = AgentChanges.model_validate(stored)
    try:
        batch_id, preview = apply_changes(
            db, changes, external_ids, f"agent proposal {proposal.id}: {proposal.summary}"
        )
    except ProposalInvalid as e:
        # The ledger moved since the proposal was made. Nothing written;
        # the proposal stays pending with the reason attached.
        db.rollback()
        proposal = db.get(AgentProposal, proposal_id)
        proposal.error_json = json.dumps(e.error, default=str)
        db.commit()
        _reject(e.error["code"], e.error.get("params"))
    proposal.status = "applied"
    proposal.import_batch_id = batch_id
    proposal.preview_json = json.dumps(preview, default=str)
    proposal.error_json = None
    proposal.decided_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    background.add_task(_rebuild_snapshots)
    return _proposal_read(proposal)


@router.post("/proposals/{proposal_id}/reject", response_model=AgentProposalRead)
def reject_proposal(
    proposal_id: int, db: Session = Depends(get_db), _scope=Depends(require_write_scope)
):
    proposal = _pending_proposal(db, proposal_id)
    proposal.status = "rejected"
    proposal.decided_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    return _proposal_read(proposal)
