from fastapi import APIRouter, Depends, HTTPException, status

from app.deps.auth import get_current_user
from app.schemas.auth import AuthResponse, UserLoginRequest, UserProfileResponse, UserRegisterRequest
from app.security.rate_limit import rate_limit
from app.services.auth import authenticate_user, create_access_token, register_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit(20, 60, "auth_register"))],
)
async def register(payload: UserRegisterRequest) -> AuthResponse:
    try:
        register_user(payload.username, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    access_token = create_access_token(payload.username)
    return AuthResponse(access_token=access_token, username=payload.username)


@router.post(
    "/login",
    response_model=AuthResponse,
    dependencies=[Depends(rate_limit(30, 60, "auth_login"))],
)
async def login(payload: UserLoginRequest) -> AuthResponse:
    try:
        is_authenticated = authenticate_user(payload.username, payload.password)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    if not is_authenticated:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    access_token = create_access_token(payload.username)
    return AuthResponse(access_token=access_token, username=payload.username)


@router.get("/me", response_model=UserProfileResponse)
async def me(current_user: dict[str, str] = Depends(get_current_user)) -> UserProfileResponse:
    return UserProfileResponse(username=current_user["username"])
