from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.llm import LLMError
from app.models import ChatMessage, ChatSession, User
from app.ollama import OllamaClient
from app.user_auth import get_current_user

router = APIRouter(prefix="/chat", tags=["chat"])

SYSTEM_PROMPT = (
    "You are Forge, a helpful AI coding assistant. Be concise and practical. "
    "You do not have shell access in chat mode; for repository tasks, tell the user to use Agent mode."
)


class SessionRead(BaseModel):
    id: int
    title: str


class MessageRead(BaseModel):
    id: int
    role: str
    content: str


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    session_id: int | None = None


class SendMessageResponse(BaseModel):
    session: SessionRead
    messages: list[MessageRead]


def _session_for_user(db: Session, user: User, session_id: int) -> ChatSession:
    session = db.get(ChatSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Chat not found")
    return session


@router.get("/sessions", response_model=list[SessionRead])
def list_sessions(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[SessionRead]:
    rows = db.scalars(
        select(ChatSession).where(ChatSession.user_id == user.id).order_by(ChatSession.updated_at.desc())
    ).all()
    return [SessionRead(id=row.id, title=row.title) for row in rows]


@router.post("/sessions", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
def create_session(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> SessionRead:
    session = ChatSession(user_id=user.id, title="New chat")
    db.add(session)
    db.commit()
    db.refresh(session)
    return SessionRead(id=session.id, title=session.title)


@router.get("/sessions/{session_id}/messages", response_model=list[MessageRead])
def list_messages(
    session_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[MessageRead]:
    _session_for_user(db, user, session_id)
    rows = db.scalars(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id.asc())
    ).all()
    return [MessageRead(id=row.id, role=row.role, content=row.content) for row in rows]


@router.post("/messages", response_model=SendMessageResponse)
async def send_message(
    request: SendMessageRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SendMessageResponse:
    if request.session_id is None:
        session = ChatSession(user_id=user.id, title=request.content.strip()[:80] or "New chat")
        db.add(session)
        db.flush()
    else:
        session = _session_for_user(db, user, request.session_id)
        if session.title == "New chat":
            session.title = request.content.strip()[:80] or "New chat"

    user_message = ChatMessage(session_id=session.id, role="user", content=request.content.strip())
    db.add(user_message)
    db.flush()

    history = db.scalars(
        select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.id.asc())
    ).all()
    # Keep a single system message, then alternating user/assistant turns.
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for row in history[-24:]:
        role = row.role if row.role in {"user", "assistant"} else "user"
        messages.append({"role": role, "content": row.content[:8_000]})

    try:
        payload = await OllamaClient(settings).chat(settings.ollama_model, messages)
        assistant_text = str(payload["message"].get("content") or "").strip()
        if not assistant_text:
            assistant_text = "I could not generate a reply. Check that Ollama is running and the model is pulled."
    except LLMError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    assistant_message = ChatMessage(session_id=session.id, role="assistant", content=assistant_text)
    db.add(assistant_message)
    db.commit()
    db.refresh(session)

    rows = db.scalars(
        select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.id.asc())
    ).all()
    return SendMessageResponse(
        session=SessionRead(id=session.id, title=session.title),
        messages=[MessageRead(id=row.id, role=row.role, content=row.content) for row in rows],
    )
