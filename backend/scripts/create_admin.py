"""Create or reset the local Forge admin account."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.db import SessionLocal, initialize_database
from app.models import User
from app.security import hash_password


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or update a Forge admin user")
    parser.add_argument("--email", default="admin@forge.local")
    parser.add_argument("--password", default="ForgeAdmin123!")
    parser.add_argument("--name", default="Admin")
    args = parser.parse_args()

    initialize_database()
    email = args.email.strip().lower()
    db = SessionLocal()
    try:
        user = db.scalars(select(User).where(User.email == email)).first()
        if user is None:
            user = User(
                email=email,
                display_name=args.name.strip() or "Admin",
                password_hash=hash_password(args.password),
                role="admin",
            )
            db.add(user)
            action = "created"
        else:
            user.display_name = args.name.strip() or user.display_name
            user.password_hash = hash_password(args.password)
            user.role = "admin"
            action = "updated"
        db.commit()
        db.refresh(user)
        print(f"Admin account {action}.")
        print(f"  email:    {user.email}")
        print(f"  password: {args.password}")
        print(f"  role:     {user.role}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
