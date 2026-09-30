#!/bin/bash
set -ux
: > hf.log
exec > >(tee -a hf.log) 2>&1
HF_REPO="${1-winlator-a55-beam}"
[ -n "${HF_TOKEN-}" ] || { echo "no HF_TOKEN"; exit 1; }
[ -s W.apk ] || { echo "no W.apk"; exit 1; }
python3 -m venv /tmp/hfvenv 2>&1 | tail -3
/tmp/hfvenv/bin/pip install -q --upgrade pip 2>&1 | tail -2
/tmp/hfvenv/bin/pip install -q "huggingface_hub" 2>&1 | tail -5
T0=$(date +%s)
/tmp/hfvenv/bin/python3 -u - <<PY
import os,sys,traceback,time
try:
  import huggingface_hub as h
  tok=os.environ["HF_TOKEN"]
  t0=time.time()
  repo=os.environ.get("HF_REPO","winlator-a55-beam")
  api=h.HfApi(token=tok)
  who=api.whoami(); user=who["name"]; print("HF whoami:",user)
  repo_id=f"{user}/{repo}"
  print("repo_id:",repo_id)
  try:
    api.create_repo(repo_id=repo_id,repo_type="model",private=True,exist_ok=True)
    print("create_repo ok")
  except Exception as e:
    print("create_repo warn:",repr(e))
  for f in ["W.apk","W.sha256"]:
    if os.path.exists(f):
      sz=os.path.getsize(f); print("uploading",f,"size",sz,"at",time.time()-T0,"s")
      api.upload_file(path_or_fileobj=f,path_in_repo=f,repo_id=repo_id,repo_type="model",
                      commit_message=f"port {f}")
      print("ok",f,"at",time.time()-t0,"s")
  print("HF_UPLOAD_OK https://huggingface.co/"+repo_id)
except Exception as e:
  traceback.print_exc(); sys.exit(2)
PY
RC=$?
echo HF_UPLOAD_DONE rc=$RC elapsed=$(( $(date +%s) - T0 ))
exit $RC
