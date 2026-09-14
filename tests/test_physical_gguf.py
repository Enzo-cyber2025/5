"""Execute real Java GGUF parser/writer with synthetic structural fixtures.
Not an inference test; real model weights and native evaluation are tested on Android.
"""
from pathlib import Path
import struct
import subprocess
import shutil
import os
import pytest

ROOT=Path(__file__).resolve().parents[1]
JAVA=ROOT/'apk-fix/java/com/ggufchat/app/GgufFile.java'

def string(s):
    b=s.encode();return struct.pack('<Q',len(b))+b

def fixture(path,kind='language',alignment=32,extra=(),dual=False):
    metadata=[('general.architecture',8,'clip' if kind=='projector' else 'llama'),('general.alignment',4,alignment)]
    tensors=[]
    if kind!='projector':
        metadata += [('llama.embedding_length',4,4),('tokenizer.ggml.tokens',9,['test','<image>'] if kind=='tokens' else ['test'])]
        tensors += [('token_embd.weight',[4,8],bytes(range(128))),('blk.0.attn_q.weight',[4,4],bytes(range(64)))]
    if kind in ('projector','complete','declaration'):
        metadata += [('clip.has_vision_encoder',7,True),('clip.vision.projector_type' if dual else 'clip.projector_type',8,'gemma4v' if dual else 'idefics3'),('clip.vision.block_count',4,1),('clip.vision.projection_dim',4,4)]
        if kind!='declaration':tensors += [('v.blk.0.attn_q.weight',[2,2],b'V'*16),('mm.model.fc.weight',[4,4],b'M'*64)]
    if dual:
        metadata += [('clip.has_audio_encoder',7,True),('clip.audio.projector_type',8,'gemma4a')]
        tensors += [('a.blk.0.attn_q.weight',[2,2],b'A'*16)]
    metadata+=list(extra)
    header=b'GGUF'+struct.pack('<IQQ',3,len(tensors),len(metadata))
    for k,t,v in metadata:
        header+=string(k)+struct.pack('<I',t)
        header+=string(v) if t==8 else struct.pack('<?',v) if t==7 else struct.pack('<IQ',8,len(v))+b''.join(map(string,v)) if t==9 else struct.pack('<I',v)
    data=b''
    for name,dims,body in tensors:
        offset=len(data);header+=string(name)+struct.pack('<I',len(dims))+struct.pack('<'+'Q'*len(dims),*dims)+struct.pack('<IQ',0,offset)
        data+=body;data+=b'\0'*(-len(data)%alignment)
    header+=b'\0'*(-len(header)%alignment);path.write_bytes(header+data)
    return {n:b for n,d,b in tensors}

@pytest.fixture(scope='module')
def java(tmp_path_factory):
    if os.environ.get('GGUF_READER_JAR'):
        import jdk4py
        return [str(jdk4py.JAVA_HOME/'bin/java'),'-cp',os.environ['GGUF_READER_JAR'],'com.ggufchat.app.GgufFile']
    javac=shutil.which('javac')
    if not javac:pytest.skip('Real JDK compiler required; Android build CI installs JDK 17')
    tmp=tmp_path_factory.mktemp('gguf-java')
    subprocess.run([javac,'--release','8','-d',str(tmp),str(JAVA)],check=True)
    return [shutil.which('java'),'-cp',str(tmp),'com.ggufchat.app.GgufFile']

def run(java,*args,ok=True):
    p=subprocess.run(java+list(map(str,args)),capture_output=True,text=True)
    assert (p.returncode==0)==ok,p.stdout+p.stderr
    return p.stdout+p.stderr

@pytest.mark.parametrize('kind,expected',[('language','TEXT_ONLY'),('tokens','IMAGE_TOKENS_ONLY'),('declaration','MULTIMODAL_DECLARED_INCOMPLETE'),('projector','VISION_PROJECTOR'),('complete','VISION_SINGLE_GGUF')])
def test_parameters_and_tensor_detection_ignores_filename(java,tmp_path,kind,expected):
    f=tmp_path/'mmproj-vision-multimodal.gguf';fixture(f,kind)
    assert expected in run(java,f)
    # Identical bytes, neutral external filename, no private marker required.
    renamed=tmp_path/'x.gguf';shutil.copyfile(f,renamed)
    assert run(java,renamed)==run(java,f)

