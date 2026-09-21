import copy,random,struct,subprocess,sys,shutil
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'apk-fix'),str(ROOT/'ci')]
from repack_q5_patches import patch,apply
from evaluate_repacked_weights import evaluate,ON,VERIFY
from test_expanded_weights import fixture as expanded_fixture


def reference_block(block):
    high=int.from_bytes(block[2:6],'little')
    values=[]
    for lane in range(32):
        low=(block[6+lane%16]>>(0 if lane<16 else 4))&15
        values.append((low|(((high>>lane)&1)<<4))-16)
    return block[:2]+struct.pack('32b',*values)


def shader_layout(source,prefix_words=0):
    # Integer-equivalent host model of the shader, NOT a GPU execution claim.
    storage=bytes(4*prefix_words)+source
    words=struct.unpack('<'+'I'*(len(storage)//4),storage)
    def byte_at(i):return (words[prefix_words+i//4]>>((i%4)*8))&255
    def out_byte(pair,index):
        block,lane=divmod(index,34);base=pair*44+block*22
        if lane<2:return byte_at(base+lane)
        lane-=2;packed=byte_at(base+6+lane%16)
        low=packed&15 if lane<16 else packed>>4
        high=(byte_at(base+2+lane//8)>>(lane%8))&1
        return ((low|(high<<4))-16)&255
    out=[]
    for pair in range(len(source)//44):
        for word in range(17):out.append(sum(out_byte(pair,word*4+i)<<(8*i) for i in range(4)))
    return struct.pack('<'+'I'*len(out),*out)


def test_lossless_integer_layout_all_codes_high_bits_signed_scales_offsets():
    rng=random.Random(7)
    blocks=[]
    for scale in [0,0x8000,1,0x3c00,0xbc00,0x7bff,0x0400,0x3555]:
        for high in [0,0xffffffff,0xaaaaaaaa,0x55555555]:
            for low in range(16):blocks.append(struct.pack('<HI',scale,high)+bytes([low|(15-low)<<4])*16)
    blocks += [rng.randbytes(22) for _ in range(256)]
    source=b''.join(blocks);expected=b''.join(map(reference_block,blocks))
    for offset in [0,1,16,256]:assert shader_layout(source,offset)==expected
    for a,b in zip(blocks,[expected[i:i+34] for i in range(0,len(expected),34)]):assert a[:2]==b[:2]


def test_patch_is_idempotent_and_guarded_on_real_pinned_backend(tmp_path):
    sources=[ROOT/'.cache/llama-mobile',ROOT/'.cache/llama-prefix-audit']
    src=next((p for p in sources if (p/'ggml/src/ggml-vulkan/ggml-vulkan.cpp').exists()),None)
    if src is None:pytest.skip('Pinned upstream absent')
    rel=Path('ggml/src/ggml-vulkan');dst=tmp_path/rel;dst.mkdir(parents=True)
    (dst/'vulkan-shaders').mkdir()
    for f in ['ggml-vulkan.cpp','vulkan-shaders/vulkan-shaders-gen.cpp']:
        # Restore pristine tracked content even if builder already patched it.
        original=subprocess.check_output(['git','-C',str(src),'show','HEAD:'+str(rel/f)])
        (dst/f).write_bytes(original)
    apply(tmp_path);s=(dst/'ggml-vulkan.cpp').read_text();assert patch(s)==s
    assert 'get_misalign_bytes' in s and 'a%4==0 && d%4==0' in s
    assert '64LL*64*65535' in s and 'GGML_REPACK_FAKE' not in s
    assert (dst/'vulkan-shaders/gguf_repack_q5.comp').read_text()==(ROOT/'apk-fix/repack_q5.comp').read_text()


def test_shader_compiles_when_real_compiler_available(tmp_path):
    if not shutil.which('glslc'):pytest.skip('Shader compiler absent locally; required in Android build')
    subprocess.run(['glslc','--target-env=vulkan1.2','-o',str(tmp_path/'repack.spv'),str(ROOT/'apk-fix/repack_q5.comp')],check=True,capture_output=True)


def fixture():
    s=expanded_fixture();s['status']='COMPLETE_REPACKED_OBSERVATIONS'
    s['build']['experiment'].pop('experimental_expanded_weights_build')
    s['build']['experiment']['experimental_repacked_weights_build']=True
    s['proof']['vulkan_environment']=VERIFY.copy();s['proof']['expansion'].update(precision='Q8_LOSSLESS',verified_bytes=256000000,extra_device_bytes=70000000)
    for pair in s['pairs']:
        pair['candidate']['vulkan_environment']=ON.copy()
        pair['candidate']['expansion'].update(precision='Q8_LOSSLESS',extra_device_bytes=70000000)
    return s


def test_distinct_provenance_preserves_historical_2x_target():
    r=evaluate(fixture());assert r['target_2x_passed'] and not r['release_approved']
    s=fixture();s['proof']['expansion']['precision']='F32'
    with pytest.raises(AssertionError):evaluate(s)
    with pytest.raises(AssertionError):evaluate(expanded_fixture())
    s=fixture();s['proof']['expansion']['extra_device_bytes']=1
    with pytest.raises(AssertionError):evaluate(s)
