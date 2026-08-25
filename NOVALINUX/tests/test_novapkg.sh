#!/usr/bin/env bash
# =============================================================================
# test_novapkg.sh — teste de ponta a ponta do NovaPKG dentro do repositório
#
# Verifica build/install(list ou informação)/remove do pacote de exemplo,
# usando um root de teste descartável (${TMPROOT}). Nenhuma dependência além de
# Python 3 e tar/xz disponíveis no sistema.
# =============================================================================
set -e -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOVAPKG="${HERE}/../novapkg/novapkg"
REPO="${HERE}/../novapkg/repo"
TMPROOT="$(mktemp -d)"
TMPSTAGE="$(mktemp -d)"
trap 'rm -rf "${TMPROOT}" "${TMPSTAGE}"' EXIT

export NOVAPKG_ROOT="${TMPROOT}"
export NOVAPKG_REPO="${REPO}"

echo "[1/5] build do pacote de exemplo..."
mkdir -p "${TMPSTAGE}/.novapkg" "${TMPSTAGE}/usr/bin"
cat > "${TMPSTAGE}/.novapkg/metadata.json" <<EOF
{"name":"nova-test","version":"1.0","arch":"x86_64","description":"pacote de teste"}
EOF
printf '#!/bin/sh\necho "test ok"\n' > "${TMPSTAGE}/usr/bin/nova-test-bin"
chmod +x "${TMPSTAGE}/usr/bin/nova-test-bin"
python3 "${NOVAPKG}" build --staging "${TMPSTAGE}" --name nova-test --version 1.0 \
  --output "${TMPROOT}/nova-test.nvpkg" >/dev/null

echo "[2/5] update índice do repositório..."
python3 "${NOVAPKG}" update >/dev/null

echo "[3/5] install (por arquivo .nvpkg)..."
python3 "${NOVAPKG}" install "${TMPROOT}/nova-test.nvpkg" >/dev/null
test -x "${TMPROOT}/usr/bin/nova-test-bin" || { echo "FALHA: binário não instalado/executável"; exit 1; }
"${TMPROOT}/usr/bin/nova-test-bin" | grep -q "test ok" || { echo "FALHA: binário não executa"; exit 1; }

echo "[4/5] list/search/info..."
python3 "${NOVAPKG}" list | grep -q nova-test || { echo "FALHA: list"; exit 1; }
python3 "${NOVAPKG}" search test | grep -q nova-test || { echo "FALHA: search"; exit 1; }

echo "[5/5] remove..."
python3 "${NOVAPKG}" remove nova-test >/dev/null
if python3 "${NOVAPKG}" list | grep -q nova-test; then
  echo "FALHA: remove não limpou"; exit 1; fi

echo "OK: teste NovaPKG passou (build/install/list/search/remove)."
