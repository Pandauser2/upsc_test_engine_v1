"""
Auth routes: register (default role faculty), login (JWT), GET /auth/me with role.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse, UserResponse
from app.services.auth import hash_password, verify_password, create_access_token
from app.api.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new user; default role is faculty."""
    try:
        if db.query(User).filter(User.email == data.email).first():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
        user = User(
            email=data.email,
            password_hash=hash_password(data.password),
            role="faculty",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return UserResponse(id=str(user.id), email=user.email, role=user.role)
    except HTTPException:
        raise
    except IntegrityError as e:
        db.rollback()
        err_msg = str(getattr(e, "orig", e)).lower()
        logger.warning("Register IntegrityError: %s", e)
        if "email" in err_msg or "unique" in err_msg:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Registration failed (constraint)")
    except Exception as e:
        db.rollback()
        logger.exception("Register failed: %s", e)
        detail = "Registration failed. Check server logs for details."
        if getattr(settings, "debug", False):
            detail = f"Registration failed: {type(e).__name__}: {e}"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        )


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    """Login with email/password; returns JWT."""
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    token = create_access_token(user.id, user.email, user.role)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    """Return current user (id, email, role)."""
    return UserResponse(id=str(current_user.id), email=current_user.email, role=current_user.role)
