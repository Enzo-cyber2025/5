#!/usr/bin/env python3
import json,sys
from evaluate_expanded_weights import evaluate_protocol,ENV
ON={**ENV,'GGUF_REPACK_WEIGHTS':'1'}
VERIFY={**ON,'GGUF_VERIFY_REPACKED_WEIGHTS':'1'}
def evaluate(s):
    return evaluate_protocol(s,kind='repacked',on=ON,verify=VERIFY,precision='Q8_LOSSLESS')
if __name__=='__main__':
    if not __debug__:raise RuntimeError('Assertions required')
    r=evaluate(json.load(open(sys.argv[1])));print(json.dumps(r,indent=2))
    raise SystemExit(0 if r['target_2x_passed'] else 1)
