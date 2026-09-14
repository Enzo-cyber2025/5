#!/usr/bin/env bash
# Public reference authorized by the user; not asserted to be their exact download.
set -euo pipefail
mkdir -p .cache/gemma4-models
BASE=https://huggingface.co/unsloth/gemma-4-E2B-it-GGUF/resolve/0314792d7f1f7e229411f620751375812bb9faf2
for NAME in gemma-4-E2B-it-Q3_K_S.gguf mmproj-F16.gguf; do
  curl --fail --location --retry 3 --max-time 1200 "$BASE/$NAME" -o ".cache/gemma4-models/$NAME"
done
(cd .cache/gemma4-models && printf '%s\n' \
 '80d155f647d3a896669b1d1605b494b97ee9dbd1dcafd27957394134c280d270  gemma-4-E2B-it-Q3_K_S.gguf' \
 '140be8d7849741f88c50757d529b84373ee8e27052cc2236855b537f4a8215fa  mmproj-F16.gguf' | sha256sum -c -)
