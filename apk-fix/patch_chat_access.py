"""Repair illegal private member access in hand-written ChatActivity worker classes.

DEX does not give nested classes Java source-level private access. Retain private
members and use synthetic static accessors, as the original javac-generated code does.
"""
from pathlib import Path

OWNER = 'Lcom/ggufchat/app/ChatActivity;'
REPAIRS = {
    'ChatActivity$15': {
        f'iget-boolean v1, v0, {OWNER}->loading:Z': f'invoke-static {{v0}}, {OWNER}->repair$isLoading({OWNER})Z\n    move-result v1',
        f'iget v1, v0, {OWNER}->loadPct:I': f'invoke-static {{v0}}, {OWNER}->repair$getLoadPct({OWNER})I\n    move-result v1',
        f'iput v1, v0, {OWNER}->loadPct:I': f'invoke-static {{v0, v1}}, {OWNER}->repair$setLoadPct({OWNER}I)V',
        f'invoke-direct {{v0}}, {OWNER}->updateModelStatus()V': f'invoke-static {{v0}}, {OWNER}->repair$updateModelStatus({OWNER})V',
        f'iget-object v1, v0, {OWNER}->statusLine:Landroid/widget/TextView;': f'invoke-static {{v0}}, {OWNER}->repair$getStatusLine({OWNER})Landroid/widget/TextView;\n    move-result-object v1',
    },
    'ChatActivity$16': {
        f'iget-object v0, v0, {OWNER}->chat:Lcom/ggufchat/app/Chat;': f'invoke-static {{v0}}, {OWNER}->access$400({OWNER})Lcom/ggufchat/app/Chat;\n    move-result-object v0',
    },
    'ChatActivity$17': {
        f'iput-boolean v1, v0, {OWNER}->loading:Z': f'invoke-static {{v0, v1}}, {OWNER}->repair$setLoading({OWNER}Z)V',
        f'invoke-direct {{v0}}, {OWNER}->updateModelStatus()V': f'invoke-static {{v0}}, {OWNER}->repair$updateModelStatus({OWNER})V',
    },
}

ACCESSORS = f'''
.method static synthetic repair$isLoading({OWNER})Z
    .locals 1
    iget-boolean v0, p0, {OWNER}->loading:Z
    return v0
.end method

.method static synthetic repair$setLoading({OWNER}Z)V
    .locals 0
    iput-boolean p1, p0, {OWNER}->loading:Z
    return-void
.end method

.method static synthetic repair$getLoadPct({OWNER})I
    .locals 1
    iget v0, p0, {OWNER}->loadPct:I
    return v0
.end method

.method static synthetic repair$setLoadPct({OWNER}I)V
    .locals 0
    iput p1, p0, {OWNER}->loadPct:I
    return-void
.end method

.method static synthetic repair$getStatusLine({OWNER})Landroid/widget/TextView;
    .locals 1
    iget-object v0, p0, {OWNER}->statusLine:Landroid/widget/TextView;
    return-object v0
.end method

.method static synthetic repair$updateModelStatus({OWNER})V
    .locals 0
    invoke-direct {{p0}}, {OWNER}->updateModelStatus()V
    return-void
.end method
'''


def patch_chat_access(app: Path):
    path = app / 'ChatActivity.smali'
    source = path.read_text()
    if 'repair$' in source:
        raise ValueError('ChatActivity já contém os accessors de reparo')
    expected = ['.field private loading:Z', '.field private loadPct:I',
                '.field private statusLine:Landroid/widget/TextView;',
                '.method private updateModelStatus()V',
                f'.method static synthetic access$400({OWNER})Lcom/ggufchat/app/Chat;']
    if any(source.count(x) != 1 for x in expected):
        raise ValueError('ChatActivity difere da versão esperada')
    outputs = {path: source + ACCESSORS}
    for name, replacements in REPAIRS.items():
        path = app / (name + '.smali')
        source = path.read_text()
        for old, new in replacements.items():
            if source.count(old) != 1:
                raise ValueError(f'Acesso privado inesperado/já corrigido em {name}: {old}')
            source = source.replace(old, new)
        outputs[path] = source
    # Validate every expected access before writing any of the classes.
    for path, source in outputs.items():
        path.write_text(source)
