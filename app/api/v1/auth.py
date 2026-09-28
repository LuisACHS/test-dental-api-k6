from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import OAuth2PasswordRequestForm

from app.core.deps import CurrentUser, DbSession, get_user_by_email
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User, UserRole
from app.schemas.auth import Token, UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un paciente",
)
async def register(payload: UserCreate, db: DbSession) -> User:
    if await get_user_by_email(db, payload.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El email ya esta registrado",
        )

    #  bcrypt es CPU-bound: fuera del event loop o bloquea a todo el resto de
    #  los requests mientras hashea.
    hashed = await run_in_threadpool(hash_password, payload.password)

    user = User(
        email=payload.email,
        hashed_password=hashed,
        full_name=payload.full_name,
        role=UserRole.patient,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post(
    "/login",
    response_model=Token,
    summary="Obtener un access token",
    description=(
        "Flujo OAuth2 password. El campo `username` de Swagger es el email.\n\n"
        "El token resultante se usa con el boton **Authorize**."
    ),
)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
) -> Token:
    email = form.username.strip().lower()
    user = await get_user_by_email(db, email)

    password_ok = False
    if user is not None:
        password_ok = await run_in_threadpool(
            verify_password, form.password, user.hashed_password
        )

    #  Mensaje unico para no revelar si el email existe.
    if user is None or not password_ok or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o password incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token, expires_in = create_access_token(subject=str(user.id), role=user.role.value)
    return Token(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=UserRead, summary="Usuario del token actual")
async def me(current_user: CurrentUser) -> User:
    return current_user
