"""Cria o primeiro tenant e usuário administrador de forma interativa."""

from __future__ import annotations

import argparse
from getpass import getpass

from app.core.config import settings
from app.core.security import hash_password
from app.db.models import Tenant, User
from app.db.session import SessionLocal, configure_database


def create_admin(tenant_name: str, username: str, password: str) -> User:
    """Cria um administrador; nunca substitui uma conta existente."""
    if len(password) < 12:
        raise ValueError("A senha deve ter pelo menos 12 caracteres.")

    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == username).first() is not None:
            raise ValueError("Já existe um usuário com esse nome.")

        tenant = db.query(Tenant).filter(Tenant.nome == tenant_name).first()
        if tenant is None:
            tenant = Tenant(nome=tenant_name)
            db.add(tenant)
            db.flush()

        user = User(
            tenant_id=tenant.id,
            username=username,
            password_hash=hash_password(password),
            role="admin",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def reset_password(username: str, password: str) -> User:
    """Redefine a senha de uma conta existente via acesso administrativo ao banco."""
    if len(password) < 12:
        raise ValueError("A senha deve ter pelo menos 12 caracteres.")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            raise ValueError("Usuário não encontrado.")
        user.password_hash = hash_password(password)
        user.ativo = True
        db.commit()
        db.refresh(user)
        return user
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Cria o primeiro administrador do Auditor NCM.")
    parser.add_argument("--tenant", required=True, help="Nome da empresa/tenant.")
    parser.add_argument("--username", required=True, help="Usuário para o login.")
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Redefine a senha de um usuário existente, sem alterar o tenant.",
    )
    args = parser.parse_args()

    if not settings.database_url:
        raise RuntimeError("DATABASE_URL é obrigatória para criar o administrador.")
    password = getpass("Senha (mínimo 12 caracteres): ")
    confirmation = getpass("Repita a senha: ")
    if password != confirmation:
        raise ValueError("As senhas não coincidem.")

    configure_database()
    if args.reset_password:
        user = reset_password(args.username.strip(), password)
        print(f"Senha redefinida para: {user.username}")
    else:
        user = create_admin(args.tenant.strip(), args.username.strip(), password)
        print(f"Administrador criado: {user.username}")


if __name__ == "__main__":
    main()
