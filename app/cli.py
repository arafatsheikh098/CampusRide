"""Management CLI.

Subcommands land in their respective milestones. M1 ships only the
`upgrade-db` and `downgrade-db` helpers so the docker entrypoint can call
them; M2 adds `create-moderator`; M9 adds `purge` and `seed`.
"""
from __future__ import annotations

import argparse
import sys

from alembic import command as _alembic_command
from alembic.config import Config as _AlembicConfig


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
    args = p.parse_args(argv)

    if args.cmd == "upgrade-db":
        return upgrade_db()
    if args.cmd == "downgrade-db":
        return downgrade_db()
    if args.cmd in ("purge", "seed", "create-moderator"):
        # Implemented in the appropriate milestone; this guard makes the
        # command explicit rather than silent.
        print(f"{args.cmd} is implemented in a later milestone.", file=sys.stderr)
        return 2
    p.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
