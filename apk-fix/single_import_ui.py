"""One import screen, including restoration of the historical ModelsActivity."""
from unified_mobile import replace_method


def patch_single_import_ui(app):
    p=app/'MainActivity.smali';s=p.read_text()
    assert s.count('"Importar .gguf"')==1
    s=s.replace('"Importar .gguf"','"Importar GGUF"')
    # Pages must exist before consuming the navigation request.
    a=s.index('.method protected onCreate(');b=s.index('.end method',a)
    part=s[a:b];assert part.count('    return-void')==1
    part=part.replace('    return-void','    invoke-direct {p0}, Lcom/ggufchat/app/MainActivity;->consumeImportNavigation()V\n    return-void')
    s=s[:a]+part+s[b:]
    assert '.method protected onNewIntent(' not in s
    s+='''
.method private consumeImportNavigation()V
    .locals 3
    invoke-virtual {p0}, Lcom/ggufchat/app/MainActivity;->getIntent()Landroid/content/Intent;
    move-result-object v0
    if-eqz v0, :done
    const-string v1, "ggufchat.openImport"
    const/4 v2, 0x0
    invoke-virtual {v0, v1, v2}, Landroid/content/Intent;->getBooleanExtra(Ljava/lang/String;Z)Z
    move-result v2
    if-eqz v2, :done
    invoke-virtual {v0, v1}, Landroid/content/Intent;->removeExtra(Ljava/lang/String;)V
    const/4 v2, 0x1
    invoke-direct {p0, v2}, Lcom/ggufchat/app/MainActivity;->showTab(I)V
    :done
    return-void
.end method

.method protected onNewIntent(Landroid/content/Intent;)V
    .locals 0
    invoke-super {p0, p1}, Landroid/app/Activity;->onNewIntent(Landroid/content/Intent;)V
    invoke-virtual {p0, p1}, Lcom/ggufchat/app/MainActivity;->setIntent(Landroid/content/Intent;)V
    invoke-direct {p0}, Lcom/ggufchat/app/MainActivity;->consumeImportNavigation()V
    return-void
.end method
'''
    p.write_text(s)
    p=app/'ModelsActivity.smali';s=p.read_text()
    s=replace_method(s,'.method protected onCreate(Landroid/os/Bundle;)V','''    .locals 3
    invoke-super {p0, p1}, Landroid/app/Activity;->onCreate(Landroid/os/Bundle;)V
    new-instance v0, Landroid/content/Intent;
    const-class v1, Lcom/ggufchat/app/MainActivity;
    invoke-direct {v0, p0, v1}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V
    const-string v1, "ggufchat.openImport"
    const/4 v2, 0x1
    invoke-virtual {v0, v1, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Z)Landroid/content/Intent;
    const v1, 0x24000000
    invoke-virtual {v0, v1}, Landroid/content/Intent;->addFlags(I)Landroid/content/Intent;
    invoke-virtual {p0, v0}, Lcom/ggufchat/app/ModelsActivity;->startActivity(Landroid/content/Intent;)V
    invoke-virtual {p0}, Lcom/ggufchat/app/ModelsActivity;->finish()V
    return-void''')
    s=replace_method(s,'.method protected onResume()V','''    .locals 0
    invoke-super {p0}, Landroid/app/Activity;->onResume()V
    return-void''')
    p.write_text(s)
