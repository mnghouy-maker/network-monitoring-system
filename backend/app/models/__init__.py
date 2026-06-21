"""SQLAlchemy models.

Importing the models here ensures they are registered on ``Base.metadata``
when this package is imported (e.g. by Alembic's ``env.py``).
"""

from app.models.user import User, UserRole

__all__ = ["User", "UserRole"]
