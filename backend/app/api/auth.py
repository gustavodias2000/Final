from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.login_throttle import login_throttle
from app.core.security import create_access_token, verify_password
from app.db.models import User
from app.schemas.auth import LoginRequest

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login")
def login(request: LoginRequest, db: Session = Depends(get_db)):
    wait_seconds = login_throttle.retry_after(request.username)
    if wait_seconds:
        minutes = max(1, -(-wait_seconds // 60))
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Muitas tentativas sem sucesso. Tente de novo em {minutes} {'minuto' if minutes == 1 else 'minutos'}.",
            headers={"Retry-After": str(wait_seconds)},
        )

    user = db.query(User).filter(User.username == request.username, User.ativo.is_(True)).first()
    if not user or not verify_password(request.password, user.password_hash):
        login_throttle.record_failure(request.username)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciais inválidas")

    login_throttle.reset(request.username)

    token = create_access_token({"sub": str(user.id), "tenant_id": str(user.tenant_id)})
    return {"access_token": token, "token_type": "bearer"}
