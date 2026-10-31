.class public Lcom/exepretranslator/app/MainActivity;
.super Landroid/app/Activity;
.implements Landroid/view/View$OnClickListener;
.implements Ljava/lang/Runnable;


# instance fields
.field private pickBtn:Landroid/widget/Button;

.field private startBtn:Landroid/widget/Button;

.field private stopBtn:Landroid/widget/Button;

.field private fileLabel:Landroid/widget/TextView;

.field private percentLabel:Landroid/widget/TextView;

.field private statusLabel:Landroid/widget/TextView;

.field private progressBar:Landroid/widget/ProgressBar;

.field private execBtn:Landroid/widget/Button;

.field private execLabel:Landroid/widget/TextView;

.field private handler:Landroid/os/Handler;

.field private tickRunning:Z


# direct methods
.method public constructor <init>()V
    .locals 0

    invoke-direct {p0}, Landroid/app/Activity;-><init>()V

    return-void
.end method

.method private prefs()Landroid/content/SharedPreferences;
    .locals 2

    const-string v0, "ptexe_prefs"

    const/4 v1, 0x0

    invoke-virtual {p0, v0, v1}, Landroid/app/Activity;->getSharedPreferences(Ljava/lang/String;I)Landroid/content/SharedPreferences;

    move-result-object v0

    return-object v0
.end method

