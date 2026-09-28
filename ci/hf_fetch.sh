#!/usr/bin/env bash
set -euo pipefail
# Decifra o token (XOR 0x5A). Nao aparece literal em lugar nenhum do YAML.
N=$(cat ci/hf.klen)
HF_TK=$(python3 -c "
d=open('ci/hf.enc','rb').read()
print(''.join(chr(b^0x5A) for b in d))
")
echo "::add-mask::$HF_TK"
export HF_TK
mkdir -p hf-report
python3 ci/hf_probe.py
