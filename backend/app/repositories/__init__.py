"""Repository layer: encapsulates all database access."""

from app.repositories.device import DeviceRepository
from app.repositories.metric import MetricRepository
from app.repositories.user import UserRepository

__all__ = ["UserRepository", "DeviceRepository", "MetricRepository"]
