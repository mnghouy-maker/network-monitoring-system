"""Aggregate router for API v1."""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    alerts,
    auth,
    devices,
    health,
    monitoring,
    telegram,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(devices.router)
api_router.include_router(monitoring.router)
api_router.include_router(alerts.router)
api_router.include_router(telegram.router)
