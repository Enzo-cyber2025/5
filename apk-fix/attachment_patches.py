"""Hooks into the original activity, preserving its native generation lifecycle."""
from unified_mobile import replace_method


def patch_attachments(app):
    p=app/'ChatActivity.smali';s=p.read_text()
    s=replace_method(s,'.method private pickAttachment(Ljava/lang/String;)V','''    .locals 0
    invoke-static {p0, p1}, Lcom/ggufchat/app/Attachments;->pickLegacy(Landroid/app/Activity;Ljava/lang/String;)V
    return-void''')
    s=replace_method(s,'.method private handleAttachment(Landroid/net/Uri;)V','''    .locals 0
    invoke-static {p0, p1}, Lcom/ggufchat/app/Attachments;->single(Landroid/app/Activity;Landroid/net/Uri;)V
    return-void''')
    s=replace_method(s,'.method protected onActivityResult(IILandroid/content/Intent;)V','''    .locals 0
    invoke-super {p0, p1, p2, p3}, Landroid/app/Activity;->onActivityResult(IILandroid/content/Intent;)V
    invoke-static {p0, p1, p2, p3}, Lcom/ggufchat/app/Attachments;->result(Landroid/app/Activity;IILandroid/content/Intent;)V
    return-void''')
    start=s.index('.method private onSend()V');end=s.index('.end method',start)
    part=s[start:end]
    # Original formatter inverted both isEmpty branches, losing non-empty text
    # whenever a pending attachment was present.
    for label in ('cond_3','cond_5'):
        old='    if-eqz v4, :'+label
        assert part.count(old)==1
        part=part.replace(old,'    if-nez v4, :'+label)
    part=part.replace('    .prologue','''    .prologue
    invoke-static {p0}, Lcom/ggufchat/app/Attachments;->prepareSend(Landroid/app/Activity;)Z
    move-result v0
    if-nez v0, :attachments_ready
    return-void
    :attachments_ready''',1)
    marker='    invoke-direct {p0}, Lcom/ggufchat/app/ChatActivity;->save()V'
    assert part.count(marker)==1
    part=part.replace(marker,marker+'\n    invoke-static {p0}, Lcom/ggufchat/app/Attachments;->sent(Landroid/app/Activity;)V')
    s=s[:start]+part+s[end:]
    start=s.index('.method protected onResume()V');end=s.index('.end method',start)
    part=s[start:end].replace('    return-void','    invoke-static {p0}, Lcom/ggufchat/app/Attachments;->resume(Landroid/app/Activity;)V\n    return-void')
    p.write_text(s[:start]+part+s[end:])
    p=app/'ChatStore.smali';s=p.read_text()
    start=s.index('.method public static delete(');end=s.index('.end method',start)
    part=s[start:end];marker='    .line 88\n    return-void'
    assert part.count(marker)==1
    part=part.replace(marker,'    .line 88\n    goto/16 :attachments_deleted')
    part+='\n    :attachments_deleted\n    invoke-static {p0, p1}, Lcom/ggufchat/app/Attachments;->deleteChat(Landroid/content/Context;Ljava/lang/String;)V\n    return-void\n'
    p.write_text(s[:start]+part+s[end:])

    p=app/'GenerationService.smali';s=p.read_text()
    marker='    invoke-static {v4, v5, v6}, Lcom/ggufchat/app/PromptBuilder;->renderPrompt(JLjava/util/List;)Ljava/lang/String;'
    assert s.count(marker)==1
    s=s.replace(marker,'''    move-object/from16 v0, p0
    move-object/from16 v1, v18
    move-wide v2, v4
    move-object v4, v6
    invoke-static {v0, v1, v2, v3, v4}, Lcom/ggufchat/app/AttachmentInference;->prepare(Landroid/content/Context;Ljava/lang/Object;JLjava/util/List;)Ljava/lang/String;
    move-result-object v6
    move-wide v4, v2
    # Original move-result below must remain directly after a result-producing invocation.
    invoke-static {v6}, Lcom/ggufchat/app/AttachmentInference;->identity(Ljava/lang/String;)Ljava/lang/String;''')
    old='Lcom/ggufchat/app/Native;->generate(JLjava/lang/String;IFFFFFIILcom/ggufchat/app/Native$GenerateCallback;)Z'
    assert s.count(old)==1
    s=s.replace(old,'Lcom/ggufchat/app/AttachmentInference;->generate(JLjava/lang/String;IFFFFFIILjava/lang/Object;)Z')
    p.write_text(s)
