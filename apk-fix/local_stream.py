"""Experimental in-process routing only; not used by the production build recipe."""
from pathlib import Path

BUS='Lcom/ggufchat/app/LocalGenerationStream;'
def patch(app):
    app=Path(app)
    paths={n:(app/(n+'.smali')) for n in ('ChatActivity','GenerationService')}
    texts={n:p.read_text() for n,p in paths.items()}
    assert all(BUS not in s for s in texts.values()),'Do not double-apply stream routing'
    receiver=(app/'ChatActivity$1.smali').read_text()
    assert all(x not in receiver for x in ('->goAsync(', '->setResult', '->abortBroadcast(', '->isOrderedBroadcast('))
    s=texts['ChatActivity']
    replacements=[
        ('invoke-virtual {p0, v0}, Lcom/ggufchat/app/ChatActivity;->unregisterReceiver(Landroid/content/BroadcastReceiver;)V',
         'invoke-static {p0, v0}, '+BUS+'->unregister(Landroid/content/Context;Landroid/content/BroadcastReceiver;)V'),
        ('invoke-virtual {p0, v1, v0, v3}, Lcom/ggufchat/app/ChatActivity;->registerReceiver(Landroid/content/BroadcastReceiver;Landroid/content/IntentFilter;I)Landroid/content/Intent;',
         'invoke-static {p0, v1, v0, v3}, '+BUS+'->register(Landroid/content/Context;Landroid/content/BroadcastReceiver;Landroid/content/IntentFilter;I)Landroid/content/Intent;'),
        ('invoke-virtual {p0, v1, v0}, Lcom/ggufchat/app/ChatActivity;->registerReceiver(Landroid/content/BroadcastReceiver;Landroid/content/IntentFilter;)Landroid/content/Intent;',
         'invoke-static {p0, v1, v0}, '+BUS+'->register(Landroid/content/Context;Landroid/content/BroadcastReceiver;Landroid/content/IntentFilter;)Landroid/content/Intent;')]
    for old,new in replacements:
        assert s.count(old)==1
        s=s.replace(old,new)
    texts['ChatActivity']=s
    s=texts['GenerationService']
    old='invoke-virtual {p0, v0}, Lcom/ggufchat/app/GenerationService;->sendBroadcast(Landroid/content/Intent;)V'
    assert s.count(old)==3
    # Fail before writing either file if a new producer/extra type needs review.
    import re
    for name in ('broadcastToken','broadcastDone','broadcastError'):
        method=re.search(r'^\.method private '+name+r'\([^\n]*\n.*?^\.end method',s,re.M|re.S)
        assert method and method[0].count(old)==1 and '->setPackage(' in method[0]
        signatures=re.findall(r'Intent;->putExtra\((.*?)\)Landroid/content/Intent;',method[0])
        assert len(signatures)==2 and all(t in ('Ljava/lang/String;Ljava/lang/String;','Ljava/lang/String;Z') for t in signatures)
    texts['GenerationService']=s.replace(old,'invoke-static {p0, v0}, '+BUS+'->send(Landroid/content/Context;Landroid/content/Intent;)V')
    for n,p in paths.items():p.write_text(texts[n])
