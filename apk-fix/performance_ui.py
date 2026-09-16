"""Safe native dispatch, incremental fenced code renderer and real UI arrival timing."""
from unified_mobile import replace_method

def patch_performance_ui(app):
    p=app/'Native.smali';s=p.read_text()
    import re
    s,n=re.subn(r'    const-string v0, "aijni"\s+invoke-static \{v0\}, Ljava/lang/System;->loadLibrary\(Ljava/lang/String;\)V',
                '    invoke-static {}, Lcom/ggufchat/app/NativeDispatch;->load()V',s)
    assert n==1;p.write_text(s)
    p=app/'ChatActivity.smali';s=p.read_text()
    s=s.replace('    invoke-virtual {v0, p1}, Landroid/widget/TextView;->append(Ljava/lang/CharSequence;)V',
                '    invoke-static {p0}, Lcom/ggufchat/app/ResponseTiming;->first(Landroid/app/Activity;)V\n    invoke-static {v0, p1}, Lcom/ggufchat/app/CodeBlocks;->append(Landroid/widget/TextView;Ljava/lang/String;)V')
    a=s.index('.method private addMessageView(');b=s.index('.end method',a);part=s[a:b]
    marker='    :goto_2';assert part.count(marker)==1
    part=part.replace(marker,marker+'\n    invoke-static {v4, p2}, Lcom/ggufchat/app/CodeBlocks;->decorate(Landroid/widget/LinearLayout;Z)V')
    s=s[:a]+part+s[b:]
    a=s.index('.method private onSend()V');b=s.index('.end method',a);part=s[a:b]
    # Log from entry of the real Send handler, before saving/preparing the request.
    marker='    .prologue';assert part.count(marker)==1
    part=part.replace(marker,marker+'\n    invoke-static {p0}, Lcom/ggufchat/app/ResponseTiming;->sent(Landroid/app/Activity;)V',1)
    s=s[:a]+part+s[b:];p.write_text(s)
