"""Provision the cost-guarded PantryPulse UAT DynamoDB tables."""

from __future__ import annotations

import argparse

from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError, ProfileNotFound

from pantrypulse.persistence.provisioning import (
    create_aws_session,
    ensure_tables,
    table_names,
    verify_cost_guardrails,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        help="Optional shared-credentials profile. Without it, use AWS values from .env.",
    )
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument(
        "--apply", action="store_true", help="Create missing tables after guardrails pass."
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.apply:
        print("Dry run: would manage " + ", ".join(table_names()))
        print("Run again with --apply to create missing tables.")
        return

    try:
        session = create_aws_session(
            profile_name=args.profile,
            region_name=args.region,
        )
        account_id = verify_cost_guardrails(
            session.client("sts"), session.client("budgets", region_name="us-east-1")
        )
        created = ensure_tables(session.client("dynamodb"), apply=True)
    except ProfileNotFound:
        raise SystemExit(
            f"AWS profile '{args.profile}' is unavailable. No tables were created. "
            "Configure the profile, then rerun with --apply."
        ) from None
    except (NoCredentialsError, PartialCredentialsError):
        raise SystemExit(
            "AWS credentials are unavailable or incomplete. Set AWS_ACCESS_KEY_ID and "
            "AWS_SECRET_ACCESS_KEY in the ignored .env file, then rerun with --apply."
        ) from None
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "AWS error")
        raise SystemExit(
            f"AWS preflight failed ({code}). No tables were created."
        ) from None
    except RuntimeError as error:
        raise SystemExit(f"Provisioning aborted: {error}") from None
    if created:
        print(f"Account {account_id}: created " + ", ".join(created))
    else:
        print(f"Account {account_id}: all required tables already exist.")


if __name__ == "__main__":
    main()
