"""AI troubleshooting assistant schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.ai import AIMessageRole, AISubjectType


class AISessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    subject_type: AISubjectType = AISubjectType.GENERAL
    # Required when ``subject_type`` is device or server.
    subject_id: uuid.UUID | None = None


class AIMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    role: AIMessageRole
    content: str
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    created_at: datetime


class AISessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    subject_type: AISubjectType
    subject_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class AISessionDetailOut(AISessionOut):
    messages: list[AIMessageOut] = Field(default_factory=list)


class AIChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class AIDiagnoseRequest(BaseModel):
    """One-shot diagnosis request scoped to a device or server."""

    subject_type: AISubjectType = AISubjectType.GENERAL
    subject_id: uuid.UUID | None = None
    question: str | None = Field(default=None, max_length=8000)
