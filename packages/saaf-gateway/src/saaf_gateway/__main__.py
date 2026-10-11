"""``python -m saaf_gateway`` / ``saaf-gateway`` entrypoint."""

from __future__ import annotations

import argparse


def main() -> None:
    import uvicorn

    p = argparse.ArgumentParser(prog="saaf-gateway")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--workers", type=int, default=1)
    args = p.parse_args()
    uvicorn.run("saaf_gateway.app:create_app", factory=True, host=args.host, port=args.port, workers=args.workers)


if __name__ == "__main__":
    main()
