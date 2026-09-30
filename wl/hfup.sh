#!/bin/bash
set -eux
HF_USER="$1"; HF_REPO="$2"
[ -s W.apk ] || { echo "no W.apk to upload"; exit 1; }
pip install -q -q huggingface_hub 2>&1 | tail -2
python3 - <<PY
import os,sys,huggingface_hub as h
tok=os.environ["HF_TOKEN"]
repo_id=f"{os.environ['HF_USER']}/{os.environ['HF_REPO']}"
api=h.HfApi(token=tok)
try:
    api.create_repo(repo_id=repo_id,repo_type="model",private=True,exist_ok=True)
except Exception as e:
    print("create_repo warn:",e)
for f in ["W.apk","W.sha256"]:
    if os.path.exists(f):
        print("upload",f,"->",repo_id)
        api.upload_file(path_or_fileobj=f,path_in_repo=f,repo_id=repo_id,repo_type="model",commit_message=f"upload {f}")
print("HF_UPLOAD_OK",repo_id)
PY
