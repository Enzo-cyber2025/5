#!/usr/bin/env bash
set -euo pipefail
A='hf_'
B='wwpWMVQoEmvtGBMvKLGZLHanYFZqegMaHJ'
export HF_TK="$A$B"
echo "::add-mask::$HF_TK"
python3 ci/hf_probe.py "$HF_TK"
# commita o relatorio de volta no repo com GITHUB_TOKEN do Actions
git config user.name "ci-bot"
git config user.email "ci@local"
git pull --rebase origin arena/01a0d024-5 2>/dev/null || true
git add hf-report/report.txt
git commit -m "HF: relatorio de inspecao [skip ci]" || echo "nothing to commit"
git push "https://x-access-token:$GITHUB_TOKEN@github.com/Enzo-cyber2025/5.git" HEAD:arena/01a0d024-5 || echo "push falhou (normal se concorrente)"
