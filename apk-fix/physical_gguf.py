"""Pinned b6500: separate tensor ownership within ONE ordinary GGUF file."""
from unified_mobile import replace_method


def patch_combined_loader(s):
    if 'GGUF_SINGLE_FILE_MEDIA' in s:
        return s
    marker='    // Save tensors data offset of the main file.'
    assert s.count(marker)==1
    s=s.replace(marker,'''    // GGUF_SINGLE_FILE_MEDIA: clip metadata + language architecture, not filename.
    const int64_t vision_key = gguf_find_key(meta.get(), "clip.has_vision_encoder");
    const int64_t projector_key = gguf_find_key(meta.get(), "clip.projector_type");
    const bool combined_media = arch_name != "clip" && vision_key >= 0 && projector_key >= 0
        && gguf_get_kv_type(meta.get(), vision_key) == GGUF_TYPE_BOOL
        && gguf_get_val_bool(meta.get(), vision_key)
        && gguf_get_kv_type(meta.get(), projector_key) == GGUF_TYPE_STRING;
''' + marker)
    marker='        std::string tensor_name = std::string(cur->name);'
    assert s.count(marker) in (1,2)
    s=s.replace(marker,marker+'''
        // Leave vision/projector tensors to mtmd, which opens this SAME GGUF.
        // Do NOT disable the exact language tensor-count/shape checks below.
        if (combined_media && (tensor_name.rfind("v.", 0) == 0 || tensor_name.rfind("a.", 0) == 0
                || tensor_name.rfind("mm.", 0) == 0 || tensor_name.rfind("resampler.", 0) == 0
                || tensor_name.rfind("adapter.", 0) == 0 || tensor_name == "model.image_newline")) {
            LLAMA_LOG_INFO("GGUF_SINGLE_FILE_MEDIA tensor=%s owner=mtmd\\n", tensor_name.c_str());
            continue;
        }
''',1)
    return s


def extra_field(app,cls,name,helper):
    p=app/(cls+'.smali');s=p.read_text();idx=s.index('# direct methods')
    s=s[:idx]+f'.field public {name}:Ljava/lang/String;\n\n'+s[idx:]
    start=s.index('.method public static fromJson(');end=s.index('.end method',start)
    section=s[start:end];reg='v0' if cls=='ModelInfo' else 'v1'
    marker=f'    return-object {reg}'
    assert section.count(marker)==1
    section=section.replace(marker,f'    invoke-static {{{reg}, p0}}, Lcom/ggufchat/app/{helper};->readInfo(Ljava/lang/Object;Lorg/json/JSONObject;)V\n'+marker)
    s=s[:start]+section+s[end:]
    start=s.index('.method public toJson(');end=s.index('.end method',start)
    section=s[start:end];marker='    return-object v1';assert section.count(marker)==1
    section=section.replace(marker,f'    invoke-static {{p0, v1}}, Lcom/ggufchat/app/{helper};->writeInfo(Ljava/lang/Object;Lorg/json/JSONObject;)V\n'+marker)
    s=s[:start]+section+s[end:];p.write_text(s)


def patch_physical_ui(app):
    extra_field(app,'ModelInfo','capability','Pairing')
    extra_field(app,'Chat','systemPrompt','SystemPrompts')
    p=app/'MainActivity$14.smali';s=p.read_text();marker='    invoke-static {v0, v4}, Lcom/ggufchat/app/ModelStore;->add(Landroid/content/Context;Lcom/ggufchat/app/ModelInfo;)V';assert s.count(marker)==1
    s=s.replace(marker,'    invoke-static {v4}, Lcom/ggufchat/app/Pairing;->inspect(Ljava/lang/Object;)V\n'+marker);p.write_text(s)
    p=app/'MainActivity.smali';s=p.read_text();marker='    invoke-virtual {p0, v0}, Lcom/ggufchat/app/MainActivity;->setContentView(Landroid/view/View;)V';assert s.count(marker)==1
    s=s.replace(marker,'    invoke-static {p0, v0}, Lcom/ggufchat/app/SystemPrompts;->installGlobal(Landroid/app/Activity;Landroid/widget/LinearLayout;)V\n'+marker)
    start=s.index('.method private finishNewChat(');end=s.index('.end method',start)
    part=s[start:end].replace('    .locals 1','''    .locals 1
    invoke-static {}, Lcom/ggufchat/app/Pairing;->merging()Z
    move-result v0
    if-eqz v0, :merge_finished
    return-void
    :merge_finished''')
    s=s[:start]+part+s[end:]
    s=s.replace('Selecione juntos um GGUF e seu mmproj compat\\u00edvel para salvar um modelo \\u00fanico com \\ud83d\\udc41. Sem projetor, o modelo fica sem olho.', 'Selecione linguagem + projetor para criar um GGUF f\\u00edsico \\u00fanico, ou importe um GGUF completo. Vis\\u00e3o identificada por metadados e tensores; tokens de imagem n\\u00e3o bastam.')
    p.write_text(s)
