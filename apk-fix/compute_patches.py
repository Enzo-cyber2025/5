"""Lifecycle hooks: foreground-owned import, bounded CPU locks, vector UI."""
from unified_mobile import replace_method

def patch_compute(app):
    p=app/'GenerationService.smali';s=p.read_text()
    for method,call in [('acquireWakeLock','acquire'),('releaseWakeLock','release')]:
        s=replace_method(s,'.method private '+method+'()V',f'''    .locals 0
    invoke-static {{p0}}, Lcom/ggufchat/app/WorkWakeLocks;->{call}(Landroid/app/Service;)V
    return-void''')
    old='    invoke-virtual {p0, v2, v3}, Lcom/ggufchat/app/GenerationService;->startForeground(ILandroid/app/Notification;)V'
    assert s.count(old)==1
    s=s.replace(old,'    invoke-static {p0, v2, v3}, Lcom/ggufchat/app/ComputeService;->promote(Landroid/app/Service;ILandroid/app/Notification;)V')
    p.write_text(s)
    p=app/'MainActivity.smali';s=p.read_text();a=s.index('.method private importModel(');b=s.index('.end method',a)
    part=s[a:b];old='    invoke-virtual {v6}, Ljava/lang/Thread;->start()V';assert part.count(old)==1
    part=part.replace(old,'    invoke-static {p0, v6}, Lcom/ggufchat/app/ComputeService;->startThread(Landroid/content/Context;Ljava/lang/Thread;)V')
    s=s[:a]+part+s[b:]
    s=s.replace('"\\ud83d\\udc41"','"Visão"').replace('"\\uD83D\\uDC41"','"Visão"')
    p.write_text(s)
    p=app/'App.smali';s=p.read_text();old='    invoke-super {p0}, Landroid/app/Application;->onCreate()V';assert s.count(old)==1
    p.write_text(s.replace(old,old+'\n    invoke-static {p0}, Lcom/ggufchat/app/UiLifecycle;->install(Landroid/app/Application;)V'))
