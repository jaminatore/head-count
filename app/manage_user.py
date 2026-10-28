"""Operator-only account commands. Run in an app container with DB access."""

import argparse
import asyncio

from sqlalchemy import select

from app.db import async_session
from app.models import User


async def run(args):
    async with async_session() as db:
        result = await db.execute(select(User).where(User.email == args.email))
        user = result.scalar_one_or_none()
        if user is None:
            raise SystemExit(f"No user with email {args.email}; they must sign in once first")
        if args.command == "grant-instructor":
            user.role = "instructor"
        elif args.command == "link-identity":
            user.oidc_issuer = args.issuer
            user.oidc_subject = args.subject
        await db.commit()
        print(f"Updated {user.email}: role={user.role}, OIDC linked={bool(user.oidc_subject)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    grant = commands.add_parser("grant-instructor", help="Grant an existing SSO user instructor access")
    grant.add_argument("email")
    link = commands.add_parser("link-identity", help="Link an existing user to a verified OIDC issuer and subject")
    link.add_argument("email")
    link.add_argument("issuer")
    link.add_argument("subject")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
