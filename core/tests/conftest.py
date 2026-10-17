from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from freeread.context import AppContext
from freeread.main import create_app

TOKEN = "secret"
AUTH = {"X-FreeRead-Token": TOKEN}


@pytest.fixture
def ctx(tmp_path: Path) -> Iterator[AppContext]:
    context = AppContext.open(tmp_path / "data")
    yield context
    context.close()


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """带 lifespan（任务 worker 运行中）的客户端，默认带会话 token。"""
    with TestClient(create_app(token=TOKEN, data_dir=tmp_path / "data"), headers=AUTH) as c:
        yield c
