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
