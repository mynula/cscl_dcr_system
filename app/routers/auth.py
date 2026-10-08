from datetime import timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models.user import User
from app.schemas.user import Token, UserResponse, UserLogin
from app.services.auth_service import (
    verify_password,
    create_access_token,
    get_current_user,
    get_current_user_optional,
    get_password_hash,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Render the login page if not logged in, else redirect to dashboard."""
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={"user": None, "error": None}
    )


@router.post("/login")
async def login_submit(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Handle login form submission with session cookie generation."""
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        # Check if requested via HTMX
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={
                "user": None,
                "error": "Invalid username or password. Please try again."
            },
            status_code=status.HTTP_400_BAD_REQUEST
        )

    if not user.is_active:
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={
                "user": None,
                "error": "Your account has been deactivated. Please contact the administrator."
            },
            status_code=status.HTTP_403_FORBIDDEN
        )

    # Create access token
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role, "id": user.id}
    )

    # If HTMX request, we can use HX-Redirect header
    if request.headers.get("hx-request"):
        res = Response(content="Login successful", status_code=200)
        res.set_cookie(
            key="access_token",
            value=f"Bearer {access_token}",
            httponly=True,
            max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            samesite="lax",
            secure=settings.secure_cookies,
        )
        res.headers["HX-Redirect"] = "/dashboard"
        return res

    redirect = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    redirect.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        secure=settings.secure_cookies,
    )
    return redirect


@router.get("/change-password", response_class=HTMLResponse)
async def change_password_page(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(
        request=request,
        name="auth/change_password.html",
        context={"user": current_user, "error": None, "success": None},
    )


@router.post("/change-password", response_class=HTMLResponse)
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(..., min_length=12),
    confirm_password: str = Form(..., min_length=12),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(current_password, current_user.hashed_password):
        error = "Current password is incorrect."
    elif new_password != confirm_password:
        error = "New password and confirmation do not match."
    elif new_password == current_password:
        error = "Choose a new password different from the current password."
    else:
        current_user.hashed_password = get_password_hash(new_password)
        db.commit()
        return templates.TemplateResponse(
            request=request,
            name="auth/change_password.html",
            context={
                "user": current_user,
                "error": None,
                "success": "Password updated successfully.",
            },
        )

    return templates.TemplateResponse(
        request=request,
        name="auth/change_password.html",
        context={"user": current_user, "error": error, "success": None},
        status_code=status.HTTP_400_BAD_REQUEST,
    )


@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """OAuth2 compatible token endpoint for programmatic API access."""
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )

    access_token = create_access_token(
        data={"sub": user.username, "role": user.role, "id": user.id}
    )
    return Token(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.model_validate(user)
    )


@router.get("/logout")
async def logout(response: Response):
    """Log out user by clearing the access_token cookie."""
    redirect = RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
    redirect.delete_cookie(key="access_token", secure=settings.secure_cookies, httponly=True, samesite="lax")
    return redirect


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(current_user: User = Depends(get_current_user)):
    """Return currently authenticated user information."""
    return UserResponse.model_validate(current_user)
