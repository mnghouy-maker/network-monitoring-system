"""AI troubleshooting assistant service.

Gathers live operational context (device/server inventory, latest metrics,
active alerts, health snapshots, latest backup metadata) and hands it to an
:class:`~app.ai.protocols.AIProvider` as grounding for each answer. The chat
history is persisted so conversations are resumable.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from app.ai.protocols import AIProvider, ChatTurn
from app.models.ai import AIMessage, AIMessageRole, AISession, AISubjectType
from app.repositories.ai import AIMessageRepository, AISessionRepository
from app.repositories.alert import AlertHistoryRepository
from app.repositories.backup import ConfigBackupRepository
from app.repositories.device import DeviceRepository
from app.repositories.metric import MetricRepository
from app.repositories.server import ServerHealthRepository, ServerRepository
from app.schemas.ai import AISessionCreate
from app.services.exceptions import (
    AIError,
    EntityNotFoundError,
    ServiceError,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are an expert network operations engineer embedded in a self-hosted "
    "NOC platform. You help operators diagnose and resolve issues with network "
    "devices (routers, switches, firewalls) and Linux servers. You are given "
    "live telemetry from the platform under 'CURRENT CONTEXT'. Ground every "
    "answer in that data: cite the specific metrics, alerts, or health values "
    "you relied on, call out what looks abnormal, and give concrete, ordered "
    "remediation steps. State your assumptions and, when the data is "
    "insufficient, say what additional information or command output you would "
    "need. Be concise and practical; prefer bullet points and short "
    "paragraphs over prose."
)


def _fmt(value: object, suffix: str = "") -> str:
    return "unknown" if value is None else f"{value}{suffix}"


class TroubleshootingService:
    """Create sessions, gather context and drive the LLM conversation."""

    def __init__(
        self,
        *,
        session_repo: AISessionRepository,
        message_repo: AIMessageRepository,
        provider: AIProvider,
        device_repo: DeviceRepository,
        metric_repo: MetricRepository,
        alert_repo: AlertHistoryRepository,
        server_repo: ServerRepository,
        server_health_repo: ServerHealthRepository,
        backup_repo: ConfigBackupRepository,
        model: str,
        max_tokens: int = 2048,
        max_history: int = 20,
    ) -> None:
        self._sessions = session_repo
        self._messages = message_repo
        self._provider = provider
        self._devices = device_repo
        self._metrics = metric_repo
        self._alerts = alert_repo
        self._servers = server_repo
        self._server_health = server_health_repo
        self._backups = backup_repo
        self._model = model
        self._max_tokens = max_tokens
        self._max_history = max_history

    @property
    def is_configured(self) -> bool:
        return self._provider.is_configured

    # --- sessions ------------------------------------------------------------
    async def create_session(self, payload: AISessionCreate) -> AISession:
        await self._validate_subject(payload.subject_type, payload.subject_id)
        title = payload.title or await self._default_title(
            payload.subject_type, payload.subject_id
        )
        session = AISession(
            title=title,
            subject_type=payload.subject_type,
            subject_id=payload.subject_id,
        )
        return await self._sessions.add(session)

    async def list_sessions(
        self, *, skip: int = 0, limit: int = 100
    ) -> list[AISession]:
        return await self._sessions.list(skip=skip, limit=limit)

    async def get_session(self, session_id: uuid.UUID) -> AISession:
        session = await self._sessions.get(session_id)
        if session is None:
            raise EntityNotFoundError(f"AI session {session_id} not found")
        return session

    async def list_messages(
        self, session_id: uuid.UUID
    ) -> list[AIMessage]:
        await self.get_session(session_id)
        return await self._messages.list_for_session(session_id)

    async def delete_session(self, session_id: uuid.UUID) -> None:
        await self._sessions.delete(await self.get_session(session_id))

    # --- chat ----------------------------------------------------------------
    async def send_message(
        self, session_id: uuid.UUID, content: str
    ) -> AIMessage:
        """Append a user turn, call the provider and persist its reply."""
        if not self._provider.is_configured:
            raise AIError("The AI assistant is not configured")

        session = await self.get_session(session_id)

        await self._messages.add(
            AIMessage(
                session_id=session.id,
                role=AIMessageRole.USER,
                content=content,
            )
        )

        history = await self._messages.list_for_session(session.id)
        turns = [
            ChatTurn(role=m.role.value, content=m.content)
            for m in history[-self._max_history :]
        ]
        context = await self._build_context(session)
        system = f"{_SYSTEM_PROMPT}\n\nCURRENT CONTEXT:\n{context}"

        completion = await self._provider.complete(
            system=system, messages=turns, max_tokens=self._max_tokens
        )

        reply = await self._messages.add(
            AIMessage(
                session_id=session.id,
                role=AIMessageRole.ASSISTANT,
                content=completion.text or "(no response)",
                model=completion.model,
                input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
            )
        )
        # Bump the session's updated_at so recent conversations sort first.
        await self._sessions.touch(session)
        return reply

    async def diagnose(
        self,
        subject_type: AISubjectType,
        subject_id: uuid.UUID | None,
        question: str | None,
    ) -> tuple[AISession, AIMessage]:
        """Open a scoped session and answer an initial diagnostic question."""
        session = await self.create_session(
            AISessionCreate(subject_type=subject_type, subject_id=subject_id)
        )
        prompt = question or self._default_question(subject_type)
        reply = await self.send_message(session.id, prompt)
        return session, reply

    # --- context gathering ---------------------------------------------------
    async def _build_context(self, session: AISession) -> str:
        try:
            if session.subject_type is AISubjectType.DEVICE and session.subject_id:
                return await self._device_context(session.subject_id)
            if session.subject_type is AISubjectType.SERVER and session.subject_id:
                return await self._server_context(session.subject_id)
            return await self._general_context()
        except Exception as exc:  # noqa: BLE001 - context is best-effort
            logger.warning("Failed to build AI context: %s", exc)
            return "Context is unavailable due to an internal error."

    async def _device_context(self, device_id: uuid.UUID) -> str:
        device = await self._devices.get(device_id)
        if device is None:
            return f"Device {device_id} no longer exists."
        lines = [
            "Subject: network device",
            f"- name: {device.name}",
            f"- hostname: {device.hostname}",
            f"- category: {device.category.value}",
            f"- vendor/model: {_fmt(device.vendor)}/{_fmt(device.model)}",
            f"- active: {device.is_active}",
        ]

        metric = await self._metrics.get_latest(device_id)
        if metric is None:
            lines.append("Latest metric: none recorded yet.")
        else:
            lines += [
                "Latest metric "
                f"({self._ago(metric.collected_at)}, source "
                f"{metric.source.value}):",
                f"- reachable: {metric.reachable}",
                f"- latency: {_fmt(metric.latency_ms, ' ms')}",
                f"- packet loss: {_fmt(metric.packet_loss_percent, '%')}",
                f"- cpu: {_fmt(metric.cpu_load_percent, '%')}",
                f"- memory: {_fmt(metric.memory_used_percent, '%')}",
                f"- uptime: {_fmt(metric.uptime_seconds, ' s')}",
            ]

        alerts = await self._alerts.list_history(
            device_id=device_id, limit=10
        )
        active = [a for a in alerts if a.is_active]
        if active:
            lines.append("Active alerts:")
            lines += [
                f"- [{a.severity.value}] {a.alert_type.value}: {a.message}"
                for a in active
            ]
        else:
            lines.append("Active alerts: none.")

        backup = await self._backups.get_latest_success(
            device_id, config_type=_running_config_type()
        )
        if backup is not None:
            lines.append(
                "Latest successful running-config backup: "
                f"{self._ago(backup.created_at)} "
                f"({_fmt(backup.size_bytes, ' bytes')})."
            )
        return "\n".join(lines)

    async def _server_context(self, server_id: uuid.UUID) -> str:
        server = await self._servers.get(server_id)
        if server is None:
            return f"Server {server_id} no longer exists."
        lines = [
            "Subject: server host",
            f"- name: {server.name}",
            f"- hostname: {server.hostname}",
            f"- monitor method: {server.monitor_method.value}",
            f"- active: {server.is_active}",
        ]
        check = await self._server_health.get_latest(server_id)
        if check is None:
            lines.append("Latest health check: none recorded yet.")
        else:
            lines += [
                f"Latest health check ({self._ago(check.collected_at)}):",
                f"- status: {check.status.value}",
                f"- reachable: {check.reachable}",
                f"- cpu: {_fmt(check.cpu_percent, '%')}",
                f"- memory: {_fmt(check.memory_percent, '%')}",
                f"- disk: {_fmt(check.disk_percent, '%')}",
                f"- load (1/5/15): {_fmt(check.load1)}/"
                f"{_fmt(check.load5)}/{_fmt(check.load15)}",
                f"- uptime: {_fmt(check.uptime_seconds, ' s')}",
            ]
            if check.error:
                lines.append(f"- last error: {check.error}")
        return "\n".join(lines)

    async def _general_context(self) -> str:
        devices = await self._devices.list(limit=500)
        servers = await self._servers.list(limit=500)
        active_alerts = await self._alerts.list_active(limit=25)
        lines = [
            "Subject: platform-wide overview",
            f"- devices tracked: {len(devices)}",
            f"- servers tracked: {len(servers)}",
            f"- active alerts: {len(active_alerts)}",
        ]
        if active_alerts:
            lines.append("Active alerts (most recent first):")
            lines += [
                f"- [{a.severity.value}] {a.alert_type.value}: {a.message}"
                for a in active_alerts[:15]
            ]
        return "\n".join(lines)

    # --- helpers -------------------------------------------------------------
    async def _validate_subject(
        self, subject_type: AISubjectType, subject_id: uuid.UUID | None
    ) -> None:
        if subject_type is AISubjectType.GENERAL:
            return
        if subject_id is None:
            raise ServiceError(
                f"subject_id is required for a {subject_type.value} session"
            )
        if subject_type is AISubjectType.DEVICE:
            if await self._devices.get(subject_id) is None:
                raise EntityNotFoundError(f"Device {subject_id} not found")
        elif subject_type is AISubjectType.SERVER:
            if await self._servers.get(subject_id) is None:
                raise EntityNotFoundError(f"Server {subject_id} not found")

    async def _default_title(
        self, subject_type: AISubjectType, subject_id: uuid.UUID | None
    ) -> str:
        if subject_type is AISubjectType.DEVICE and subject_id:
            device = await self._devices.get(subject_id)
            if device is not None:
                return f"Troubleshoot device {device.name}"
        if subject_type is AISubjectType.SERVER and subject_id:
            server = await self._servers.get(subject_id)
            if server is not None:
                return f"Troubleshoot server {server.name}"
        return "General troubleshooting"

    @staticmethod
    def _default_question(subject_type: AISubjectType) -> str:
        if subject_type is AISubjectType.DEVICE:
            return (
                "Assess this device's current health and connectivity. Is "
                "anything wrong, and what should I check or do next?"
            )
        if subject_type is AISubjectType.SERVER:
            return (
                "Assess this server's current health. Is anything wrong, and "
                "what should I investigate or do next?"
            )
        return (
            "Give me an overview of the current state of the network and any "
            "issues I should prioritize."
        )

    @staticmethod
    def _ago(when: datetime | None) -> str:
        if when is None:
            return "unknown time"
        return when.isoformat()


def _running_config_type():  # noqa: ANN202 - avoid import cycle at module top
    from app.models.backup import ConfigType

    return ConfigType.RUNNING
