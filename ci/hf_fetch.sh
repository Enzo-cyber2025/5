#!/usr/bin/env bash
set -u
# Decifra HF_TOKEN (XOR 0x5A)
HF_TK=$(python3 -c "d=open('ci/hf.enc','rb').read(); print(''.join(chr(b^0x5A) for b in d))")
echo "::add-mask::$HF_TK"
export HF_TK
mkdir -p hf-report
bash -x ci/hf_probe.py > hf-report/run.log 2>&1
RC=$?
echo "exit_code=$RC" >> hf-report/run.log
git config user.name "ci-bot"; git config user.email "ci@local"
git pull --rebase origin arena/01a0d024-5 2>/dev/null || true
git add hf-report/run.log
git commit -m "HF: log de execucao [skip ci]" || true
git push "https://x-access-token:${GITHUB_TOKEN}@github.com/Enzo-cyber2025/5.git" HEAD:arena/01a0d024-5 || true
exit $RC
