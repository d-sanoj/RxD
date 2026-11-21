"""Sign-in and active-user lookup."""

from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.models.entities import User
from app.models.repositories import AuditRepo, UserRepo


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = UserRepo(db).by_username(username)
    ok = user is not None and user.active and verify_password(password, user.password_hash)
    AuditRepo(db).add(
        username,
        "auth.login" if ok else "auth.login_failed",
        "user",
        str(user.id) if user else "",
    )
    db.commit()
    return user if ok else None


def get_active_user(db: Session, username: str) -> User | None:
    user = UserRepo(db).by_username(username)
    return user if user and user.active else None
