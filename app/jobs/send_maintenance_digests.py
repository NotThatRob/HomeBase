import argparse
import logging

from app.config import get_settings
from app.database import get_session_factory
from app.logging_config import setup_logging
from app.services.email_reminders import send_digests

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send HomeBase maintenance digests.")
    parser.add_argument(
        "--frequency",
        choices=["daily", "weekly"],
        default="daily",
        help="Digest frequency to send.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build digest summaries without contacting Resend.",
    )
    parser.add_argument(
        "--days-ahead",
        type=int,
        default=7,
        help="Upcoming due window to include.",
    )
    args = parser.parse_args()

    settings = get_settings()
    setup_logging(settings)
    logger.info(
        "Starting maintenance digest job",
        extra={"frequency": args.frequency, "dry_run": args.dry_run},
    )
    session = get_session_factory()()
    try:
        results = send_digests(
            session,
            frequency=args.frequency,
            settings=settings,
            dry_run=args.dry_run,
            days_ahead=args.days_ahead,
        )
    finally:
        session.close()

    summary = _summarize(results)
    logger.info(
        "Completed maintenance digest job",
        extra={
            "frequency": args.frequency,
            "dry_run": args.dry_run,
            "processed": summary["total"],
            "sent": summary["sent"],
            "skipped": summary["skipped"],
            "failed": summary["failed"],
        },
    )

    if not results:
        print(f"No {args.frequency} digest recipients.")
        return 0

    for index, result in enumerate(results, start=1):
        print(
            f"{result.status}: recipient {index} "
            f"({result.task_count} task{'s' if result.task_count != 1 else ''}) "
            f"- {result.detail}"
        )
    return 0


def _summarize(results) -> dict[str, int]:
    counts = {"total": len(results), "sent": 0, "skipped": 0, "failed": 0, "dry_run": 0}
    for result in results:
        if result.status in counts:
            counts[result.status] += 1
    return counts


if __name__ == "__main__":
    raise SystemExit(main())
