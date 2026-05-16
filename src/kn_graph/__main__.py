import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="KN Graph")
    sub = parser.add_subparsers(dest="command")

    serve_parser = sub.add_parser("serve", help="Start the API server")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8013)
    serve_parser.add_argument("--data-dir", default="", help="Data directory for libraries, runs, chat store etc. (default: %%LOCALAPPDATA%%/KNGraphApp on Windows, ~/.kn_graph elsewhere)")
    serve_parser.add_argument("--reload", action="store_true", help="Enable auto-reload on code changes")

    sub.add_parser("worker", help="Start the Celery worker")
    mcp_parser = sub.add_parser("mcp-server", help="Start KN MCP server over stdio")
    mcp_parser.add_argument("--api-base-url", default="", help="Backend API base URL")

    args = parser.parse_args()

    if args.command == "serve":
        import uvicorn
        from pathlib import Path
        from kn_graph.config import Settings

        kwargs = dict(host=args.host, port=args.port)
        if args.data_dir:
            kwargs["data_dir"] = Path(args.data_dir)
        settings = Settings(**kwargs)
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
    elif args.command == "mcp-server":
        from kn_graph.services import kn_mcp_server
        argv = [sys.argv[0]]
        if str(args.api_base_url or "").strip():
            argv.extend(["--api-base-url", str(args.api_base_url).strip()])
        old_argv = list(sys.argv)
        try:
            sys.argv = argv
            kn_mcp_server.main()
        finally:
            sys.argv = old_argv

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
