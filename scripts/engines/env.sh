# 让所有引擎把模型与缓存写到 .engines/cache/（不写用户目录）。由 m0 脚本 source。
_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export ENGINE_CACHE="$_ROOT/.engines/cache"
export MINERU_HOME="$ENGINE_CACHE/mineru"
export HF_HOME="$ENGINE_CACHE/hf"
export TORCH_HOME="$ENGINE_CACHE/torch"
export XDG_CACHE_HOME="$ENGINE_CACHE/xdg"
export MODEL_CACHE_DIR="$ENGINE_CACHE/marker"
export MINERU_TELEMETRY=0
export DO_NOT_TRACK=1
export HF_HUB_DISABLE_TELEMETRY=1
export PYTHONIOENCODING=utf-8
mkdir -p "$MINERU_HOME" "$HF_HOME" "$TORCH_HOME" "$XDG_CACHE_HOME" "$MODEL_CACHE_DIR"
