"""应用内安装本机解析引擎（infra/parsers/installer.py）。用假的 uv，不联网。"""

import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from freeread.infra.parsers import installer
from freeread.infra.parsers.installer import EngineInstaller, InstallError, _extract_uv

FAKE_UV = """
import sys
from pathlib import Path

args = sys.argv[1:]
if args[0] == "venv":
    Path(args[-1]).mkdir(parents=True)
    print("Creating virtual environment at:", args[-1])
elif args[0] == "pip":
    print("Resolved 3 packages")
    if Path(__file__).with_name("fail").exists():
        print("error: no matching distribution", file=sys.stderr)
        sys.exit(2)
    print("Installed 3 packages")
"""


@pytest.fixture
def fake(tmp_path, monkeypatch):
    script = tmp_path / "fake_uv.py"
    script.write_text(FAKE_UV, encoding="utf-8")
    # 假环境没有真的 python：导入检查改用当前解释器跑一个总能成功的导入
    monkeypatch.setattr(installer, "venv_python", lambda venv: Path(sys.executable))
    monkeypatch.setattr(
        installer, "IMPORT_CHECK", {"mineru": "import json", "docling": "import json"}
    )
    root = tmp_path / "engines"
    return script, root, EngineInstaller(root, tmp_path, [sys.executable, str(script)])


async def test_install_success(fake, tmp_path):
    _, root, inst = fake
    reports: list[tuple[float, str]] = []

    async def report(p: float, msg: str) -> None:
        reports.append((p, msg))

    await inst.install("mineru", report)
    assert (root / "mineru").is_dir()
    assert not (root / "mineru.partial").exists()
    messages = [m for _, m in reports]
    assert "Installed 3 packages" in messages
    assert [p for p, _ in reports] == sorted(p for p, _ in reports)
    log = (tmp_path / "engine-install-mineru.log").read_text(encoding="utf-8")
    assert "mineru[torch]==4.0.12" in log and "--torch-backend auto" in log


async def test_install_failure_leaves_no_engine(fake):
    script, root, inst = fake
    (script.parent / "fail").touch()

    async def report(p: float, msg: str) -> None:
        pass

    with pytest.raises(InstallError, match="no matching distribution"):
        await inst.install("docling", report)
    assert not (root / "docling").exists()
    # 再装一次会先清掉上次的半成品
    (script.parent / "fail").unlink()
    await inst.install("docling", report)
    assert (root / "docling").is_dir()


async def test_install_unknown_engine(fake):
    async def report(p: float, msg: str) -> None:
        pass

    with pytest.raises(InstallError):
        await fake[2].install("marker", report)


def test_extract_uv(tmp_path):
    exe = "uv.exe" if sys.platform == "win32" else "uv"
    z = tmp_path / "uv.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr(exe, b"zip-uv")
        f.writestr("uvx.exe", b"other")
    (tmp_path / "a").mkdir()
    _extract_uv(z, tmp_path / "a" / exe)
    assert (tmp_path / "a" / exe).read_bytes() == b"zip-uv"

    src = tmp_path / "uv-target"
    src.mkdir()
    (src / exe).write_bytes(b"tar-uv")
    t = tmp_path / "uv.tar.gz"
    with tarfile.open(t, "w:gz") as f:
        f.add(src, arcname="uv-target")
    (tmp_path / "b").mkdir()
    _extract_uv(t, tmp_path / "b" / exe)
    assert (tmp_path / "b" / exe).read_bytes() == b"tar-uv"


def test_request_install_dedup(ctx, monkeypatch):
    monkeypatch.delenv("FREEREAD_MINERU_PYTHON")
    monkeypatch.delenv("FREEREAD_DOCLING_PYTHON")
    a = ctx.parse.request_install("mineru")
    assert a.kind == "engine_install" and a.payload == {"engine": "mineru"}
    assert ctx.parse.request_install("mineru").id == a.id
    assert ctx.parse.request_install("docling").id != a.id


def test_install_api_rejects_unknown_engine(client):
    assert client.post("/parsers/marker/install").status_code == 422


def test_install_refused_when_python_overridden(client):
    # conftest 用 FREEREAD_<ENGINE>_PYTHON 把引擎指向不存在的路径：不能覆盖用户指定的环境
    r = client.post("/parsers/docling/install")
    assert r.status_code == 409 and "FREEREAD_DOCLING_PYTHON" in r.json()["detail"]
