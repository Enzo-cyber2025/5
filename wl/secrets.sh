#!/bin/bash
_deob(){
  python3 -c "
import base64,sys
def deob(s,key='wl-a55-beam'):
  s=s+'='*(-len(s)%4)
  b=base64.urlsafe_b64decode(s.encode());k=key.encode()
  sys.stdout.write(bytes(b[i]^k[i%len(k)] for i in range(len(b))).decode())
deob(sys.argv[1])" "$1"
}
export HF_TOKEN=$(_deob "$(awk -F= '/^HF=/{print $2}' wl/.tk)")
export KAGGLE_KEY=$(_deob "$(awk -F= '/^KG=/{print $2}' wl/.tk)")
export KAGGLE_USERNAME="enzocyber2025"
