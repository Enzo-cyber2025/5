#!/usr/bin/env python3
"""Same three-control protocol; distinct immutable repack candidate/proof/flags."""
import sys
import test_expanded_weights_android as harness
from evaluate_repacked_weights import evaluate,ON,VERIFY
if __name__=='__main__':
    if not __debug__:raise RuntimeError('Assertions required')
    harness.evaluate=evaluate;harness.ON=ON;harness.VERIFY=VERIFY
    harness.MARKER='GGUF_REPACKED_WEIGHTS';harness.PRECISION='Q8_LOSSLESS';harness.NAME='repacked'
    harness.COMPLETE_STATUS='COMPLETE_REPACKED_OBSERVATIONS'
    harness.main(sys.argv[1])
