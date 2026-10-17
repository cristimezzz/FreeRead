"""导出 Core Service 的 OpenAPI 文档，供前端 openapi-typescript 生成类型。

    cd core && python ../scripts/export_openapi.py > ../docs/schemas/openapi.json

CI 会检查 docs/schemas/openapi.json 与代码同步。
"""

import json
import sys
import tempfile
from pathlib import Path

from freeread.main import create_app


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(token=None, data_dir=Path(tmp))
        try:
            schema = app.openapi()
        finally:
            app.state.ctx.close()
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    print(json.dumps(schema, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
