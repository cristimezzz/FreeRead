#!/usr/bin/env bash
# 为 M0 评测创建各解析引擎的独立环境（避免 torch 等依赖冲突）。
# 用法：bash scripts/m0_setup_engines.sh [mineru|docling|marker ...]
# 环境位于 .engines/<name>/，已加入 .gitignore。
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=.engines
mkdir -p "$ROOT"

engines=("$@")
# marker 已从候选中移除，需要时显式传入 marker
[ ${#engines[@]} -eq 0 ] && engines=(mineru docling)

for e in "${engines[@]}"; do
  venv="$ROOT/$e"
  [ -d "$venv" ] || uv venv --python 3.12 "$venv"
  case "$e" in
    mineru)  pkgs=("mineru[torch]") ;;
    docling) pkgs=("docling") ;;
    marker)  pkgs=("marker-pdf<2") ;;  # 2.x 需要 Docker vLLM 或 llama-server
    *) echo "unknown engine $e" >&2; exit 1 ;;
  esac
  echo "== $e: ${pkgs[*]}"
  uv pip install --python "$venv" --torch-backend auto "${pkgs[@]}"
done
