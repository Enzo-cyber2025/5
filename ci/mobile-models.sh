#!/usr/bin/env bash
set -euo pipefail
mkdir -p .cache/mobile-models
BASE=https://huggingface.co/ggml-org/SmolVLM-256M-Instruct-GGUF/resolve/main
for NAME in SmolVLM-256M-Instruct-Q8_0.gguf mmproj-SmolVLM-256M-Instruct-Q8_0.gguf; do
  curl --fail --location --retry 3 --max-time 900 "$BASE/$NAME" -o ".cache/mobile-models/$NAME"
done
(cd .cache/mobile-models && printf '%s\n' \
 '2a31195d3769c0b0fd0a4906201666108834848db768af11de1d2cef7cd35e65  SmolVLM-256M-Instruct-Q8_0.gguf' \
 '7e943f7c53f0382a6fc41b6ee0c2def63ba4fded9ab8ed039cc9e2ab905e0edd  mmproj-SmolVLM-256M-Instruct-Q8_0.gguf' | sha256sum -c -)
