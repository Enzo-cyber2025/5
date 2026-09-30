#!/bin/bash
set -ux
HF_USER="${1:-${HF_USER-${GITHUB_REPOSITORY_OWNER,,}}}"
HF_REPO="${2:-winlator-a55-beam}"
: > hf.log
exec > >(tee -a hf.log) 2>&1
echo "HF_UPLOAD start user=$HF_USER repo=$HF_REPO tok_len=${#HF_TOKEN}"
[ -n "${HF_TOKEN-}" ] || { echo "no HF_TOKEN"; exit 1; }
[ -s W.apk ] || { echo "no W.apk"; exit 1; }
# Venv para o huggingface_hub (evita PEP 668)
python3 -m venv /tmp/hfvenv 2>&1 | tail -3
/tmp/hfvenv/bin/pip install -q --upgrade pip 2>&1 | tail -2
/tmp/hfvenv/bin/pip install -q "huggingface_hub[cli,hf_transfer]" 2>&1 | tail -5
export HF_HUB_ENABLE_HF_TRANSFER=0
/tmp/hfvenv/bin/python3 -u - <<PY
import os,sys,traceback,time
t0=time.time()
try:
  import huggingface_hub as h
  tok=os.environ["HF_TOKEN"]; user=os.environ.get("HF_USER","").strip().lower()
  repo=os.environ.get("HF_REPO","winlator-a55-beam").strip()
  if not user:
    who=h.HfApi(token=tok).whoami(); user=who["name"]; print("HF whoami:",user)
  repo_id=f"{user}/{repo}"; print("repo_id:",repo_id)
  api=h.HfApi(token=tok,timeout=600)
  try: api.create_repo(repo_id=repo_id,repo_type="model",private=True,exist_ok=True)
  except Exception as e: print("create_repo warn:",e)
  for f in ["W.apk","W.sha256"]:
    if os.path.exists(f):
      sz=os.path.getsize(f); print("uploading",f,"size",sz,"at",time.time()-t0,"s")
      api.upload_file(path_or_fileobj=f,path_in_repo=f,repo_id=repo_id,repo_type="model",
                      commit_message=f"port {f}")
      print("ok",f,"at",time.time()-t0,"s")
  print("HF_UPLOAD_OK https://huggingface.co/"+repo_id)
except Exception as e:
  traceback.print_exc(); sys.exit(2)
PY
RC=$?
echo HF_UPLOAD_DONE rc=$RC elapsed=$(( $(date +%s) - t0 ))
exit $RC