def read_tensors(path):
    """Independent tiny fixture reader; validates output offsets and byte preservation."""
    import io
    f=io.BytesIO(path.read_bytes())
    def u(fmt):return struct.unpack('<'+fmt,f.read(struct.calcsize('<'+fmt)))[0]
    def s():return f.read(u('Q')).decode()
    assert f.read(4)==b'GGUF';assert u('I')==3;nt=u('Q');nk=u('Q');alignment=32
    for _ in range(nk):
        key=s();t=u('I')
        if t==8:v=s()
        elif t==7:v=u('?')
        elif t==4:v=u('I')
        elif t==9:
            assert u('I')==8;v=[s() for _ in range(u('Q'))]
        else:raise AssertionError(t)
        if key=='general.alignment':alignment=v
    tensors=[]
    for _ in range(nt):
        name=s();dims=[u('Q') for _ in range(u('I'))];assert u('I')==0;off=u('Q');assert off%alignment==0
        size=4
        for dim in dims:size*=dim
        tensors.append((name,off,size))
    start=(f.tell()+alignment-1)//alignment*alignment
    return {name:path.read_bytes()[start+off:start+off+size] for name,off,size in tensors}

def test_merge_is_one_valid_table_and_preserves_all_weights(java,tmp_path):
    a,b,out=[tmp_path/n for n in ('mmproj-misleading.gguf','ordinary.gguf','one.gguf')]
    tensors=fixture(a);tensors.update(fixture(b,'projector',64))
    before=(a.read_bytes(),b.read_bytes())
    assert 'VISION_SINGLE_GGUF' in run(java,a,b,out)
    assert read_tensors(out)==tensors
    assert (a.read_bytes(),b.read_bytes())==before
    assert out.read_bytes()!=before[0]+before[1]
    assert 'VISION_SINGLE_GGUF' in run(java,out)
    run(java,a,b,out,ok=False) # never overwrite an existing output

@pytest.mark.parametrize('damage',['truncate','bad_magic','big_endian','duplicate_key','dimensions','wrong_pair','projection_dimension'])
def test_bad_inputs_fail_and_do_not_publish_output(java,tmp_path,damage):
    a,b,out=[tmp_path/n for n in ('a.gguf','b.gguf','out.gguf')];fixture(a);fixture(b,'projector')
    if damage=='truncate':b.write_bytes(b.read_bytes()[:-40])
    elif damage=='bad_magic':b.write_bytes(b'bad!'+b.read_bytes()[4:])
    elif damage=='big_endian':b.write_bytes(b'FUGG'+b.read_bytes()[4:])
    elif damage=='duplicate_key':fixture(b,'projector',extra=[('clip.has_vision_encoder',7,True)])
    elif damage=='dimensions':b.write_bytes(b.read_bytes().replace(struct.pack('<Q',2)+struct.pack('<Q',2),struct.pack('<Q',2**63-1)+struct.pack('<Q',2**63-1),1))
    elif damage=='wrong_pair':fixture(b,'language')
    elif damage=='projection_dimension':b.write_bytes(b.read_bytes().replace(string('clip.vision.projection_dim')+struct.pack('<II',4,4),string('clip.vision.projection_dim')+struct.pack('<II',4,8)))
    run(java,a,b,out,ok=False);assert not out.exists()

def test_native_keeps_tensor_count_validation_and_single_file_memory_accounting():
    import sys
    sys.path.insert(0,str(ROOT/'apk-fix'))
    from physical_gguf import patch_combined_loader
    sample='    // Save tensors data offset of the main file.\n        std::string tensor_name = std::string(cur->name);\nif (n_created != n_tensors) throw error;'
    changed=patch_combined_loader(sample)
    assert 'if (n_created != n_tensors) throw error;' in changed
    assert 'GGUF_TYPE_BOOL' in changed and 'owner=mtmd' in changed
    assert patch_combined_loader(changed)==changed
    source=(ROOT/'apk-fix/native/mobile.cpp').read_text()
    assert 'projector_path==model_path?0:bytes(projector_path)' in source
    assert 'GGUF_SINGLE_FILE_LOADED same_path=1' in source


def test_dual_vision_audio_projector_and_complete_gguf(java,tmp_path):
    language,projector,out=[tmp_path/n for n in ('language.gguf','neutral.gguf','single.gguf')]
    tensors=fixture(language);tensors.update(fixture(projector,'projector',dual=True))
    assert 'VISION_PROJECTOR' in run(java,projector)
    assert 'VISION_SINGLE_GGUF' in run(java,language,projector,out)
    assert read_tensors(out)==tensors
    assert 'VISION_SINGLE_GGUF' in run(java,out)


def test_unknown_layout_is_not_assumed_to_be_a_second_language():
    source=(ROOT/'apk-fix/java/com/ggufchat/app/Pairing.java').read_text()
    assert 'GgufFile.read(new File(field(item,"path"))).pairingRole()' in source
    parser=JAVA.read_text()
    assert 'if(language()&&!visionWeights())return "language";' in parser
    assert 'componente não reconhecido como linguagem ou projetor compatível' in parser
