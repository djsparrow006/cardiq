"""
Authentication — real login, not a name picker. Password hashing via
werkzeug (already a Flask dependency, no new package needed), session
management via Flask-Login.

Account creation is admin-only (per product decision): there's no public
/register route. The very first account ever created (when the users table
is empty) is automatically made an admin, so someone can actually log in
and start creating team accounts. After that, only admins can create users.
"""
from flask_login import LoginManager
from werkzeug.security import generate_password_hash, check_password_hash

from db.session import SessionLocal
from db.models import User

login_manager = LoginManager()
login_manager.login_view = "login"


@login_manager.user_loader
def load_user(user_id):
    db = SessionLocal()
    try:
        return db.query(User).get(int(user_id))
    finally:
        db.close()


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(user: User, password: str) -> bool:
    return check_password_hash(user.password_hash, password)


def create_user(db, name: str, password: str, role: str = "member") -> User:
    user = User(name=name, password_hash=hash_password(password), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def bootstrap_first_admin_if_needed(db):
    """If the users table is completely empty, create a default admin
    account so someone can log in and start creating real team accounts.
    Prints the credentials once — change the password immediately after
    first login in a real deployment."""
    if db.query(User).count() > 0:
        return
    default_password = "changeme123"
    create_user(db, name="admin", password=default_password, role="admin")
    print("=" * 60)
    print("No users existed — created a default admin account:")
    print("  username: admin")
    print(f"  password: {default_password}")
    print("  CHANGE THIS PASSWORD after your first login.")
    print("=" * 60)
