"""Command line: python3 -m app serve|migrate|seed|test (or python3 manage.py ...)."""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "app.sqlite3"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="manage.py", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="run the web application")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--db", default=str(DEFAULT_DB))
    serve.add_argument("--allow-network", action="store_true",
                       help="bind to a non-loopback address (only behind an authenticating proxy)")
    migrate = commands.add_parser("migrate", help="apply (or revert) database migrations")
    migrate.add_argument("--db", default=str(DEFAULT_DB))
    migrate.add_argument("--down", type=int, default=0, metavar="STEPS")
    seed = commands.add_parser("seed", help="load the synthetic seed data")
    seed.add_argument("--db", default=str(DEFAULT_DB))
    test = commands.add_parser("test", help="run unit and API integration tests")
    test.add_argument("--report", help="write a JSON result report to this path")
    args = parser.parse_args(argv)

    if args.command == "serve":
        from . import server
        server.serve(args.host, args.port, args.db, allow_network=args.allow_network)
        return 0
    if args.command == "test":
        sys.path.insert(0, str(ROOT))
        from tests import run_tests
        return run_tests.main(args.report)
    pathlib.Path(args.db).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.command == "migrate":
        from . import db
        connection = db.connect(args.db)
        try:
            done = db.rollback(connection, steps=args.down) if args.down else db.migrate(connection)
        finally:
            connection.close()
        print(json.dumps({"reverted" if args.down else "applied": done}))
        return 0
    from . import seed as seeding
    counts = seeding.seed(args.db)
    print(json.dumps({"seeded_synthetic_records": counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
