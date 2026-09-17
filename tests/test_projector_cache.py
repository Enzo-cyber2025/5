"""Host cache/key tests: synthetic inputs, not GPU/model performance evidence."""
from pathlib import Path
import subprocess,sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'.cache/llama-mobile'
sys.path.insert(0,str(ROOT/'apk-fix'))
from projector_patches import IMPL,patch_projector

def test_bounded_lru_exact_bytes_and_ownership(tmp_path):
    cpp=tmp_path/'cache.cpp';cpp.write_text(r'''
#include "image_embedding_cache.h"
#include <cassert>
#include <cstring>
#include <limits>
int main(){
 ImageEmbeddingCache c;ImageEmbeddingCache::Key a{},b{},d{};b[0]=1;d[0]=2;
 float values[]={-0.0f,1.25f,-17.0f};
 assert(!c.find(a,3));assert(c.store(a,values,3));
 assert(!memcmp(c.find(a,3),values,sizeof(values)));assert(!c.find(a,2));
 assert(c.store(b,values,3));assert(c.find(a,3)); // adding B doesn't discard A
 assert(!c.store(d,values,std::numeric_limits<size_t>::max()));
 assert(!c.store(d,nullptr,1));assert(!c.store(d,values,0));
 for(int i=2;i<128;i++){d[0]=i;assert(c.store(d,values,3));}
 assert(c.size()==128);assert(c.find(a,3));d[0]=128;assert(c.store(d,values,3));
 assert(c.find(a,3)&&!c.find(b,3));assert(c.size()==128);
 c.clear();assert(c.bytes()==0&&!c.find(a,3));
 std::vector<float> big(ImageEmbeddingCache::capacity_bytes/sizeof(float),2.5f);
 assert(c.store(a,big.data(),big.size()));assert(c.bytes()==ImageEmbeddingCache::capacity_bytes);
 assert(c.store(b,values,3));assert(!c.find(a,big.size()));assert(c.bytes()==sizeof(values));
 ImageEmbeddingCache other;assert(!other.find(b,3));
}''')
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror','-I'+str(ROOT/'apk-fix/native'),str(cpp),'-o',str(tmp_path/'cache')],check=True)
    subprocess.run([str(tmp_path/'cache')],check=True)

def test_fingerprint_real_pinned_types_pixels_geometry_and_placeholders(tmp_path):
    if not (SRC/'tools/mtmd/mtmd.cpp').exists():pytest.skip('Pinned source required')
    text=(SRC/'tools/mtmd/mtmd.cpp').read_text()
    # Compile the ACTUAL pinned type/serializer definitions, not hand-written doubles.
    serializer=text[text.index('#define MTMD_SERIALIZATION_VERSION'):text.index('// for still image data')]
    types=text[text.index('enum mtmd_pos_type'):text.index('struct mtmd_input_chunks {')]
    cpp=tmp_path/'key.cpp';cpp.write_text('''#include "clip-impl.h"
#include "mtmd.h"
#include "mtmd-internal.h"
#include <cstring>
#include <type_traits>
#include <cassert>
'''+serializer+types+IMPL+r'''
int main(){
 mtmd_input_chunk c{};c.type=MTMD_INPUT_CHUNK_TYPE_IMAGE;
 c.tokens_image=std::make_unique<mtmd_image_tokens>();
 auto &im=*c.tokens_image;im.nx=1;im.ny=1;im.id="same-source-id";
 clip_image_f32 p;p.set_size({2,2},false,false);p.cpy_buf(std::vector<float>(12,0.5f));
 im.batch_f32.entries.push_back(p);
 unsigned char a[32],b[32];
 assert(mtmd_gguf_image_fingerprint(&c,a)==0);
 assert(mtmd_gguf_image_fingerprint(&c,b)==0&&!memcmp(a,b,32));
 // Same source ID and dimensions, DIFFERENT actual prepared pixel.
 auto pixels=im.batch_f32.entries[0].get_ro_buf();pixels[0]=0.25f;
 im.batch_f32.entries[0].cpy_buf(pixels);
 assert(mtmd_gguf_image_fingerprint(&c,b)==0&&memcmp(a,b,32));
 im.batch_f32.entries[0]=p;
 // anyres geometry is excluded from upstream serialization: our key must cover it.
 mtmd_serialization oldmeta(MTMD_SERIALIZATION_VERSION);c.serialize(oldmeta);
 im.batch_f32.entries[0].anyres.grid_x=2;
 mtmd_serialization newmeta(MTMD_SERIALIZATION_VERSION);c.serialize(newmeta);
 assert(oldmeta.data==newmeta.data);
 assert(mtmd_gguf_image_fingerprint(&c,b)==0&&memcmp(a,b,32));
 im.batch_f32.entries[0]=p;im.batch_f32.entries[0].lead_pad=1;
 assert(mtmd_gguf_image_fingerprint(&c,b)==0&&memcmp(a,b,32));
 im.batch_f32.entries[0]=p;im.image_idx=1;
 assert(mtmd_gguf_image_fingerprint(&c,b)==0&&memcmp(a,b,32));
 im.image_idx=0;im.id="different-id";
 assert(mtmd_gguf_image_fingerprint(&c,b)==0&&memcmp(a,b,32));
 im.id="same-source-id";im.batch_f32.entries[0].set_size({2,2},true,false);
 assert(mtmd_gguf_image_fingerprint(&c,b)!=0);
 assert(mtmd_gguf_image_fingerprint(nullptr,b)!=0);
 c.type=MTMD_INPUT_CHUNK_TYPE_TEXT;assert(mtmd_gguf_image_fingerprint(&c,b)!=0);
}''')
    h=SRC/'vendor/hash'
    subprocess.run(['gcc','-I'+str(h),'-c',str(h/'sha256/sha256.c'),'-o',str(tmp_path/'sha.o')],check=True)
    subprocess.run(['g++','-std=c++17','-O2','-ffunction-sections','-fdata-sections','-Wl,--gc-sections','-I'+str(SRC/'ggml/include'),'-I'+str(SRC/'include'),'-I'+str(SRC/'tools/mtmd'),'-I'+str(SRC/'vendor'),str(cpp),str(tmp_path/'sha.o'),'-o',str(tmp_path/'key')],check=True)
    subprocess.run([str(tmp_path/'key')],check=True)

