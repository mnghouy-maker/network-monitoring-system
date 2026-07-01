"""Alerting schemas (request/response contracts)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.alert import AlertSeverity, AlertStatus, AlertType


class AlertRuleBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    alert_type: AlertType
    severity: AlertSeverity = AlertSeverity.WARNING
    threshold: float | None = None
    device_id: uuid.UUID | None = None
    is_enabled: bool = True


class AlertRuleCreate(AlertRuleBase):
    """Payload for creating an alert rule."""


class AlertRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    alert_type: AlertType | None = None
    severity: AlertSeverity | None = None
    threshold: float | None = None
    device_id: uuid.UUID | None = None
    is_enabled: bool | None = None


class AlertRuleOut(AlertRuleBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class AlertHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_id: uuid.UUID
    rule_id: uuid.UUID | None
    alert_type: AlertType
    severity: AlertSeverity
    status: AlertStatus
    message: str
    value: float | None
    threshold: float | None
    triggered_at: datetime
    resolved_at: datetime | None


class AlertAcknowledgeRequest(BaseModel):
    """Body for acknowledging an alert via the REST API."""

    note: str | None = Field(default=None, max_length=1000)
