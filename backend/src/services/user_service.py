# =============================================================================
# User Service
# =============================================================================
"""Service for user management."""

import secrets
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import get_logger
from src.db.models import User, Session

logger = get_logger(__name__)


class UserService:
    """Service for user management."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_or_create_user(
        self,
        username: str,
        email: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> User:
        """
        Get existing user or create new one.
        
        Args:
            username: Unique username
            email: User email
            display_name: Display name
            
        Returns:
            User instance
        """
        result = await self.db.execute(
            select(User).where(User.username == username)
        )
        user = result.scalar_one_or_none()
        
        if user:
            # Update last login
            user.last_login_at = datetime.now(timezone.utc)
            await self.db.flush()
            return user
        
        # Create new user
        user = User(
            username=username,
            email=email,
            display_name=display_name or username,
            last_login_at=datetime.now(timezone.utc),
        )
        self.db.add(user)
        await self.db.flush()
        
        logger.info("User created", username=username)
        return user
    
    async def get_user(self, user_id: UUID) -> Optional[User]:
        """Get user by ID."""
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
    
    async def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username."""
        result = await self.db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()
    
    async def create_session(
        self,
        user_id: UUID,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Session:
        """
        Create a new user session.
        
        Args:
            user_id: User ID
            ip_address: Client IP
            user_agent: Client user agent
            
        Returns:
            Created session
        """
        session = Session(
            user_id=user_id,
            session_token=secrets.token_urlsafe(32),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.db.add(session)
        await self.db.flush()
        
        logger.info("Session created", user_id=str(user_id))
        return session
    
    async def get_session(self, session_id: UUID) -> Optional[Session]:
        """Get session by ID."""
        result = await self.db.execute(
            select(Session).where(Session.id == session_id)
        )
        return result.scalar_one_or_none()
    
    async def get_session_by_token(self, token: str) -> Optional[Session]:
        """Get session by token."""
        result = await self.db.execute(
            select(Session).where(
                Session.session_token == token,
                Session.is_active == True,
            )
        )
        return result.scalar_one_or_none()
    
    async def end_session(self, session_id: UUID) -> Optional[Session]:
        """End a session."""
        result = await self.db.execute(
            select(Session).where(Session.id == session_id)
        )
        session = result.scalar_one_or_none()
        
        if session:
            session.is_active = False
            session.ended_at = datetime.now(timezone.utc)
            await self.db.flush()
        
        return session
    
    async def get_active_user_count(self) -> int:
        """Get count of active users."""
        from sqlalchemy import func
        
        result = await self.db.execute(
            select(func.count(User.id)).where(User.is_active == True)
        )
        return result.scalar() or 0
