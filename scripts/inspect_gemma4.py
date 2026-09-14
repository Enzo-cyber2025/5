#!/usr/bin/env python3
"""Actual public Gemma4 weights through app's Java GGUF merger; no native approval."""
import hashlib,json,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path('.cache/llama-mobile/gguf-py').resolve()))
from gguf import GGUFReader

def hashes(p):
    return {t.name:{'shape':t.shape.tolist(),'type':int(t.tensor_type),'sha256':hashlib.sha256(t.data).hexdigest()} for t in GGUFReader(str(p)).tensors}

def main():
    e=Path('evidence');e.mkdir(exist_ok=True)
    base=Path('.cache/gemma4-models');a=base/'gemma-4-E2B-it-Q3_K_S.gguf';b=base/'mmproj-F16.gguf';out=base/'combined.gguf'
    java=['java','-cp','.cache/gemma4-classes','com.ggufchat.app.GgufFile']
    result={'status':'FAIL','scope':'Gemma4 actual-weight Java merger, not Android/native execution'}
    try:
        result['input_analysis']=[subprocess.check_output(java+[str(p)],text=True).strip() for p in (a,b)]
        assert 'VISION_PROJECTOR' in result['input_analysis'][1]
        result['output_analysis']=subprocess.check_output(java+list(map(str,(a,b,out))),text=True).strip()
        assert 'VISION_SINGLE_GGUF' in result['output_analysis']
        expected=hashes(a);vision=hashes(b);assert not set(expected)&set(vision);expected.update(vision)
        assert hashes(out)==expected
        r=GGUFReader(str(out))
        result.update(status='PASS',size=out.stat().st_size,tensor_count=len(expected),tensors=expected,
                      metadata={k:r.fields[k].contents() for k in ('general.architecture','clip.has_vision_encoder','clip.has_audio_encoder','clip.vision.projector_type','clip.audio.projector_type','clip.vision.projection_dim')})
        with out.open('rb') as f:result['unified_sha256']=hashlib.file_digest(f,'sha256').hexdigest()
    finally:
        (e/'physical-gemma4-host.json').write_text(json.dumps(result,indent=2))
        print(json.dumps({k:v for k,v in result.items() if k!='tensors'},indent=2))

if __name__=='__main__':main()
