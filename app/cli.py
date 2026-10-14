"""Management CLI.

Subcommands land in their respective milestones. M1 ships only the
`upgrade-db` and `downgrade-db` helpers so the docker entrypoint can call
them; M2 adds `create-moderator`; M9 adds `purge` and `seed`.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from alembic import command as _alembic_command
from alembic.config import Config as _AlembicConfig
from sqlmodel import Session, select

from .config import get_settings
from .db import get_engine
from .models.user import User, UserRole, UserStatus
from .phone import PhoneError, normalize as normalize_phone
from .security import hash_password


def upgrade_db() -> int:
    cfg = _AlembicConfig("alembic.ini")
    _alembic_command.upgrade(cfg, "head")
    return 0


def downgrade_db(revision: str = "-1") -> int:
    cfg = _AlembicConfig("alembic.ini")
    _alembic_command.downgrade(cfg, revision)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("upgrade-db")
    sub.add_parser("downgrade-db")
    sub.add_parser("purge", help="(M9) purge old trips and bookings")
    sub.add_parser("seed", help="(M9) idempotent demo seed")
    p_create_mod = sub.add_parser("create-moderator", help="(M2)")
    p_create_mod.add_argument("--mobile", required=True)
    p_create_mod.add_argument("--password", required=True)
    p_create_mod.add_argument("--full-name", required=True)
    p_create_mod.add_argument("--department", default="Staff")
    p_create_mod.add_argument("--batch", default="N/A")
    args = p.parse_args(argv)

    if args.cmd == "upgrade-db":
        return upgrade_db()
    if args.cmd == "downgrade-db":
        return downgrade_db()
    if args.cmd == "create-moderator":
        return _create_moderator(
            mobile=args.mobile,
            password=args.password,
            full_name=args.full_name,
            department=args.department,
            batch=args.batch,
        )
    if args.cmd == "purge":
        from .purge import purge as _purge
        counts = _purge()
        print("purged:", counts)
        return 0
    if args.cmd == "seed":
        from .seed import seed as _seed
        counts = _seed()
        print("seeded:", counts)
        return 0
    p.print_help()
    return 1


def _create_moderator(*, mobile: str, password: str, full_name: str, department: str, batch: str) -> int:
    try:
        mobile_e164 = normalize_phone(mobile)
    except PhoneError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if len(password) < 8:
        print("error: password must be at least 8 characters", file=sys.stderr)
        return 2
    get_settings()  # ensure env-driven config loaded
    with Session(get_engine()) as session:
        existing = session.exec(select(User).where(User.mobile_e164 == mobile_e164)).first()
        if existing is not None:
            print("error: a user with that mobile already exists", file=sys.stderr)
            return 2
        u = User(
            full_name=full_name,
            department=department,
            batch_or_session=batch,
            mobile_e164=mobile_e164,
            password_hash=hash_password(password),
            role=UserRole.MODERATOR,
            status=UserStatus.APPROVED,
            is_campus_member=True,
            is_18_or_older=True,
            created_at=datetime.now(timezone.utc),
            approved_at=datetime.now(timezone.utc),
        )
        session.add(u)
        session.commit()
        # Log only the user id, never the mobile number, so the secret
        # doesn't leak into shell history or captured stdout/stderr.
        print(f"created moderator id={u.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
