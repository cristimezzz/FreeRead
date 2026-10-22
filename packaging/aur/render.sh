#!/usr/bin/env bash
# 渲染 AUR 的 PKGBUILD：render.sh <版本> <deb 文件> <LICENSE 文件> > PKGBUILD
# deb 和 LICENSE 必须与 Release v<版本> 上的文件逐字节一致（校验和写进 PKGBUILD）。
set -euo pipefail
version="$1" deb="$2" license="$3"
sha() { sha256sum "$1" | cut -d' ' -f1; }
sed -e "s/@VERSION@/${version}/" \
    -e "s/@DEB_SHA256@/$(sha "$deb")/" \
    -e "s/@LICENSE_SHA256@/$(sha "$license")/" \
    "$(dirname "$0")/PKGBUILD.in"
