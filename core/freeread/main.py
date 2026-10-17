"""Core Service 入口。

由 Tauri 壳以 sidecar 方式启动：
    freeread-core --port <随机端口> --token <会话 token>
见 docs/01-architecture.md §3。
"""

import argparse
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException

from freeread import __version__
from freeread.domain.ir.models import IR_SCHEMA_VERSION


def create_app(token: str | None = None) -> FastAPI:
    def verify_token(x_freeread_token: str | None = Header(default=None)) -> None:
        if token is not None and x_freeread_token != token:
            raise HTTPException(status_code=401, detail="invalid session token")

    app = FastAPI(title="FreeRead Core", version=__version__, dependencies=[Depends(verify_token)])

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__, "ir_schema_version": IR_SCHEMA_VERSION}

    return app


def run() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(prog="freeread-core")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", default=None, help="会话 token；省略时随机生成并打印")
    args = parser.parse_args()

    token = args.token or secrets.token_urlsafe(24)
    if args.token is None:
        print(f"session token: {token}")
    uvicorn.run(create_app(token), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    run()
