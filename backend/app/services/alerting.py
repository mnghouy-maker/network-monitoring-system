"""Alerting engine: evaluate metrics against rules and manage alert lifecycle.

The :class:`AlertEvaluator` is pure logic (no I/O) and therefore exhaustively
unit-testable. :class:`AlertingService` wires it to repositories and the
notifier: it persists firing/recovery transitions, deduplicates active alerts
(one open alert per device+type), and dispatches Telegram notifications.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.models.alert import (
    AlertAcknowledgement,
    AlertHistory,
    AlertRule,
    AlertSeverity,
    AlertStatus,
    AlertType,
)
from app.models.device import Device
from app.models.metric import DeviceMetric
from app.models.telegram import TelegramUser
from app.repositories.alert import (
    AlertAcknowledgementRepository,
    AlertHistoryRepository,
    AlertRuleRepository,
)
from app.repositories.device import DeviceRepository
from app.repositories.metric import MetricRepository
from app.schemas.alert import AlertRuleCreate, AlertRuleUpdate
from app.services.exceptions import AlertError, EntityNotFoundError
from app.services.notifier import AlertNotifier

logger = logging.getLogger(__name__)

# Alert types whose value is a percentage gauge compared with the threshold.
_GAUGE_TYPES = {
    AlertType.HIGH_CPU,
    AlertType.HIGH_MEMORY,
    AlertType.HIGH_DISK,
    AlertType.HIGH_INTERFACE_UTIL,
    AlertType.PACKET_LOSS,
}

_TYPE_LABEL = {
    AlertType.HIGH_CPU: "CPU load",
    AlertType.HIGH_MEMORY: "Memory usage",
    AlertType.HIGH_DISK: "Disk usage",
    AlertType.HIGH_INTERFACE_UTIL: "Interface utilization",
    AlertType.PACKET_LOSS: "Packet loss",
}


@dataclass(slots=True)
class AlertCondition:
    """Result of evaluating one rule against a device's metrics."""

    triggered: bool
    value: float | None
    threshold: float | None
    message: str


class AlertEvaluator:
    """Decides whether a rule's condition is met for a device's metrics."""

    def __init__(self, default_thresholds: dict[AlertType, float]) -> None:
        self._defaults = default_thresholds

    def evaluate(
        self,
        rule: AlertRule,
        device: Device,
        current: DeviceMetric | None,
        previous: DeviceMetric | None = None,
    ) -> AlertCondition:
        if rule.alert_type is AlertType.DEVICE_OFFLINE:
            return self._evaluate_offline(device, current)
        if rule.alert_type in _GAUGE_TYPES:
            return self._evaluate_gauge(rule, device, current, previous)
        # DEVICE_ONLINE (a recovery label) and anything else are not conditions.
        return AlertCondition(False, None, None, "")

    def _evaluate_offline(
        self, device: Device, current: DeviceMetric | None
    ) -> AlertCondition:
        if current is None:
            return AlertCondition(False, None, None, "")
        triggered = not current.reachable
        message = (
            f"{device.name} is not responding to ICMP ping."
            if triggered
            else ""
        )
        return AlertCondition(triggered, None, None, message)

    def _evaluate_gauge(
        self,
        rule: AlertRule,
        device: Device,
        current: DeviceMetric | None,
        previous: DeviceMetric | None,
    ) -> AlertCondition:
        value = self._extract_value(rule.alert_type, current, previous)
        threshold = (
            rule.threshold
            if rule.threshold is not None
            else self._defaults.get(rule.alert_type)
        )
        triggered = (
            value is not None and threshold is not None and value > threshold
        )
        message = ""
        if triggered:
            label = _TYPE_LABEL.get(rule.alert_type, rule.alert_type.value)
            message = (
                f"{label} on {device.name}: {value:.1f}% "
                f"(threshold {threshold:g}%)"
            )
        return AlertCondition(triggered, value, threshold, message)

    def _extract_value(
        self,
        alert_type: AlertType,
        current: DeviceMetric | None,
        previous: DeviceMetric | None,
    ) -> float | None:
        if current is None:
            return None
        if alert_type is AlertType.HIGH_CPU:
            return current.cpu_load_percent
        if alert_type is AlertType.HIGH_MEMORY:
            return current.memory_used_percent
        if alert_type is AlertType.PACKET_LOSS:
            return current.packet_loss_percent
        if alert_type is AlertType.HIGH_INTERFACE_UTIL:
            return self._interface_utilization(current, previous)
        # HIGH_DISK: no disk metric is collected yet, so there is no value to
        # compare; the rule stays inert until disk polling is added.
        return None

    @staticmethod
    def _interface_utilization(
        current: DeviceMetric, previous: DeviceMetric | None
    ) -> float | None:
        """Peak interface utilization (%) derived from two counter snapshots."""
        if previous is None:
            return None
        seconds = (current.collected_at - previous.collected_at).total_seconds()
        if seconds <= 0:
            return None

        prev_by_key = {
            (iface.if_index if iface.if_index is not None else iface.name): iface
            for iface in previous.interfaces
        }
        best: float | None = None
        for cur in current.interfaces:
            key = cur.if_index if cur.if_index is not None else cur.name
            prev = prev_by_key.get(key)
            if prev is None or not cur.speed_bps:
                continue
            for cur_octets, prev_octets in (
                (cur.in_octets, prev.in_octets),
                (cur.out_octets, prev.out_octets),
            ):
                if cur_octets is None or prev_octets is None:
                    continue
                delta = cur_octets - prev_octets
                if delta < 0:  # counter reset/wrap — skip
                    continue
                util = (delta * 8) / seconds / cur.speed_bps * 100
                if best is None or util > best:
                    best = util
        return best


