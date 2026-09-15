"""Patch only delivery/service bookkeeping; never change the native inference path."""
from unified_mobile import replace_method

def patch_reply_notifications(app):
    p=app/'GenerationService.smali';s=p.read_text()
    assert 'ReplyNotifications;' not in s, 'Patch must be applied exactly once'
    for signature,marker,call in [
        ('.method public onCreate()V','    invoke-direct {p0}, Lcom/ggufchat/app/GenerationService;->ensureChannel()V','install'),
        ('.method public onDestroy()V','    invoke-super {p0}, Landroid/app/Service;->onDestroy()V','destroy')]:
        a=s.index(signature);b=s.index('.end method',a);part=s[a:b];assert part.count(marker)==1
        part=part.replace(marker,marker+f'\n    invoke-static {{p0}}, Lcom/ggufchat/app/ReplyNotifications;->{call}(Landroid/app/Service;)V')
        s=s[:a]+part+s[b:]
    a=s.index('.method private runGeneration(');b=s.index('.end method',a);part=s[a:b]
    marker='    invoke-static {}, Lcom/ggufchat/app/GenerationStats;->begin()V';assert part.count(marker)==1
    part=part.replace(marker,marker+'\n    invoke-static/range {p0 .. p1}, Lcom/ggufchat/app/ReplyNotifications;->begin(Landroid/app/Service;Ljava/lang/String;)V')
    marker='    invoke-static {v0, v1}, Lcom/ggufchat/app/ChatStore;->upsert(Landroid/content/Context;Lcom/ggufchat/app/Chat;)V';assert part.count(marker)==1
    part=part.replace(marker,marker+'\n    invoke-static/range {p0 .. p0}, Lcom/ggufchat/app/ReplyNotifications;->persisted(Landroid/app/Service;)V')
    # Reuse the immutable string already passed to Message, instead of a second
    # full-length StringBuilder.toString allocation for splitThinking.
    import re
    pattern=r'    invoke-virtual/range \{v19 \.\. v19\}, Ljava/lang/StringBuilder;->toString\(\)Ljava/lang/String;\s+move-result-object v4\s+(?=invoke-static \{v4\}, Lcom/ggufchat/app/PromptBuilder;->splitThinking)'
    part,n=re.subn(pattern,'    move-object v4, v8\n\n    ',part);assert n==1
    # Keep CPU/foreground ownership until AFTER the saved-reply notification
    # is handed to Android. Releasing before notify can suspend a sleeping phone
    # in the gap. The worker's finally cleanup releases on success AND failure.
    marker='    invoke-direct/range {p0 .. p0}, Lcom/ggufchat/app/GenerationService;->releaseWakeLock()V'
    assert part.count(marker)==1;part=part.replace(marker,'    # Released by workerFinished after final delivery.')
    pattern=r'const/4 v4, 0x0\s+move-object/from16 v0, p0\s+invoke-virtual \{v0, v4\}, Lcom/ggufchat/app/GenerationService;->stopForeground\(Z\)V'
    part,n=re.subn(pattern,'# Foreground removal is in the worker finally cleanup.',part);assert n==1
    s=s[:a]+part+s[b:]
    s=replace_method(s,'.method private notifyFinished(Ljava/lang/String;Ljava/lang/String;Z)V','''    .locals 1
    iget-boolean v0, p0, Lcom/ggufchat/app/GenerationService;->abortRequested:Z
    if-eqz v0, :not_aborted
    const/4 p3, 0x0
    :not_aborted
    invoke-static {p0, p3}, Lcom/ggufchat/app/ReplyNotifications;->finished(Landroid/app/Service;Z)V
    return-void''')
    a=s.index('.method private buildNotification(');b=s.index('.end method',a);part=s[a:b]
    marker='    invoke-virtual {v0}, Landroid/app/Notification$Builder;->build()Landroid/app/Notification;';assert part.count(marker)==1
    part=part.replace(marker,'''    const/4 v1, 0x1
    invoke-virtual {v0, v1}, Landroid/app/Notification$Builder;->setOnlyAlertOnce(Z)Landroid/app/Notification$Builder;
    const/4 v1, 0x0
    invoke-virtual {v0, v1}, Landroid/app/Notification$Builder;->setVisibility(I)Landroid/app/Notification$Builder;
'''+marker)
    s=s[:a]+part+s[b:];p.write_text(s)
    p=app/'GenerationService$2.smali';s=p.read_text()
    marker='    invoke-static {}, Lcom/ggufchat/app/GenerationStats;->notifyNow()Z';assert s.count(marker)==1
    s=s.replace(marker,'''    iget-object v0, p0, Lcom/ggufchat/app/GenerationService$2;->this$0:Lcom/ggufchat/app/GenerationService;
    invoke-static {v0}, Lcom/ggufchat/app/ReplyNotifications;->progressNow(Landroid/app/Service;)Z''')
    p.write_text(s)
    p=app/'GenerationService$1.smali';s=p.read_text()
    s=replace_method(s,'.method public run()V','''    .locals 4
    :try_start
    iget-object v0, p0, Lcom/ggufchat/app/GenerationService$1;->this$0:Lcom/ggufchat/app/GenerationService;
    iget-object v1, p0, Lcom/ggufchat/app/GenerationService$1;->val$chatId:Ljava/lang/String;
    iget-object v2, p0, Lcom/ggufchat/app/GenerationService$1;->val$userText:Ljava/lang/String;
    invoke-static {v0, v1, v2}, Lcom/ggufchat/app/GenerationService;->access$000(Lcom/ggufchat/app/GenerationService;Ljava/lang/String;Ljava/lang/String;)V
    :try_end
    .catchall {:try_start .. :try_end} :failed
    iget-object v0, p0, Lcom/ggufchat/app/GenerationService$1;->this$0:Lcom/ggufchat/app/GenerationService;
    invoke-static {v0}, Lcom/ggufchat/app/ReplyNotifications;->workerFinished(Landroid/app/Service;)V
    return-void
    :failed
    move-exception v3
    iget-object v0, p0, Lcom/ggufchat/app/GenerationService$1;->this$0:Lcom/ggufchat/app/GenerationService;
    invoke-static {v0}, Lcom/ggufchat/app/ReplyNotifications;->workerFinished(Landroid/app/Service;)V
    throw v3''')
    p.write_text(s)
