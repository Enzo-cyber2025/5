#!/bin/bash
set -u
exec > >(tee -a hf.log) 2>&1
HF_USER="${1:-${HF_USER:-${GITHUB_REPOSITORY_OWNER,,}}}"
HF_REPO="${2:-winlator-a55-beam}"
echo "HF_UPLOAD start user=$HF_USER repo=$HF_REPO tok_len=${#HF_TOKEN}"
[ -n "$HF_TOKEN" ] || { echo "no HF_TOKEN"; exit 1; }
[ -s W.apk ] || { echo "no W.apk"; exit 1; }
pip install -q --break-system-packages huggingface_hub 2>&1 | tail -3
python3 -u - <<PY
import os,sys,traceback
try:
  import huggingface_hub as h
  tok=os.environ["HF_TOKEN"]
  user=os.environ.get("HF_USER","").strip().lower()
  repo=os.environ.get("HF_REPO","winlator-a55-beam").strip()
  if not user:
    who=h.HfApi(token=tok).whoami()
    user=who["name"]; print("HF whoami:",user)
  repo_id=f"{user}/{repo}"
  print("repo_id:",repo_id)
  api=h.HfApi(token=tok)
  api.create_repo(repo_id=repo_id,repo_type="model",private=True,exist_ok=True)
  for f in ["W.apk","W.sha256"]:
    if os.path.exists(f):
      print("uploading",f,"size",os.path.getsize(f))
      api.upload_file(path_or_fileobj=f,path_in_repo=f,repo_id=repo_id,repo_type="model",commit_message=f"port {f}")
      print("ok",f)
  print("HF_UPLOAD_OK https://huggingface.co/"+repo_id)
except Exception as e:
  traceback.print_exc()
  sys.exit(2)
PY
echo HF_UPLOAD_DONE
