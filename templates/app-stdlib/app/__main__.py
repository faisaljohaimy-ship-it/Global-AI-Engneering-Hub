"""Command line: python3 manage.py serve|migrate|seed|create-account|test."""
import argparse
import getpass
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
                       help="bind to a non-loopback address (only behind TLS and a reverse proxy)")
    serve.add_argument("--secure-cookies", action="store_true", help="mark the session cookie Secure (HTTPS)")
    migrate = commands.add_parser("migrate", help="apply (or revert) database migrations")
    migrate.add_argument("--db", default=str(DEFAULT_DB))
    migrate.add_argument("--down", type=int, default=0, metavar="STEPS")
    seed = commands.add_parser("seed", help="load the synthetic seed data")
    seed.add_argument("--db", default=str(DEFAULT_DB))
    account = commands.add_parser("create-account", help="create a sign-in account (there is no default account)")
    account.add_argument("--db", default=str(DEFAULT_DB))
    account.add_argument("--email", required=True)
    account.add_argument("--role", required=True)
    account.add_argument("--password-stdin", action="store_true", help="read the password from standard input")
    test = commands.add_parser("test", help="run unit, API integration and acceptance tests")
    test.add_argument("--report", help="write a JSON result report to this path")
    args = parser.parse_args(argv)

    if args.command == "serve":
        from . import server
        server.serve(args.host, args.port, args.db, allow_network=args.allow_network, secure_cookies=args.secure_cookies)
        return 0
    if args.command == "test":
        from tests import run_tests
        return run_tests.main(args.report)
    pathlib.Path(args.db).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    from . import db
    if args.command == "migrate":
        connection = db.connect(args.db)
        try:
            done = db.rollback(connection, steps=args.down) if args.down else db.migrate(connection)
        finally:
            connection.close()
        print(json.dumps({"reverted" if args.down else "applied": done}))
        return 0
    if args.command == "create-account":
        from . import auth, model
        password = sys.stdin.readline().rstrip("\n") if args.password_stdin else getpass.getpass("Password: ")
        schema = model.load_schema()
        try:
            with db.session(args.db) as connection:
                db.migrate(connection)
                auth.create_account(connection, schema, args.email, args.role, password)
        except auth.AuthError as error:
            print(json.dumps({"error": error.code, "message": error.message}), file=sys.stderr)
            return 1
        print(json.dumps({"created": args.email.strip(), "role": args.role}))
        return 0
    from . import seed as seeding
    counts = seeding.seed(args.db)
    print(json.dumps({"seeded_synthetic_records": counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