def test_native_retains_positions_and_separates_verification_from_speed():
    s=(ROOT/'apk-fix/native/mobile.cpp').read_text()
    assert 'image_set_id' not in s and 'image_ordinal' not in s
    assert 'mtmd_gguf_image_fingerprint(chunk,key.data())' in s
    assert 'std::memcmp(embd,mtmd_get_output_embd' in s
    assert 'GGUF_VERIFY_IMAGE_EMBED_CACHE' in s and 'verification=%d' in s
    assert 'mtmd_helper_decode_image_chunk(e->projector,e->ctx,chunk,embd,past,0' in s
    assert 'cp.n_batch=128; cp.n_ubatch=32;' in s
    assert 'e->image_cache.clear();' in s[s.index('} catch(const std::exception &ex)'):]

def test_patch_is_idempotent_and_rejects_stale_implementation(tmp_path):
    if not (SRC/'tools/mtmd/mtmd.cpp').exists():pytest.skip('Pinned source required')
    target=tmp_path/'tools/mtmd';target.mkdir(parents=True)
    for name in ('mtmd.cpp','mtmd.h'):(target/name).write_bytes((SRC/'tools/mtmd'/name).read_bytes())
    patch_projector(tmp_path)
    before={p.name:p.read_bytes() for p in target.iterdir()}
    patch_projector(tmp_path)
    assert before=={p.name:p.read_bytes() for p in target.iterdir()}
    cpp=target/'mtmd.cpp';cpp.write_text(cpp.read_text().replace('GGUF-PREPARED-VISION-1','WRONG-KEY-PROTOCOL'))
    with pytest.raises(AssertionError,match='Stale projector'):patch_projector(tmp_path)

def test_cache_allocation_failure_drops_optional_cache_not_inference(tmp_path):
    cpp=tmp_path/'oom.cpp';cpp.write_text(r'''
#include "image_embedding_cache.h"
#include <cassert>
#include <cstdlib>
static bool fail=false;
void *operator new(size_t n){if(fail){fail=false;throw std::bad_alloc();}if(void *p=std::malloc(n?n:1))return p;throw std::bad_alloc();}
void operator delete(void *p)noexcept{std::free(p);}
void operator delete(void *p,size_t)noexcept{std::free(p);}
int main(){
 ImageEmbeddingCache c;ImageEmbeddingCache::Key a{},b{};b[0]=1;
 float actual[]={1.0f,2.0f,3.0f};assert(c.store(a,actual,3));
 fail=true;assert(!c.store(b,actual,3));assert(!fail);
 assert(c.bytes()==0&&c.size()==0);assert(actual[0]==1.0f&&actual[2]==3.0f);
 assert(c.store(b,actual,3));assert(c.find(b,3));
}''')
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror','-I'+str(ROOT/'apk-fix/native'),str(cpp),'-o',str(tmp_path/'oom')],check=True)
    subprocess.run([str(tmp_path/'oom')],check=True)
