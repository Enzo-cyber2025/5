"""Incremental TextView updates: no full-response copy/replace/substrings per chunk."""
from unified_mobile import replace_method

def patch_latency_ui(app):
    p=app/'ChatActivity.smali';s=p.read_text()
    s=replace_method(s,'.method private onToken(Ljava/lang/String;)V','''    .locals 2
    iget-boolean v0, p0, Lcom/ggufchat/app/ChatActivity;->generating:Z
    if-eqz v0, :finished
    iget-object v0, p0, Lcom/ggufchat/app/ChatActivity;->streamingBuf:Ljava/lang/StringBuilder;
    invoke-virtual {v0, p1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    iget-object v0, p0, Lcom/ggufchat/app/ChatActivity;->streamingView:Landroid/widget/TextView;
    if-eqz v0, :finished
    invoke-virtual {v0, p1}, Landroid/widget/TextView;->append(Ljava/lang/CharSequence;)V
    invoke-direct {p0}, Lcom/ggufchat/app/ChatActivity;->scrollToBottom()V
    :finished
    return-void''')
    p.write_text(s)
