"""Wire the existing single/batch import worker to measured stage progress.
Exactly-two selections still use the atomic path; no transaction rules change.
"""
from unified_mobile import replace_method


def patch_import_progress(app):
    p=app/'MainActivity.smali';s=p.read_text()
    start=s.index('.method private importModel(');end=s.index('.end method',start)
    part=s[start:end]
    marker='    invoke-virtual {v0}, Landroid/app/ProgressDialog;->show()V'
    assert part.count(marker)==1
    part=part.replace(marker,marker+'\n    invoke-static {p0, p1}, Lcom/ggufchat/app/ImportProgress;->beginSingle(Landroid/content/Context;Landroid/net/Uri;)V')
    s=s[:start]+part+s[end:]
    marker='    invoke-virtual {p0, v0}, Lcom/ggufchat/app/MainActivity;->setContentView(Landroid/view/View;)V'
    assert s.count(marker)==1
    s=s.replace(marker,marker+'\n    invoke-static {p0}, Lcom/ggufchat/app/ImportProgress;->attach(Landroid/app/Activity;)V')
    p.write_text(s)
    p=app/'MainActivity$14$1.smali';s=p.read_text()
    s=replace_method(s,'.method public onProgress(JJ)V','''    .locals 1
    iget-object v0, p0, Lcom/ggufchat/app/MainActivity$14$1;->this$1:Lcom/ggufchat/app/MainActivity$14;
    iget-object v0, v0, Lcom/ggufchat/app/MainActivity$14;->this$0:Lcom/ggufchat/app/MainActivity;
    invoke-static {v0, p1, p2, p3, p4}, Lcom/ggufchat/app/ImportProgress;->singleCopy(Landroid/content/Context;JJ)V
    return-void''');p.write_text(s)
    p=app/'MainActivity$14.smali';s=p.read_text()
    marker='    iget-object v1, p0, Lcom/ggufchat/app/MainActivity$14;->val$uri:Landroid/net/Uri;'
    assert s.count(marker)==1
    s=s.replace(marker,marker+'\n    invoke-static {v0, v1}, Lcom/ggufchat/app/ImportProgress;->singleSource(Landroid/content/Context;Landroid/net/Uri;)V')
    marker='    invoke-static {v5}, Lcom/ggufchat/app/GGUFMeta;->read(Ljava/io/File;)Ljava/util/Map;'
    assert s.count(marker)==1
    s=s.replace(marker,'''    iget-object v0, p0, Lcom/ggufchat/app/MainActivity$14;->this$0:Lcom/ggufchat/app/MainActivity;
    invoke-static {v0}, Lcom/ggufchat/app/ImportProgress;->identificationStart(Landroid/content/Context;)V
'''+marker)
    marker='    invoke-static {v4}, Lcom/ggufchat/app/Pairing;->inspect(Ljava/lang/Object;)V'
    assert s.count(marker)==1
    s=s.replace(marker,'    invoke-static {v0, v4}, Lcom/ggufchat/app/Pairing;->inspectWithProgress(Landroid/content/Context;Ljava/lang/Object;)V')
    p.write_text(s)
    for suffix,success in [('2',False),('3',True)]:
        p=app/('MainActivity$14$'+suffix+'.smali');s=p.read_text()
        marker='    invoke-virtual {v0}, Landroid/app/ProgressDialog;->dismiss()V'
        assert s.count(marker)==1
        # Keep original registers intact; end the session immediately before the
        # original UI callback dismisses the original single-import dialog.
        extra='''    iget-object v0, p0, Lcom/ggufchat/app/MainActivity$14$SUFFIX;->this$1:Lcom/ggufchat/app/MainActivity$14;
    iget-object v0, v0, Lcom/ggufchat/app/MainActivity$14;->this$0:Lcom/ggufchat/app/MainActivity;
    const/4 v1, BOOL
    invoke-static {v0, v1}, Lcom/ggufchat/app/ImportProgress;->singleFinished(Landroid/content/Context;Z)V
'''.replace('SUFFIX',suffix).replace('BOOL','0x1' if success else '0x0')
        # Insert after dismissal: subsequent original instructions reinitialize
        # v0/v1. The asynchronous progress renderer never re-shows this dialog.
        s=s.replace(marker,marker+'\n'+extra);p.write_text(s)
