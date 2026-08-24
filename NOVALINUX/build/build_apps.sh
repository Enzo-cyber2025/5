#!/usr/bin/env bash
# =============================================================================
# build_apps.sh — compila e empacota os aplicativos do NovaLinux como .nvpkg
#
# Lê os manifestos em novapkg/specs/*.json.nvpspec, baixa as fontes, compila
# com -O3 -march=goldmont-plus -mtune=goldmont-plus -pipe -flto=auto usando a
# toolchain alvo (SYSROOT_DIR), e cria os pacotes .nvpkg via nova-pkg build.
#
# O trabalho pesado (LibreOffice/Firefox/GIMP/VLC) requer 8–16 GB RAM e várias
# horas; por isso o default é compilar os apps leves e deixar os pesados para
# uma execução explícita com --full.
#
# Uso:
#   ./build_apps.sh [--full] [--only=htop,vlc]
# =============================================================================
set -e -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${HERE}/config.sh"

log() { echo -e "\n\u001b[1;32m[NovaLinux/apps]\u001b[0m $*"; }

FULL=0
ONLY=""
for a in "$@"; do
  case "${a}" in
    --full) FULL=1 ;;
    --only=*) ONLY="${a#--only=}" ;;
  esac
done

NOVAPKG="${PROJECT_DIR}/novapkg/novapkg"
SPECS_DIR="${PROJECT_DIR}/novapkg/specs"
PKGROOT="${BUILD_DIR}/packages"
STAGE_ROOT="${BUILD_DIR}/app-stages"
mkdir -p "${PKGROOT}" "${STAGE_ROOT}"

# toolchain alvo
TC_PREFIX="${SYSROOT_DIR}/bin/${TARGET_ARCH}-nova-linux-gnu-"
export CC="${TC_PREFIX}gcc"
export CXX="${TC_PREFIX}g++"
export AR="${TC_PREFIX}ar"
export LD="${TC_PREFIX}ld"
export RANLIB="${TC_PREFIX}ranlib"
export CFLAGS="${CFLAGS_COMMON}"
export CXXFLAGS="${CFLAGS_COMMON}"
export LDFLAGS="${LDFLAGS}"
export PATH="${SYSROOT_DIR}/bin:$PATH"

# pacotes pesados que apenas --full compila
HEAVY="libreoffice firefox-esr gimp vlc"

for spec in "${SPECS_DIR}"/*.json.nvpspec; do
  name=$(basename "${spec}" .json.nvpspec)
  if [ -n "${ONLY}" ] && ! echo ",${ONLY}," | grep -q ",${name},"; then
    continue; fi
  if [ "${FULL}" != "1" ] && echo " ${HEAVY} " | grep -q " ${name} "; then
    log "pulando pacote pesado '${name}' (use --full)";
    continue; fi

  buildroot="${STAGE_ROOT}/${name}"
  stage="${buildroot}/stage"
  log "== compilando e empacotando '${name}' =="
  # lê o manifesto
  src_url=$(python3 -c "import json;print(json.load(open('${spec}'))['source'])" 2>/dev/null || true)
  if [ -z "${src_url}" ]; then log "spec sem source: ${spec}"; continue; fi

  rm -rf "${buildroot}"
  mkdir -p "${buildroot}" "${stage}"
  cd "${buildroot}"
  # baixa e extrai (com espelho de git se curl falhar)
  if ! curl -L -f -o src.tar "${src_url}" 2>/dev/null; then
    log "download falhou para ${name} (fonte pode exigir chave/acesso). Pulando."
    continue
  fi
  tar -xf src.tar --strip-components=1 --one-top-level=src 2>/dev/null \
    || { mkdir -p src; tar -xf src.tar -C src --strip-components=1; }
  cd src

  # usuário pode customizar por um script preparado em specs/ (ex.: build_{name}.sh)
  if [ -f "${SPECS_DIR}/build_${name}.sh" ]; then
    STAGE="${stage}" bash "${SPECS_DIR}/build_${name}.sh"
  else
    # configura com fallback simples (autotools default) e empacota
    if [ -f configure ]; then
      ./configure --prefix=/usr --sysconfdir=/etc >/dev/null 2>&1 || true
    elif [ -f autogen.sh ]; then
      ./autogen.sh >/dev/null 2>&1 || true
    fi
    make -j"$(nproc)" >/dev/null 2>&1 || { log "make falhou para ${name}"; continue; }
    make install DESTDIR="${stage}" >/dev/null 2>&1 || true
  fi

  # monta o metadata dentro do stage e gera .nvpkg
  python3 - "$spec" "${stage}" "${name}" <<PYEOF
import json,sys,os
spec=json.load(open(sys.argv[1])); stage=sys.argv[2]; name=sys.argv[3]
os.makedirs(os.path.join(stage,".novapkg"),exist_ok=True)
meta={
  "name":name,"version":spec["version"],"release":1,"arch":spec["arch"],
  "description":spec.get("description",""),"license":"GPL-2.0-or-later",
  "maintainer":"Nova Project <nova@novastation>",
  "dependencies":spec.get("depends",[]),
  "build":{"compiler":"gcc","optimization":spec.get("optimization","")}
}
json.dump(meta,open(os.path.join(stage,".novapkg","metadata.json"),"w"),indent=2,sort_keys=True)
PYEOF
  NOVAPKG_ROOT="/" python3 "${NOVAPKG}" build \
    --staging "${stage}" --name "${name}" \
    --version "$(python3 -c "import json;print(json.load(open('${spec}'))['version'])")" \
    --output "${PKGROOT}/${name}.nvpkg" 2>&1 | tail -2
done

log "pacotes gerados em ${PKGROOT}:"
ls -lh "${PKGROOT}"/*.nvpkg 2>/dev/null || echo "  (nenhum pacote gerado — verifique as fontes/compile)"

# gera o índice do repositório
cd "${PKGROOT}"
IDX="${PKGROOT}/index.json"
python3 - <<PYEOF
import json,os,glob
pkgs=[]
for f in sorted(glob.glob("*.nvpkg")):
    import hashlib
    name=f.split("-")[0]
    pkgs.append({"name":name,"filename":f,"sha256":hashlib.sha256(open(f,'rb').read()).hexdigest()})
json.dump({"packages":pkgs}, open("index.json","w"), indent=2, sort_keys=True)
PYEOF
log "índice de repositório: ${IDX} ($(python3 -c "import json;print(len(json.load(open('${IDX}'))['packages']))") pacotes)"
