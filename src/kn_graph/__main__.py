import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="KN Graph")
    sub = parser.add_subparsers(dest="command")

    serve_parser = sub.add_parser("serve", help="Start the API server")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8013)
    serve_parser.add_argument("--reload", action="store_true", help="Enable auto-reload on code changes")

    sub.add_parser("worker", help="Start the Celery worker")

    args = parser.parse_args()

    if args.command == "serve":
        import uvicorn
        from kn_graph.config import Settings

        settings = Settings(
            host=args.host,
            port=args.port,
        )
        from kn_graph.app import create_app
        app = create_app(settings)
        uvicorn.run(app, host=settings.host, port=settings.port, reload=args.reload)

    elif args.command == "worker":
        from kn_graph.config import Settings
        settings = Settings()
        settings.load_global_settings()
        from kn_graph.workers.celery_app import get_celery_app
        app = get_celery_app(settings)
        app.worker_main(sys.argv[2:])

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
