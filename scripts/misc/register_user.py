import argparse

from sqlmodel import Session, create_engine
from usrak.core.security import hash_password

from src.enums import DVTDefaultRoles
from src.modules.user.infra.db_models import UserRecord

import config

engine = create_engine(
    url=config.POSTGRES.DATABASE_URL,
    echo=True
)


def register_user(
    email: str,
    password: str,
    role: str = DVTDefaultRoles.USER.value,
    is_verified: bool = False,
):
    with Session(engine) as session:
        user = UserRecord(
            email=email,
            hashed_password=hash_password(password),
            auth_provider="email",
            is_verified=is_verified,
            is_active=True,
            role=role,
        )
        session.add(user)
        session.commit()
        print(f"✅ Пользователь {email} зарегистрирован.")


def main():
    parser = argparse.ArgumentParser(description="Регистрация нового пользователя")
    parser.add_argument("--email", required=True, help="Email пользователя")
    parser.add_argument("--password", required=True, help="Пароль пользователя")
    parser.add_argument(
        "--role",
        choices=DVTDefaultRoles.values(),
        default=DVTDefaultRoles.USER.value,
        help="Роль пользователя",
    )
    parser.add_argument("--verified", action="store_true", help="Флаг: пометить пользователя как верифицированного")

    args = parser.parse_args()

    register_user(
        email=args.email,
        password=args.password,
        role=args.role,
        is_verified=args.verified,
    )


if __name__ == "__main__":
    main()
