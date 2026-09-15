"""Persist native metrics on the exact response; place footer outside its bubble."""
from unified_mobile import replace_method

def patch_generation_stats(app):
    p=app/'Message.smali';s=p.read_text().replace('# direct methods','.field public generationMetrics:Ljava/lang/String;\n\n# direct methods',1)
    for method,call,args in [('.method public static fromJson(', 'read','v0, p0'),('.method public toJson(', 'write','p0, v0')]:
        a=s.index(method);b=s.index('.end method',a);part=s[a:b];marker='    return-object v0';assert part.count(marker)==1
        part=part.replace(marker,f'    invoke-static {{{args}}}, Lcom/ggufchat/app/GenerationStats;->{call}(Ljava/lang/Object;Lorg/json/JSONObject;)V\n'+marker)
        s=s[:a]+part+s[b:]
    p.write_text(s)
    p=app/'GenerationService.smali';s=p.read_text();a=s.index('.method private runGeneration(');b=s.index('.end method',a)
    part=s[a:b];part=part.replace('    .prologue','    .prologue\n    invoke-static {}, Lcom/ggufchat/app/GenerationStats;->begin()V',1)
    marker='    invoke-direct {v7, v4, v8}, Lcom/ggufchat/app/Message;-><init>(Ljava/lang/String;Ljava/lang/String;)V';assert part.count(marker)==1
    part=part.replace(marker,marker+'\n    invoke-static {v7}, Lcom/ggufchat/app/GenerationStats;->attach(Ljava/lang/Object;)V')
    p.write_text(s[:a]+part+s[b:])
    p=app/'GenerationService$2.smali';s=p.read_text();marker='    .line 132';assert s.count(marker)==1
    s=s.replace(marker,'''    invoke-static {}, Lcom/ggufchat/app/GenerationStats;->notifyNow()Z
    move-result v0
    if-eqz v0, :goto_0
'''+marker)
    old='    invoke-virtual {v1}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;';assert s.count(old)==1
    s=s.replace(old,'    invoke-static {v1}, Lcom/ggufchat/app/GenerationStats;->preview(Ljava/lang/StringBuilder;)Ljava/lang/String;');p.write_text(s)
    p=app/'ChatActivity.smali';s=p.read_text().replace('# direct methods','.field private renderedMessage:Ljava/lang/Object;\n\n# direct methods',1)
    a=s.index('.method private renderHistory()V');b=s.index('.end method',a);part=s[a:b]
    marker='    iget-object v3, v0, Lcom/ggufchat/app/Message;->content:Ljava/lang/String;';assert part.count(marker)==1
    part=part.replace(marker,'    iput-object v0, p0, Lcom/ggufchat/app/ChatActivity;->renderedMessage:Ljava/lang/Object;\n'+marker)
    marker='    invoke-direct {p0, v3, v2, v0}, Lcom/ggufchat/app/ChatActivity;->addMessageView(Ljava/lang/String;ZZ)V';assert part.count(marker)==1
    part=part.replace(marker,marker+'\n    const/4 v0, 0x0\n    iput-object v0, p0, Lcom/ggufchat/app/ChatActivity;->renderedMessage:Ljava/lang/Object;')
    s=s[:a]+part+s[b:]
    a=s.index('.method private addMessageView(');b=s.index('.end method',a);part=s[a:b]
    marker='    :goto_2';assert part.count(marker)==1
    part=part.replace(marker,marker+'''\n    iget-object v0, p0, Lcom/ggufchat/app/ChatActivity;->renderedMessage:Ljava/lang/Object;
    invoke-static {p0, v4, v0}, Lcom/ggufchat/app/GenerationStats;->caption(Landroid/content/Context;Landroid/widget/LinearLayout;Ljava/lang/Object;)V''')
    p.write_text(s[:a]+part+s[b:])
