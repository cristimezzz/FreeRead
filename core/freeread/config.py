"""数据目录布局。见 docs/01-architecture.md §8。"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_DIR_NAME = "FreeRead"


def default_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        return Path(base) / APP_DIR_NAME if base else Path.home() / APP_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / APP_DIR_NAME


@dataclass(frozen=True)
class DataPaths:
    root: Path

    @property
    def db(self) -> Path:
        return self.root / "freeread.db"

    @property
    def documents(self) -> Path:
        return self.root / "documents"

    @property
    def zotero_snapshots(self) -> Path:
        return self.root / "zotero-snapshots"

    @property
    def models(self) -> Path:
        return self.root / "models"

    @property
    def engines(self) -> Path:
        """打包版的本机解析引擎环境（应用内安装）；开发时用仓库下的 .engines/。"""
        return self.root / "engines"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    def document_dir(self, doc_id: str) -> Path:
        return self.documents / doc_id

    def ensure(self) -> "DataPaths":
        for d in (self.root, self.documents, self.zotero_snapshots, self.models, self.logs):
            d.mkdir(parents=True, exist_ok=True)
        return self