class AlertingService:
    """Evaluates devices, persists alert transitions, and notifies."""

    def __init__(
        self,
        rule_repo: AlertRuleRepository,
        history_repo: AlertHistoryRepository,
        ack_repo: AlertAcknowledgementRepository,
        device_repo: DeviceRepository,
        metric_repo: MetricRepository,
        notifier: AlertNotifier,
        default_thresholds: dict[AlertType, float],
    ) -> None:
        self._rules = rule_repo
        self._history = history_repo
        self._acks = ack_repo
        self._devices = device_repo
        self._metrics = metric_repo
        self._notifier = notifier
        self._evaluator = AlertEvaluator(default_thresholds)

    async def evaluate_device(self, device: Device) -> list[AlertHistory]:
        """Evaluate all applicable rules for ``device`` and apply transitions."""
        snapshots = await self._metrics.list_history(device.id, limit=2)
        current = snapshots[0] if snapshots else None
        previous = snapshots[1] if len(snapshots) > 1 else None

        changed: list[AlertHistory] = []
        for rule in await self._rules.list_enabled_for_device(device.id):
            condition = self._evaluator.evaluate(
                rule, device, current, previous
            )
            existing = await self._history.get_active(
                device.id, rule.alert_type
            )

            if condition.triggered and existing is None:
                changed.append(await self._fire(rule, device, condition))
            elif not condition.triggered and existing is not None:
                changed.append(await self._resolve(existing, device))
            # Otherwise: already firing (dedup) or still clear — no change.
        return changed

    async def evaluate_device_by_id(
        self, device_id: uuid.UUID
    ) -> list[AlertHistory]:
        device = await self._devices.get(device_id)
        if device is None:
            raise EntityNotFoundError(f"Device {device_id} not found")
        return await self.evaluate_device(device)

    async def evaluate_all_active(self) -> list[AlertHistory]:
        changed: list[AlertHistory] = []
        for device in await self._devices.list_active():
            try:
                changed.extend(await self.evaluate_device(device))
            except Exception as exc:  # noqa: BLE001 - isolate per-device failures
                logger.warning("Alert evaluation failed for %s: %s", device.name, exc)
        return changed

    async def _fire(
        self, rule: AlertRule, device: Device, condition: AlertCondition
    ) -> AlertHistory:
        alert = AlertHistory(
            device_id=device.id,
            rule_id=rule.id,
            alert_type=rule.alert_type,
            severity=rule.severity,
            status=AlertStatus.FIRING,
            message=condition.message,
            value=condition.value,
            threshold=condition.threshold,
        )
        await self._history.add(alert)
        await self._notifier.notify_alert(alert, device)
        logger.info("Alert FIRING: %s on %s", rule.alert_type, device.name)
        return alert

    async def _resolve(
        self, alert: AlertHistory, device: Device
    ) -> AlertHistory:
        alert.status = AlertStatus.RESOLVED
        alert.resolved_at = datetime.now(UTC)
        await self._history.update(alert)
        await self._notifier.notify_recovery(alert, device)
        logger.info("Alert RESOLVED: %s on %s", alert.alert_type, device.name)
        return alert

    async def acknowledge(
        self,
        alert_id: uuid.UUID,
        *,
        telegram_user: TelegramUser | None = None,
        note: str | None = None,
    ) -> AlertHistory:
        alert = await self._history.get(alert_id)
        if alert is None:
            raise EntityNotFoundError(f"Alert {alert_id} not found")
        if alert.status is AlertStatus.RESOLVED:
            raise AlertError("Cannot acknowledge a resolved alert")

        alert.status = AlertStatus.ACKNOWLEDGED
        await self._history.update(alert)
        await self._acks.add(
            AlertAcknowledgement(
                alert_id=alert.id,
                telegram_user_id=(
                    telegram_user.id if telegram_user is not None else None
                ),
                note=note,
            )
        )
        return alert

    async def list_active(
        self, *, severity: AlertSeverity | None = None
    ) -> list[AlertHistory]:
        return await self._history.list_active(severity=severity)

    async def list_history(
        self,
        *,
        device_id: uuid.UUID | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[AlertHistory]:
        return await self._history.list_history(
            device_id=device_id, skip=skip, limit=limit
        )

    # --- rule management --------------------------------------------------
    async def list_rules(
        self, *, skip: int = 0, limit: int = 100
    ) -> list[AlertRule]:
        return await self._rules.list(skip=skip, limit=limit)

    async def get_rule(self, rule_id: uuid.UUID) -> AlertRule:
        rule = await self._rules.get(rule_id)
        if rule is None:
            raise EntityNotFoundError(f"Alert rule {rule_id} not found")
        return rule

    async def create_rule(self, payload: AlertRuleCreate) -> AlertRule:
        if (
            payload.device_id is not None
            and await self._devices.get(payload.device_id) is None
        ):
            raise EntityNotFoundError(
                f"Device {payload.device_id} not found"
            )
        rule = AlertRule(**payload.model_dump())
        return await self._rules.add(rule)

    async def update_rule(
        self, rule_id: uuid.UUID, payload: AlertRuleUpdate
    ) -> AlertRule:
        rule = await self.get_rule(rule_id)
        data = payload.model_dump(exclude_unset=True)
        if (
            data.get("device_id") is not None
            and await self._devices.get(data["device_id"]) is None
        ):
            raise EntityNotFoundError(f"Device {data['device_id']} not found")
        for field, value in data.items():
            setattr(rule, field, value)
        return await self._rules.update(rule)

    async def delete_rule(self, rule_id: uuid.UUID) -> None:
        rule = await self.get_rule(rule_id)
        await self._rules.delete(rule)
