"""Server admin commands.

    python -m diamondiq.manage create-user --email you@example.com --name "You" --role admin
    python -m diamondiq.manage reset-password --email you@example.com
    python -m diamondiq.manage list-users

In Docker:  docker compose exec diamondiq python -m diamondiq.manage list-users
On Render:  open the service's Shell tab and run the same command.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from . import auth
from . import models as m
from .db import SessionLocal, init_db


def _password() -> str:
    while True:
        pw = getpass.getpass(f"Password ({auth.MIN_PASSWORD}+ characters): ")
        if len(pw) < auth.MIN_PASSWORD:
            print("Too short.")
        elif getpass.getpass("Again: ") != pw:
            print("Didn't match.")
        else:
            return pw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m diamondiq.manage")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-user")
    c.add_argument("--email", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--role", default="scout", choices=auth.ROLES)
    r = sub.add_parser("reset-password")
    r.add_argument("--email", required=True)
    sub.add_parser("list-users")
    args = parser.parse_args(argv)

    init_db()
    with SessionLocal() as session:
        if args.cmd == "create-user":
            user = auth.create_user(session, args.email, args.name, _password(), args.role)
            print(f"Created {user.role} {user.email}")
        elif args.cmd == "reset-password":
            user = session.scalar(select(m.User).where(m.User.email == args.email.strip().lower()))
            if not user:
                print("No user with that email.", file=sys.stderr)
                return 1
            user.password_hash = auth.hash_password(_password())
            user.is_active = True
            session.commit()
            auth.end_all_sessions(session, user.id)
            print(f"Password reset for {user.email}; existing sessions signed out.")
        else:
            for u in session.scalars(select(m.User).order_by(m.User.email)):
                print(f"{u.email:40s} {u.role:7s} {'active' if u.is_active else 'disabled'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
