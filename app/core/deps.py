"""Dependencias compartidas: sesion, usuario autenticado y token de admin."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import TokenError, decode_access_token
from app.db.session import get_db
from app.models.user import User, UserRole

#  Sin la barra inicial: asi Swagger arma la URL relativa al server y el boton
#  Authorize sigue funcionando si la API queda detras de un prefijo.
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.api_v1_prefix.lstrip('/')}/auth/login",
    scheme_name="OAuth2 (email + password)",
)

admin_token_scheme = APIKeyHeader(
    name="X-Admin-Token",
    auto_error=False,
    scheme_name="Token de admin (caos)",
    description="Token estatico definido en la variable de entorno ADMIN_TOKEN.",
)

DbSession = Annotated[AsyncSession, Depends(get_db)]

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Credenciales invalidas",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DbSession,
) -> User:
    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
    except (TokenError, KeyError, ValueError):
        raise _CREDENTIALS_ERROR from None

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise _CREDENTIALS_ERROR
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_admin(current_user: CurrentUser) -> User:
    if current_user.role is not UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requiere rol admin",
        )
    return current_user


CurrentAdmin = Annotated[User, Depends(get_current_admin)]


async def require_admin_token(
    token: Annotated[str | None, Security(admin_token_scheme)],
) -> None:
    """Token estatico para /admin/*.

    A proposito no usa JWT: el harness de performance cambia el caos entre
    escenarios con un curl, sin loguearse ni renovar nada.
    """
    if not token or token != settings.admin_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Header X-Admin-Token ausente o invalido",
        )


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    return await db.scalar(select(User).where(User.email == email))