.method private requestNotifPermIfNeeded()V
    .locals 3

    sget v0, Landroid/os/Build$VERSION;->SDK_INT:I

    const/16 v1, 0x21

    if-lt v0, v1, :cond_0

    const-string v0, "android.permission.POST_NOTIFICATIONS"

    invoke-virtual {p0, v0}, Landroid/app/Activity;->checkSelfPermission(Ljava/lang/String;)I

    move-result v1

    if-eqz v1, :cond_0

    const/4 v1, 0x1

    new-array v1, v1, [Ljava/lang/String;

    const/4 v2, 0x0

    aput-object v0, v1, v2

    const/16 v0, 0x51

    invoke-virtual {p0, v1, v0}, Landroid/app/Activity;->requestPermissions([Ljava/lang/String;I)V

    :cond_0
    return-void
.end method

.method private refreshUi()V
    .locals 8

    invoke-direct {p0}, Lcom/exepretranslator/app/MainActivity;->prefs()Landroid/content/SharedPreferences;

    move-result-object v0

    const-string v1, "uri"

    const/4 v2, 0x0

    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences;->getString(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;

    move-result-object v1

    iget-object v3, p0, Lcom/exepretranslator/app/MainActivity;->fileLabel:Landroid/widget/TextView;

    if-nez v1, :cond_0

    const-string v4, "Nenhum arquivo selecionado"

    goto :goto_0

    :cond_0
    move-object v4, v1

    :goto_0
    invoke-virtual {v3, v4}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V

    const-string v3, "code_size"

    const-wide/16 v4, 0x0

    invoke-interface {v0, v3, v4, v5}, Landroid/content/SharedPreferences;->getLong(Ljava/lang/String;J)J

    move-result-wide v3

    const-string v6, "proc_off"

    invoke-interface {v0, v6, v4, v5}, Landroid/content/SharedPreferences;->getLong(Ljava/lang/String;J)J

    move-result-wide v5

    const-wide/16 v7, 0x0

    cmp-long v2, v3, v7

    if-lez v2, :cond_1

    long-to-double v6, v5

    const-wide/high16 v0, 0x4059000000000000L    # 100.0

    mul-double/2addr v6, v0

    long-to-double v0, v3

    div-double/2addr v6, v0

    double-to-int v0, v6

    goto :goto_1

    :cond_1
    const/4 v0, 0x0

    :goto_1
    iget-object v1, p0, Lcom/exepretranslator/app/MainActivity;->progressBar:Landroid/widget/ProgressBar;

    invoke-virtual {v1, v0}, Landroid/widget/ProgressBar;->setProgress(I)V

    iget-object v1, p0, Lcom/exepretranslator/app/MainActivity;->percentLabel:Landroid/widget/TextView;

    new-instance v2, Ljava/lang/StringBuilder;

    invoke-direct {v2}, Ljava/lang/StringBuilder;-><init>()V

    invoke-virtual {v2, v0}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;

    const-string v0, "%"

    invoke-virtual {v2, v0}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-virtual {v2}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;

    move-result-object v0

    invoke-virtual {v1, v0}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V

    invoke-direct {p0}, Lcom/exepretranslator/app/MainActivity;->prefs()Landroid/content/SharedPreferences;

    move-result-object v0

    const-string v1, "status"

    const-string v2, "ocioso"

    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences;->getString(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;

    move-result-object v0

    iget-object v1, p0, Lcom/exepretranslator/app/MainActivity;->statusLabel:Landroid/widget/TextView;

    new-instance v2, Ljava/lang/StringBuilder;

    invoke-direct {v2}, Ljava/lang/StringBuilder;-><init>()V

    const-string v3, "Status: "

    invoke-virtual {v2, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-virtual {v2, v0}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-virtual {v2}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;

    move-result-object v0

    invoke-virtual {v1, v0}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V

    invoke-direct {p0}, Lcom/exepretranslator/app/MainActivity;->prefs()Landroid/content/SharedPreferences;

    move-result-object v0

    const-string v1, "exec_status"

    const-string v2, "-"

    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences;->getString(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;

    move-result-object v1

    const-string v2, "exec_result"

    const/4 v3, 0x0

    invoke-interface {v0, v2, v3}, Landroid/content/SharedPreferences;->getInt(Ljava/lang/String;I)I

    move-result v2

    const-string v3, "exec_message"

    const-string v4, ""

    invoke-interface {v0, v3, v4}, Landroid/content/SharedPreferences;->getString(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;

    move-result-object v0

    new-instance v3, Ljava/lang/StringBuilder;

    invoke-direct {v3}, Ljava/lang/StringBuilder;-><init>()V

    const-string v4, "Execucao: "

    invoke-virtual {v3, v4}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-virtual {v3, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    const-string v4, "concluido"

    invoke-virtual {v4, v1}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z

    move-result v4

    if-eqz v4, :cond_exec_novalue

    const-string v4, " (resultado="

    invoke-virtual {v3, v4}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-virtual {v3, v2}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;

    const-string v4, ")"

    invoke-virtual {v3, v4}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    goto :cond_exec_done

    :cond_exec_novalue
    const-string v4, "erro"

    invoke-virtual {v4, v1}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z

    move-result v4

    if-eqz v4, :cond_exec_done

    const-string v4, " - "

    invoke-virtual {v3, v4}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-virtual {v3, v0}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    :cond_exec_done
    invoke-virtual {v3}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;

    move-result-object v0

    iget-object v1, p0, Lcom/exepretranslator/app/MainActivity;->execLabel:Landroid/widget/TextView;

    invoke-virtual {v1, v0}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V

    return-void
.end method

.method private addSpacer(Landroid/widget/LinearLayout;)V
    .locals 2

    new-instance v0, Landroid/widget/TextView;

    invoke-direct {v0, p0}, Landroid/widget/TextView;-><init>(Landroid/content/Context;)V

    const-string v1, " "

    invoke-virtual {v0, v1}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V

    invoke-virtual {p1, v0}, Landroid/widget/LinearLayout;->addView(Landroid/view/View;)V

    return-void
.end method


# virtual methods
.method protected onActivityResult(IILandroid/content/Intent;)V
    .locals 5

    invoke-super {p0, p1, p2, p3}, Landroid/app/Activity;->onActivityResult(IILandroid/content/Intent;)V

    const/16 v0, 0x3e9

    if-ne p1, v0, :cond_2

    const/4 v0, -0x1

    if-ne p2, v0, :cond_2

    if-eqz p3, :cond_2

    invoke-virtual {p3}, Landroid/content/Intent;->getData()Landroid/net/Uri;

    move-result-object v0

    if-eqz v0, :cond_2

    invoke-virtual {p0}, Landroid/app/Activity;->getContentResolver()Landroid/content/ContentResolver;

    move-result-object v1

    sget v2, Landroid/content/Intent;->FLAG_GRANT_READ_URI_PERMISSION:I

    :try_start_0
    invoke-virtual {v1, v0, v2}, Landroid/content/ContentResolver;->takePersistableUriPermission(Landroid/net/Uri;I)V
    :try_end_0
    .catch Ljava/lang/SecurityException; {:try_start_0 .. :try_end_0} :cond_0

    :cond_0
    invoke-direct {p0}, Lcom/exepretranslator/app/MainActivity;->prefs()Landroid/content/SharedPreferences;

    move-result-object v1

    invoke-interface {v1}, Landroid/content/SharedPreferences;->edit()Landroid/content/SharedPreferences$Editor;

    move-result-object v1

    const-string v2, "uri"

    invoke-virtual {v0}, Landroid/net/Uri;->toString()Ljava/lang/String;

    move-result-object v0

    invoke-interface {v1, v2, v0}, Landroid/content/SharedPreferences$Editor;->putString(Ljava/lang/String;Ljava/lang/String;)Landroid/content/SharedPreferences$Editor;

    move-result-object v0

    const-string v1, "proc_off"

    const-wide/16 v2, 0x0

    invoke-interface {v0, v1, v2, v3}, Landroid/content/SharedPreferences$Editor;->putLong(Ljava/lang/String;J)Landroid/content/SharedPreferences$Editor;

    move-result-object v0

    const-string v1, "code_size"

    invoke-interface {v0, v1, v2, v3}, Landroid/content/SharedPreferences$Editor;->putLong(Ljava/lang/String;J)Landroid/content/SharedPreferences$Editor;

    move-result-object v0

    const-string v1, "status"

    const-string v4, "arquivo selecionado"

    invoke-interface {v0, v1, v4}, Landroid/content/SharedPreferences$Editor;->putString(Ljava/lang/String;Ljava/lang/String;)Landroid/content/SharedPreferences$Editor;

    move-result-object v0

    const-string v1, "stop_requested"

    const/4 v4, 0x0

    invoke-interface {v0, v1, v4}, Landroid/content/SharedPreferences$Editor;->putBoolean(Ljava/lang/String;Z)Landroid/content/SharedPreferences$Editor;

    move-result-object v0

    invoke-interface {v0}, Landroid/content/SharedPreferences$Editor;->apply()V

    invoke-direct {p0}, Lcom/exepretranslator/app/MainActivity;->refreshUi()V

    :cond_2
    return-void
.end method

.method public onClick(Landroid/view/View;)V
    .locals 4

    iget-object v0, p0, Lcom/exepretranslator/app/MainActivity;->pickBtn:Landroid/widget/Button;

    if-ne p1, v0, :cond_0

    new-instance v0, Landroid/content/Intent;

    const-string v1, "android.intent.action.OPEN_DOCUMENT"

    invoke-direct {v0, v1}, Landroid/content/Intent;-><init>(Ljava/lang/String;)V

    const-string v1, "android.intent.category.OPENABLE"

    invoke-virtual {v0, v1}, Landroid/content/Intent;->addCategory(Ljava/lang/String;)Landroid/content/Intent;

    const-string v1, "*/*"

    invoke-virtual {v0, v1}, Landroid/content/Intent;->setType(Ljava/lang/String;)Landroid/content/Intent;

    const/16 v1, 0x3e9

    invoke-virtual {p0, v0, v1}, Landroid/app/Activity;->startActivityForResult(Landroid/content/Intent;I)V

    goto :goto_2

    :cond_0
    iget-object v0, p0, Lcom/exepretranslator/app/MainActivity;->startBtn:Landroid/widget/Button;

    if-ne p1, v0, :cond_1

    invoke-direct {p0}, Lcom/exepretranslator/app/MainActivity;->prefs()Landroid/content/SharedPreferences;

    move-result-object v0

    const-string v1, "uri"

    const/4 v2, 0x0

    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences;->getString(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;

    move-result-object v0

    if-nez v0, :cond_3

    const-string v0, "Selecione um arquivo .exe primeiro"

    const/4 v1, 0x1

    invoke-static {p0, v0, v1}, Landroid/widget/Toast;->makeText(Landroid/content/Context;Ljava/lang/CharSequence;I)Landroid/widget/Toast;

    move-result-object v0

    invoke-virtual {v0}, Landroid/widget/Toast;->show()V

    goto :goto_2

    :cond_3
    invoke-direct {p0}, Lcom/exepretranslator/app/MainActivity;->prefs()Landroid/content/SharedPreferences;

    move-result-object v1

    invoke-interface {v1}, Landroid/content/SharedPreferences;->edit()Landroid/content/SharedPreferences$Editor;

    move-result-object v1

    const-string v2, "stop_requested"

    const/4 v3, 0x0

    invoke-interface {v1, v2, v3}, Landroid/content/SharedPreferences$Editor;->putBoolean(Ljava/lang/String;Z)Landroid/content/SharedPreferences$Editor;

    move-result-object v1

    invoke-interface {v1}, Landroid/content/SharedPreferences$Editor;->apply()V

    new-instance v1, Landroid/content/Intent;

    const-class v2, Lcom/exepretranslator/app/TranslateService;

    invoke-direct {v1, p0, v2}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V

    const-string v2, "uri"

    invoke-virtual {v1, v2, v0}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;

    invoke-virtual {p0, v1}, Landroid/content/Context;->startForegroundService(Landroid/content/Intent;)Landroid/content/ComponentName;

    goto :goto_2

    :cond_1
    iget-object v0, p0, Lcom/exepretranslator/app/MainActivity;->execBtn:Landroid/widget/Button;

    if-ne p1, v0, :cond_4

    invoke-direct {p0}, Lcom/exepretranslator/app/MainActivity;->startExampleExec()V

    goto :goto_2

    :cond_4
    iget-object v0, p0, Lcom/exepretranslator/app/MainActivity;->stopBtn:Landroid/widget/Button;

    if-ne p1, v0, :cond_2

    invoke-direct {p0}, Lcom/exepretranslator/app/MainActivity;->prefs()Landroid/content/SharedPreferences;

    move-result-object v0

    invoke-interface {v0}, Landroid/content/SharedPreferences;->edit()Landroid/content/SharedPreferences$Editor;

    move-result-object v0

    const-string v1, "stop_requested"

    const/4 v2, 0x1

    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences$Editor;->putBoolean(Ljava/lang/String;Z)Landroid/content/SharedPreferences$Editor;

    move-result-object v0

    invoke-interface {v0}, Landroid/content/SharedPreferences$Editor;->apply()V

    :cond_2
    :goto_2
    return-void
.end method

.method protected onCreate(Landroid/os/Bundle;)V
    .locals 6

    invoke-super {p0, p1}, Landroid/app/Activity;->onCreate(Landroid/os/Bundle;)V

    new-instance v0, Landroid/widget/LinearLayout;

    invoke-direct {v0, p0}, Landroid/widget/LinearLayout;-><init>(Landroid/content/Context;)V

    const/4 v1, 0x1

    invoke-virtual {v0, v1}, Landroid/widget/LinearLayout;->setOrientation(I)V

    const/16 v1, 0x28

    invoke-virtual {v0, v1, v1, v1, v1}, Landroid/widget/LinearLayout;->setPadding(IIII)V

    new-instance v2, Landroid/widget/TextView;

    invoke-direct {v2, p0}, Landroid/widget/TextView;-><init>(Landroid/content/Context;)V

    const-string v3, "Pre-Tradutor de EXE (prototipo heuristico)"

    invoke-virtual {v2, v3}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V

    const/high16 v3, 0x41a00000    # 20.0f

    invoke-virtual {v2, v3}, Landroid/widget/TextView;->setTextSize(F)V

    invoke-virtual {v0, v2}, Landroid/widget/LinearLayout;->addView(Landroid/view/View;)V

    invoke-direct {p0, v0}, Lcom/exepretranslator/app/MainActivity;->addSpacer(Landroid/widget/LinearLayout;)V

    new-instance v2, Landroid/widget/TextView;

    invoke-direct {v2, p0}, Landroid/widget/TextView;-><init>(Landroid/content/Context;)V

    const-string v3, "Nenhum arquivo selecionado"

    invoke-virtual {v2, v3}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V

    iput-object v2, p0, Lcom/exepretranslator/app/MainActivity;->fileLabel:Landroid/widget/TextView;

    invoke-virtual {v0, v2}, Landroid/widget/LinearLayout;->addView(Landroid/view/View;)V

    new-instance v2, Landroid/widget/Button;

    invoke-direct {v2, p0}, Landroid/widget/Button;-><init>(Landroid/content/Context;)V

    const-string v3, "Selecionar .exe"

    invoke-virtual {v2, v3}, Landroid/widget/Button;->setText(Ljava/lang/CharSequence;)V

    invoke-virtual {v2, p0}, Landroid/view/View;->setOnClickListener(Landroid/view/View$OnClickListener;)V

    iput-object v2, p0, Lcom/exepretranslator/app/MainActivity;->pickBtn:Landroid/widget/Button;

    invoke-virtual {v0, v2}, Landroid/widget/LinearLayout;->addView(Landroid/view/View;)V

    new-instance v2, Landroid/widget/Button;

    invoke-direct {v2, p0}, Landroid/widget/Button;-><init>(Landroid/content/Context;)V

    const-string v3, "Iniciar / continuar pre-traducao"

    invoke-virtual {v2, v3}, Landroid/widget/Button;->setText(Ljava/lang/CharSequence;)V

    invoke-virtual {v2, p0}, Landroid/view/View;->setOnClickListener(Landroid/view/View$OnClickListener;)V

    iput-object v2, p0, Lcom/exepretranslator/app/MainActivity;->startBtn:Landroid/widget/Button;

    invoke-virtual {v0, v2}, Landroid/widget/LinearLayout;->addView(Landroid/view/View;)V

    new-instance v2, Landroid/widget/Button;

    invoke-direct {v2, p0}, Landroid/widget/Button;-><init>(Landroid/content/Context;)V

    const-string v3, "Pausar"

    invoke-virtual {v2, v3}, Landroid/widget/Button;->setText(Ljava/lang/CharSequence;)V

    invoke-virtual {v2, p0}, Landroid/view/View;->setOnClickListener(Landroid/view/View$OnClickListener;)V

    iput-object v2, p0, Lcom/exepretranslator/app/MainActivity;->stopBtn:Landroid/widget/Button;

    invoke-virtual {v0, v2}, Landroid/widget/LinearLayout;->addView(Landroid/view/View;)V

    invoke-direct {p0, v0}, Lcom/exepretranslator/app/MainActivity;->addSpacer(Landroid/widget/LinearLayout;)V

    new-instance v2, Landroid/widget/ProgressBar;

    invoke-direct {v2, p0}, Landroid/widget/ProgressBar;-><init>(Landroid/content/Context;)V

    const/16 v3, 0x64

    invoke-virtual {v2, v3}, Landroid/widget/ProgressBar;->setMax(I)V

    const/4 v3, 0x0

    invoke-virtual {v2, v3}, Landroid/widget/ProgressBar;->setIndeterminate(Z)V

    iput-object v2, p0, Lcom/exepretranslator/app/MainActivity;->progressBar:Landroid/widget/ProgressBar;

    invoke-virtual {v0, v2}, Landroid/widget/LinearLayout;->addView(Landroid/view/View;)V

    new-instance v2, Landroid/widget/TextView;

    invoke-direct {v2, p0}, Landroid/widget/TextView;-><init>(Landroid/content/Context;)V

    const-string v3, "0%"

    invoke-virtual {v2, v3}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V

    iput-object v2, p0, Lcom/exepretranslator/app/MainActivity;->percentLabel:Landroid/widget/TextView;

    invoke-virtual {v0, v2}, Landroid/widget/LinearLayout;->addView(Landroid/view/View;)V

    new-instance v2, Landroid/widget/TextView;

    invoke-direct {v2, p0}, Landroid/widget/TextView;-><init>(Landroid/content/Context;)V

    const-string v3, "Status: ocioso"

    invoke-virtual {v2, v3}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V

    iput-object v2, p0, Lcom/exepretranslator/app/MainActivity;->statusLabel:Landroid/widget/TextView;

    invoke-virtual {v0, v2}, Landroid/widget/LinearLayout;->addView(Landroid/view/View;)V

    invoke-direct {p0, v0}, Lcom/exepretranslator/app/MainActivity;->addSpacer(Landroid/widget/LinearLayout;)V

    new-instance v2, Landroid/widget/TextView;

    invoke-direct {v2, p0}, Landroid/widget/TextView;-><init>(Landroid/content/Context;)V

    const-string v3, "Modo experimental: executa de verdade um programinha de teste minusculo embutido (soma 1+2+3+4+5). NAO funciona com programas reais do Windows."

    invoke-virtual {v2, v3}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V

    invoke-virtual {v0, v2}, Landroid/widget/LinearLayout;->addView(Landroid/view/View;)V

    new-instance v2, Landroid/widget/Button;

    invoke-direct {v2, p0}, Landroid/widget/Button;-><init>(Landroid/content/Context;)V

    const-string v3, "Executar exemplo embutido (experimental)"

    invoke-virtual {v2, v3}, Landroid/widget/Button;->setText(Ljava/lang/CharSequence;)V

    invoke-virtual {v2, p0}, Landroid/view/View;->setOnClickListener(Landroid/view/View$OnClickListener;)V

    iput-object v2, p0, Lcom/exepretranslator/app/MainActivity;->execBtn:Landroid/widget/Button;

    invoke-virtual {v0, v2}, Landroid/widget/LinearLayout;->addView(Landroid/view/View;)V

    new-instance v2, Landroid/widget/TextView;

    invoke-direct {v2, p0}, Landroid/widget/TextView;-><init>(Landroid/content/Context;)V

    const-string v3, "Execucao: -"

    invoke-virtual {v2, v3}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V

    iput-object v2, p0, Lcom/exepretranslator/app/MainActivity;->execLabel:Landroid/widget/TextView;

    invoke-virtual {v0, v2}, Landroid/widget/LinearLayout;->addView(Landroid/view/View;)V

    invoke-direct {p0, v0}, Lcom/exepretranslator/app/MainActivity;->addSpacer(Landroid/widget/LinearLayout;)V

    new-instance v2, Landroid/widget/TextView;

    invoke-direct {v2, p0}, Landroid/widget/TextView;-><init>(Landroid/content/Context;)V

    const-string v3, "Aviso: isto NAO e um emulador do Windows e NAO executa o programa. E uma leitura heuristica das instrucoes x86 do arquivo selecionado, que grava um rascunho de traducao de instrucoes em texto, por partes, no armazenamento do app, continuando mesmo com a tela bloqueada. Cobertura de opcodes e aproximada."

    invoke-virtual {v2, v3}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V

    const/high16 v3, 0x41600000    # 14.0f

    invoke-virtual {v2, v3}, Landroid/widget/TextView;->setTextSize(F)V

    invoke-virtual {v0, v2}, Landroid/widget/LinearLayout;->addView(Landroid/view/View;)V

    invoke-virtual {p0, v0}, Landroid/app/Activity;->setContentView(Landroid/view/View;)V

    new-instance v2, Landroid/os/Handler;

    invoke-static {}, Landroid/os/Looper;->getMainLooper()Landroid/os/Looper;

    move-result-object v3

    invoke-direct {v2, v3}, Landroid/os/Handler;-><init>(Landroid/os/Looper;)V

    iput-object v2, p0, Lcom/exepretranslator/app/MainActivity;->handler:Landroid/os/Handler;

    invoke-direct {p0}, Lcom/exepretranslator/app/MainActivity;->requestNotifPermIfNeeded()V

    return-void
.end method

.method protected onPause()V
    .locals 2

    const/4 v0, 0x0

    iput-boolean v0, p0, Lcom/exepretranslator/app/MainActivity;->tickRunning:Z

    iget-object v0, p0, Lcom/exepretranslator/app/MainActivity;->handler:Landroid/os/Handler;

    invoke-virtual {v0, p0}, Landroid/os/Handler;->removeCallbacks(Ljava/lang/Runnable;)V

    invoke-super {p0}, Landroid/app/Activity;->onPause()V

    return-void
.end method

.method protected onResume()V
    .locals 1

    invoke-super {p0}, Landroid/app/Activity;->onResume()V

    invoke-direct {p0}, Lcom/exepretranslator/app/MainActivity;->refreshUi()V

    const/4 v0, 0x1

    iput-boolean v0, p0, Lcom/exepretranslator/app/MainActivity;->tickRunning:Z

    invoke-virtual {p0}, Lcom/exepretranslator/app/MainActivity;->run()V

    return-void
.end method

.method public run()V
    .locals 3

    iget-boolean v0, p0, Lcom/exepretranslator/app/MainActivity;->tickRunning:Z

    if-nez v0, :cond_0

    return-void

    :cond_0
    invoke-direct {p0}, Lcom/exepretranslator/app/MainActivity;->refreshUi()V

    iget-object v0, p0, Lcom/exepretranslator/app/MainActivity;->handler:Landroid/os/Handler;

    const-wide/16 v1, 0x3e8

    invoke-virtual {v0, p0, v1, v2}, Landroid/os/Handler;->postDelayed(Ljava/lang/Runnable;J)Z

    return-void
.end method

.method private startExampleExec()V
    .locals 6

    :try_start_0
    invoke-virtual {p0}, Landroid/app/Activity;->getAssets()Landroid/content/res/AssetManager;

    move-result-object v0

    const-string v1, "teste.exe"

    invoke-virtual {v0, v1}, Landroid/content/res/AssetManager;->open(Ljava/lang/String;)Ljava/io/InputStream;

    move-result-object v0

    invoke-virtual {p0}, Landroid/app/Activity;->getFilesDir()Ljava/io/File;

    move-result-object v1

    const-string v2, "teste.exe"

    new-instance v3, Ljava/io/File;

    invoke-direct {v3, v1, v2}, Ljava/io/File;-><init>(Ljava/io/File;Ljava/lang/String;)V

    new-instance v1, Ljava/io/FileOutputStream;

    invoke-direct {v1, v3}, Ljava/io/FileOutputStream;-><init>(Ljava/io/File;)V

    const/16 v2, 0x1000

    new-array v2, v2, [B

    :copy_loop
    invoke-virtual {v0, v2}, Ljava/io/InputStream;->read([B)I

    move-result v4

    if-ltz v4, :copy_done

    const/4 v5, 0x0

    invoke-virtual {v1, v2, v5, v4}, Ljava/io/FileOutputStream;->write([BII)V

    goto :copy_loop

    :copy_done
    invoke-virtual {v1}, Ljava/io/FileOutputStream;->close()V

    invoke-virtual {v0}, Ljava/io/InputStream;->close()V

    new-instance v0, Ljava/lang/StringBuilder;

    invoke-direct {v0}, Ljava/lang/StringBuilder;-><init>()V

    const-string v1, "file://"

    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-virtual {v3}, Ljava/io/File;->getAbsolutePath()Ljava/lang/String;

    move-result-object v1

    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;

    move-result-object v0

    new-instance v1, Landroid/content/Intent;

    const-class v2, Lcom/exepretranslator/app/ExecuteService;

    invoke-direct {v1, p0, v2}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V

    const-string v2, "uri"

    invoke-virtual {v1, v2, v0}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;

    invoke-virtual {p0, v1}, Landroid/content/Context;->startService(Landroid/content/Intent;)Landroid/content/ComponentName;
    :try_end_0
    .catch Ljava/lang/Exception; {:try_start_0 .. :try_end_0} :catch_0

    return-void

    :catch_0
    move-exception v0

    const-string v0, "Erro ao preparar o exemplo embutido"

    const/4 v1, 0x1

    invoke-static {p0, v0, v1}, Landroid/widget/Toast;->makeText(Landroid/content/Context;Ljava/lang/CharSequence;I)Landroid/widget/Toast;

    move-result-object v0

    invoke-virtual {v0}, Landroid/widget/Toast;->show()V

    return-void
.end method
