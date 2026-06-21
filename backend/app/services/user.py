"""User service: business rules for managing users."""

import uuid

from app.core.security import hash_password
from app.models.user import User, UserRole
from app.repositories.user import UserRepository
from app.schemas.user import UserCreate, UserUpdate
from app.services.exceptions import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
)


class UserService:
    """Encapsulates user lifecycle operations."""

    def __init__(self, repository: UserRepository) -> None:
        self._repo = repository

    async def get(self, user_id: uuid.UUID) -> User:
        user = await self._repo.get(user_id)
        if user is None:
            raise EntityNotFoundError(f"User {user_id} not found")
        return user

    async def list(self, skip: int = 0, limit: int = 100) -> list[User]:
        return await self._repo.list(skip=skip, limit=limit)

    async def create(self, payload: UserCreate) -> User:
        if await self._repo.get_by_email(payload.email):
            raise EntityAlreadyExistsError("Email already registered")
        if await self._repo.get_by_username(payload.username):
            raise EntityAlreadyExistsError("Username already taken")

        user = User(
            email=payload.email,
            username=payload.username,
            full_name=payload.full_name,
            role=payload.role,
            is_active=payload.is_active,
            hashed_password=hash_password(payload.password),
        )
        return await self._repo.add(user)

    async def update(self, user_id: uuid.UUID, payload: UserUpdate) -> User:
        user = await self.get(user_id)
        data = payload.model_dump(exclude_unset=True)

        if "email" in data and data["email"] != user.email:
            if await self._repo.get_by_email(data["email"]):
                raise EntityAlreadyExistsError("Email already registered")
        if "username" in data and data["username"] != user.username:
            if await self._repo.get_by_username(data["username"]):
                raise EntityAlreadyExistsError("Username already taken")

        if "password" in data:
            user.hashed_password = hash_password(data.pop("password"))

        for field, value in data.items():
            setattr(user, field, value)

        return await self._repo.update(user)

    async def delete(self, user_id: uuid.UUID) -> None:
        user = await self.get(user_id)
        await self._repo.delete(user)

    async def ensure_first_admin(
        self, email: str, username: str, password: str
    ) -> User | None:
        """Create the bootstrap admin if no user with this email exists.

        Returns the created user, or ``None`` if it already existed. Used at
        application startup to guarantee the platform is reachable.
        """
        if await self._repo.get_by_email(email):
            return None
        user = User(
            email=email,
            username=username,
            full_name="Platform Administrator",
            role=UserRole.ADMIN,
            is_active=True,
            is_superuser=True,
            hashed_password=hash_password(password),
        )
        return await self._repo.add(user)
