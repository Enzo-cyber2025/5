"""UI-only patch; never modify native code, tensors, sampling or output budgets."""
from unified_mobile import replace_method


def scroll_patch(s):
    assert 'ScrollTail;->request(' not in s, 'Apply the scroll patch exactly once'
    return replace_method(s, '.method private scrollToBottom()V', '''    .locals 1
    iget-object v0, p0, Lcom/ggufchat/app/ChatActivity;->scroll:Landroid/widget/ScrollView;
    invoke-static {v0}, Lcom/ggufchat/app/ScrollTail;->request(Landroid/widget/ScrollView;)V
    return-void''')


def patch_delivered_ui(app):
    """Experiment starts from exact signed 323fd5, not a different native build."""
    p=app/'ChatActivity.smali';p.write_text(scroll_patch(p.read_text()))
    p=app/'GenerationService$2.smali';s=p.read_text()
    old='    invoke-static {v0}, Lcom/ggufchat/app/ReplyNotifications;->progressNow(Landroid/app/Service;)Z'
    assert s.count(old)==1
    s=s.replace(old,'''    iget-object v1, p0, Lcom/ggufchat/app/GenerationService$2;->val$reply:Ljava/lang/StringBuilder;
    invoke-static {v0, v1}, Lcom/ggufchat/app/ReplyNotifications;->progressNow(Landroid/app/Service;Ljava/lang/StringBuilder;)Z''')
    p.write_text(s)
