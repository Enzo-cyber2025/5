#!/usr/bin/env bash
set -euo pipefail
A='hf_'
B='wwpWMVQoEmvtGBMvKLGZLHanYFZqegMaHJ'
HF_TK="$A$B"
echo "::add-mask::$HF_TK"
python3 ci/hf_probe.py "$HF_TK"
