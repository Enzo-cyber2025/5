#!/usr/bin/env bash
set -e
cd /home/user/novabuild/src/linux-414
export ARCH=x86_64
export PATH="/home/user/novabuild/tools:$PATH"
export KCFLAGS="-O3 -pipe -march=goldmont-plus -mtune=goldmont-plus -fno-semantic-interposition"
export KBUILD_BUILD_USER=nova
export KBUILD_BUILD_HOST=novastation
make ARCH=x86_64 -j2 bzImage 2>&1
echo "BUILD_EXIT=$?"
