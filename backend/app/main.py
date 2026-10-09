"""HTTP application: authentication, unit ownership, and saved analysis workflows."""

import secrets
import time
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .routes import router
from . import config
from .database import get_db
from .models import User, LoginSession
from .schemas import Credentials
from .engine import ENGINE_VERSION
from .security import current_user, digest, hasher, DUMMY_HASH, require_trusted_origin, throttle


app = FastAPI(
    title="Trading Strategy Testing Platform",
    version="1.0.0",
    description="Historical strategy simulation with costs, benchmarks and temporal model comparisons.",
)


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    # Never echo submitted values: validation failures may contain passwords.
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Review the highlighted fields.",
                "fields": [{"path": ".".join(map(str, item["loc"])), "message": item["msg"]} for item in exc.errors()],
            }
        },
    )


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={"error": {"code": f"HTTP_{exc.status_code}", "message": str(exc.detail)}},
    )


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
def health():
    return {"status": "ok", "engine_version": ENGINE_VERSION}


def issue_session(user, response, db):
    token, csrf = secrets.token_urlsafe(32), secrets.token_hex(32)
    db.add(
        LoginSession(
            token_hash=digest(token), user_id=user.id, csrf_token=csrf, expires_at=time.time() + config.SESSION_SECONDS
        )
    )
    db.commit()
    response.set_cookie(
        "strategy_session",
        token,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="lax",
        max_age=config.SESSION_SECONDS,
        path="/",
    )
    return {"user": {"id": user.id, "email": user.email}, "csrf_token": csrf}


@app.post("/api/auth/register", status_code=201)
def register(data: Credentials, request: Request, response: Response, db=Depends(get_db)):
    require_trusted_origin(request)
    throttle(request)
    user = User(email=data.email, password_hash=hasher.hash(data.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with this email already exists.") from None
    return issue_session(user, response, db)


@app.post("/api/auth/login")
def login(data: Credentials, request: Request, response: Response, db=Depends(get_db)):
    require_trusted_origin(request)
    throttle(request)
    user = db.scalar(select(User).where(User.email == data.email))
    try:
        valid = hasher.verify(user.password_hash if user else DUMMY_HASH, data.password)
    except (VerificationError, InvalidHashError):
        valid = False
    if not valid or user is None:
        raise HTTPException(401, "Email or password is incorrect.")
    if hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hasher.hash(data.password)
    return issue_session(user, response, db)


@app.get("/api/auth/session")
def session(request: Request, user=Depends(current_user)):
    return {"user": {"id": user.id, "email": user.email}, "csrf_token": request.state.login_session.csrf_token}


@app.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response, user=Depends(current_user), db=Depends(get_db)):
    db.delete(request.state.login_session)
    db.commit()
    response.delete_cookie("strategy_session", path="/")


app.include_router(router)
