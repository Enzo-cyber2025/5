#!/usr/bin/env bash
# =============================================================================
# upload.sh — publica APENAS o .iso e o .sha256 no repositório público
#
# Regras do projeto (obrigatórias):
#   * Criar um repositório GitHub PÚBLICO chamado NovaLinux-ISO.
#   * Branch de publicação: somente "release".
#   * Enviar APENAS  ./${ISO_NAME}  e  ./${ISO_NAME}.sha256  (ou *.iso e *.sha256).
#   * NÃO incluir código-fonte (nenhum .c, .cpp, .h, .rs, .go, .py, .sh, .patch,
#     .config, Makefile, etc.) na branch "release". O source é mantido em
#     NOVALINUX/ (branch de desenvolvimento), separado da entrega binária.
#
# Uso:
#   ./upload.sh                                     # usa $NOVALINUX_REPO
#   NOVALINUX_REPO=usuario/NovaLinux-ISO ./upload.sh
#   ./upload.sh --repo usuario/NovaLinux-ISO
# =============================================================================
set -e -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${HERE}/config.sh"

log() { echo -e "\n\u001b[1;32m[NovaLinux/upload]\u001b[0m $*"; }

REPO="${NOVALINUX_REPO:-}"
if [ $# -ge 2 ] && [ "$1" = "--repo" ]; then REPO="$2"; fi
if [ -z "${REPO}" ]; then
  echo "ERRO: informe o repositório. Ex.: ./upload.sh --repo usuario/NovaLinux-ISO"; exit 1; fi

if [ ! -f "${ISO_PATH}" ] || [ ! -f "${SHA_PATH}" ]; then
  echo "ERRO: ${ISO_PATH} e/ou ${SHA_PATH} não existem. Rode ./build_all.sh primeiro."; exit 1; fi

log "Repositório alvo: ${REPO} (público, branch release)"
if ! gh repo view "${REPO}" >/dev/null 2>&1; then
  log "criando repositório público ${REPO}..."
  gh repo create "${REPO}" --public --source . --push --description \
    "NovaLinux — distribuição Linux otimizada para Intel Pentium N5030 (Goldmont Plus)" \
    --accept 2>&1 || true
fi

TMPD=$(mktemp -d)
trap 'rm -rf "${TMPD}"' EXIT
cp "${ISO_PATH}" "${TMPD}/"
cp "${SHA_PATH}" "${TMPD}/"

log "clonando apenas a branch release em ${TMPD}/repo..."
git clone "https://github.com/${REPO}.git" "${TMPD}/repo" 2>/dev/null || \
  { echo "ERRO: clone falhou"; exit 1; }
cd "${TMPD}/repo"
# retém a branch release se existir; caso contrário cria a partir de main/empty
if git show-ref --quiet refs/remotes/origin/release; then
  git checkout release
else
  git checkout -b release || true
fi

log "removendo fontes antigos e copiando AINDA SOMENTE binários+hash..."
git rm -rf . >/dev/null 2>&1 || true
rm -rf ./* ./.github 2>/dev/null || true
cp "${ISO_PATH}" .
cp "${SHA_PATH}" .
# garante que nada de fonte vá junto
find . -maxdepth 1 -type f ! -name '*.iso' ! -name '*.sha256' -delete 2>/dev/null || true

git add -A
git -c user.name="NovaLinux Bot" -c user.email="nova@novastation" commit -m "NovaLinux ${DISTRO_VERSION} release ISO + SHA256" 2>&1 || true
git push -u origin release --force 2>&1 | tail -5

log "conteúdo final da branch release:"
ls -la
log "URL: https://github.com/${REPO}"
log "SHA256: $(cat "${SHA_PATH}")"
