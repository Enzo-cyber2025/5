"""Structural changes for single-record multimodal units (mobile APK only)."""
import re


def replace_method(s, signature, body):
    start=s.index(signature);end=s.index('.end method',start)+len('.end method')
    return s[:start]+signature+'\n'+body+'\n.end method'+s[end:]


def patch_unified_ui(app):
    p=app/'ModelStore.smali';s=p.read_text()
    signature='.method public static load(Landroid/content/Context;)Ljava/util/ArrayList;'
    assert s.count(signature)==1
    s=s.replace(signature,signature.replace(' load(', ' loadRecords('))
    s+='\n'+signature+'''
    .locals 1
    invoke-static {p0}, Lcom/ggufchat/app/Pairing;->loadUnified(Landroid/content/Context;)Ljava/util/ArrayList;
    move-result-object v0
    return-object v0
.end method
'''
    s=replace_method(s,'.method public static remove(Landroid/content/Context;Ljava/lang/String;)V','''    .locals 0
    invoke-static {p0, p1}, Lcom/ggufchat/app/Pairing;->removeUnified(Landroid/content/Context;Ljava/lang/String;)V
    return-void''')
    p.write_text(s)
    p=app/'MainActivity.smali';s=p.read_text()
    # No second ModelInfo lookup and no name-based guessing at chat creation.
    s=replace_method(s,'.method private finishNewChat(Lcom/ggufchat/app/ModelInfo;)V','''    .locals 1
    iget-object v0, p1, Lcom/ggufchat/app/ModelInfo;->mmprojPath:Ljava/lang/String;
    invoke-direct {p0, p1, v0}, Lcom/ggufchat/app/MainActivity;->createChat(Lcom/ggufchat/app/ModelInfo;Ljava/lang/String;)V
    return-void''')
    s=replace_method(s,'.method private hasVision(Lcom/ggufchat/app/ModelInfo;)Z','''    .locals 1
    invoke-static {p1}, Lcom/ggufchat/app/Pairing;->isUnified(Ljava/lang/Object;)Z
    move-result v0
    return v0''')
    start=s.index('.method private showModelPicker(');end=s.index('.end method',start)
    part=s[start:end]
    pattern=r'    iget-object ([vp]\d+), ([vp]\d+), Lcom/ggufchat/app/ModelInfo;->name:Ljava/lang/String;'
    part,n=re.subn(pattern,r'    invoke-static {\2}, Lcom/ggufchat/app/Pairing;->displayName(Ljava/lang/Object;)Ljava/lang/String;\n    move-result-object \1',part)
    assert n==1
    s=s[:start]+part+s[end:]
    s=s.replace('O projetor multimodal (mmproj) \\u00e9 detectado e vinculado automaticamente ao modelo de vis\\u00e3o.', 'Selecione juntos um GGUF e seu mmproj compat\\u00edvel para salvar um modelo \\u00fanico com \\ud83d\\udc41. Sem projetor, o modelo fica sem olho.')
    p.write_text(s)
    p=app/'Settings.smali';s=p.read_text();start=s.index('.method public static gpuLayers(');end=s.index('.end method',start)
    part=s[start:end];assert 'const/4 v2, 0x0' in part
    s=s[:start]+part.replace('const/4 v2, 0x0','const/16 v2, 0x63')+s[end:];p.write_text(s)
    # GPU load is strict. An explicit CPU choice still works, but a failed GPU
    # request must not retry silently with CPU and masquerade as GPU success.
    p=app/'EngineManager.smali';s=p.read_text()
    start=s.index('    if-eqz p4, :cond_6');end=s.index('    .line 38',start)
    assert s[start:end].count('Native;->create(')==1
    s=s[:start]+s[end:];p.write_text(s)


def patch_clip_gpu(s):
    """Pinned b6500: strict Vulkan projector plus actual weight-placement evidence."""
    if 'GGUF_PROJECTOR_WEIGHTS' in s:
        return s
    start=s.index('        if (ctx_params.use_gpu) {')
    end=s.index('\n        if (backend) {',start)
    s=s[:start]+'''        if (ctx_params.use_gpu) {
            // Match the language model's explicitly selected Vulkan device.
            try {
                backend = ggml_backend_init_by_name("Vulkan0", nullptr);
            } catch (...) {
                ggml_backend_free(backend_cpu);
                backend_cpu = nullptr;
                throw;
            }
            if (!backend) {
                ggml_backend_free(backend_cpu);
                backend_cpu = nullptr;
                throw std::runtime_error("Vulkan unavailable for projector; CPU fallback disabled");
            }
        }
''' + s[end:]
    marker='            ggml_backend_buffer_set_usage(ctx_clip.buf.get(), GGML_BACKEND_BUFFER_USAGE_WEIGHTS);'
    assert s.count(marker)==1
    s=s.replace(marker,'''            if (!ctx_clip.buf) throw std::runtime_error("Projector weight allocation failed");
'''+marker)
    marker='            fin.close();'
    assert s.count(marker)==1
    s=s.replace(marker,'''            if (!fin) throw std::runtime_error("Truncated projector tensor data");
'''+marker+'''
            LOG_INF("GGUF_PROJECTOR_WEIGHTS backend=%s bytes=%zu tensors=%zu\\n",
                    ggml_backend_name(ctx_clip.backend), ggml_backend_buffer_get_size(ctx_clip.buf.get()),
                    tensors_to_load.size());''')
    return s
