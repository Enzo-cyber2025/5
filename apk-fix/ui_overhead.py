"""UI-only patch; never modify native code, tensors, sampling or output budgets."""
from unified_mobile import replace_method


def scroll_patch(s):
    assert 'ScrollTail;->request(' not in s, 'Apply the scroll patch exactly once'
    return replace_method(s, '.method private scrollToBottom()V', '''    .locals 1
    iget-object v0, p0, Lcom/ggufchat/app/ChatActivity;->scroll:Landroid/widget/ScrollView;
    invoke-static {v0}, Lcom/ggufchat/app/ScrollTail;->request(Landroid/widget/ScrollView;)V
    return-void''')


def discard_unused_stream_buffer(s):
    """Only the obsolete UI copy: the service's authoritative reply is untouched.
    Fail closed if the delivered field has any additional reader or writer.
    """
    import re
    field='Lcom/ggufchat/app/ChatActivity;->streamingBuf:Ljava/lang/StringBuilder;'
    assert s.count(field)==4, 'Unexpected buffer use; review before deleting'
    assert s.count('.field private streamingBuf:Ljava/lang/StringBuilder;')==1
    s,n=re.subn(r'    iget-object v0, p0, '+re.escape(field)+r'\s+invoke-virtual \{v0, p1\}, Ljava/lang/StringBuilder;->append\(Ljava/lang/String;\)Ljava/lang/StringBuilder;', '',s)
    assert n==1
    s,n=re.subn(r'    new-instance v2, Ljava/lang/StringBuilder;\s+invoke-direct \{v2\}, Ljava/lang/StringBuilder;-><init>\(\)V\s+iput-object v2, p0, '+re.escape(field), '',s)
    assert n==1
    s,n=re.subn(r'    iput-object v1, p0, '+re.escape(field), '',s)
    assert n==2
    s=s.replace('.field private streamingBuf:Ljava/lang/StringBuilder;', '')
    assert 'streamingBuf' not in s
    return s


def patch_delivered_ui(app):
    """Experiment starts from exact signed 323fd5, not a different native build."""
    p=app/'ChatActivity.smali';p.write_text(discard_unused_stream_buffer(scroll_patch(p.read_text())))
    p=app/'GenerationService$2.smali';s=p.read_text()
    old='    invoke-static {v0}, Lcom/ggufchat/app/ReplyNotifications;->progressNow(Landroid/app/Service;)Z'
    assert s.count(old)==1
    s=s.replace(old,'''    iget-object v1, p0, Lcom/ggufchat/app/GenerationService$2;->val$reply:Ljava/lang/StringBuilder;
    invoke-static {v0, v1}, Lcom/ggufchat/app/ReplyNotifications;->progressNow(Landroid/app/Service;Ljava/lang/StringBuilder;)Z''')
    p.write_text(s)
