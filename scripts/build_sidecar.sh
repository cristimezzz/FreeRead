#!/usr/bin/env bash
# 用 PyInstaller 把 core 打包成 Tauri sidecar（不含重型 PDF 解析引擎）。Linux / macOS 用；
# Windows 用 scripts/build_sidecar.ps1，两边的步骤和参数保持一致（说明见那个脚本的注释）。
#
# 1. 用 uv 在 build/sidecar/.venv 建独立的 Python 环境，安装 core 基础依赖和 PyInstaller。
# 2. --onedir 打包到 build/sidecar/dist/freeread-core/，再整个目录复制到
#    apps/desktop/src-tauri/binaries/freeread-core/，由 tauri.conf.json 的 bundle.resources
#    安装到 <resource_dir>/freeread-core/（macOS 上是 FreeRead.app/Contents/Resources/freeread-core/）。
# 3. 打完用 scripts/measure_sidecar.sh 冒烟。
#
# 用法：scripts/build_sidecar.sh [--python 3.12]
# 要兼容 macOS 自带的 bash 3.2。
set -euo pipefail

python_version=3.12
while [ $# -gt 0 ]; do
  case "$1" in
    --python) python_version="$2"; shift 2 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

root=$(cd "$(dirname "$0")/.." && pwd)
core="$root/core"
build="$root/build/sidecar"
venv="$build/.venv"
python="$venv/bin/python"
target="$root/apps/desktop/src-tauri/binaries/freeread-core"
case "$(uname -s)" in
  Darwin) vec_lib=vec0.dylib ;;
  *) vec_lib=vec0.so ;;
esac

mkdir -p "$build"

echo "==> Python $python_version 构建环境：$venv"
[ -x "$python" ] || uv venv "$venv" --python "$python_version"
uv pip install --python "$python" "$core" "pyinstaller>=6.10"

# PyInstaller 入口：直接用包内模块作脚本会丢失包上下文，这里生成一个最小入口。
entry="$build/freeread_core_entry.py"
cat > "$entry" <<'EOF'
from freeread.main import run

if __name__ == "__main__":
    run()
EOF

# 各项收集参数的原因见 scripts/build_sidecar.ps1。
migrations="$core/freeread/infra/db/migrations"
prompts="$core/prompts"
engine_scripts="$root/scripts/engines"
vec_path="$("$python" -c "import os, sqlite_vec; print(os.path.dirname(sqlite_vec.__file__))")/$vec_lib"
dist="$build/dist"

echo "==> PyInstaller --onedir"
"$python" -m PyInstaller --onedir --noconfirm --clean --console \
  --name freeread-core \
  --collect-submodules uvicorn \
  --collect-submodules alembic \
  --hidden-import sqlalchemy.dialects.sqlite \
  --copy-metadata pymupdf \
  --add-binary "${vec_path}:sqlite_vec" \
  --collect-binaries onnxruntime \
  --add-data "${migrations}:freeread/infra/db/migrations" \
  --add-data "${prompts}:prompts" \
  --add-data "${engine_scripts}:engines" \
  --distpath "$dist" \
  --workpath "$build/work" \
  --specpath "$build" \
  "$entry"

onedir="$dist/freeread-core"
for required in \
  freeread-core \
  _internal/freeread/infra/db/migrations/env.py \
  _internal/prompts/translate.yaml \
  _internal/prompts/summarize_map.yaml \
  _internal/prompts/templates/summary.yaml \
  "_internal/sqlite_vec/$vec_lib" \
  _internal/engines/mineru_worker.py \
  _internal/engines/run_docling.py; do
  [ -e "$onedir/$required" ] || { echo "onedir 产物缺少 $required" >&2; exit 1; }
done

rm -rf "$target"
mkdir -p "$(dirname "$target")"
cp -R "$onedir" "$target"
files=$(find "$target" -type f | wc -l | tr -d ' ')
size=$(du -sh "$target" | cut -f1)
echo "    $target（$files 个文件，$size）"
