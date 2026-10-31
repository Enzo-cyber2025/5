.class public Lcom/exepretranslator/app/ExecuteService;
.super Landroid/app/Service;
.implements Ljava/lang/Runnable;


# instance fields
.field private channel:Ljava/nio/channels/FileChannel;

.field private currentUri:Ljava/lang/String;

.field private lastError:Ljava/lang/String;

.field private mem:[B

.field private regs:[I

.field private opClass:[I

.field private modKind:[I

.field private modReg:[I

.field private modDisp:[I

.field private regSel:[I

.field private immVal:[I

.field private instrLen:[I

.field private codeVAddr:I

.field private codeCap:I

.field private secVAddr:[I

.field private secRawPtr:[I

.field private secRawSize:[I

.field private numSec:I

.field private mrKind:I

.field private mrVal:I

.field private mrReg:I

.field private mrDisp:I

.field private mrBad:Z

.field private entryRva:I

.field private imageBase:I

.field private sizeOfImage:I

.field private memTotal:I

.field private zf:Z

.field private sfFlag:Z

.field private cfFlag:Z

.field private ofFlag:Z


# direct methods
.method public constructor <init>()V
    .locals 0

    invoke-direct {p0}, Landroid/app/Service;-><init>()V

    return-void
.end method

.method private static readU16([BI)I
    .locals 3

    aget-byte v0, p0, p1

    and-int/lit16 v0, v0, 0xff

    add-int/lit8 v1, p1, 0x1

    aget-byte v1, p0, v1

    and-int/lit16 v1, v1, 0xff

    const/16 v2, 0x8

    shl-int/2addr v1, v2

    or-int/2addr v0, v1

    return v0
.end method

.method private static readU32([BI)I
    .locals 4

    aget-byte v0, p0, p1

    and-int/lit16 v0, v0, 0xff

    add-int/lit8 v1, p1, 0x1

    aget-byte v1, p0, v1

    and-int/lit16 v1, v1, 0xff

    const/16 v2, 0x8

    shl-int/2addr v1, v2

    or-int/2addr v0, v1

    add-int/lit8 v1, p1, 0x2

    aget-byte v1, p0, v1

    and-int/lit16 v1, v1, 0xff

    const/16 v3, 0x10

    shl-int/2addr v1, v3

    or-int/2addr v0, v1

    add-int/lit8 v1, p1, 0x3

    aget-byte v1, p0, v1

    and-int/lit16 v1, v1, 0xff

    const/16 v3, 0x18

    shl-int/2addr v1, v3

    or-int/2addr v0, v1

    return v0
.end method

.method private static readFully(Ljava/nio/channels/FileChannel;J[BII)Z
    .locals 3

    invoke-static {p3, p4, p5}, Ljava/nio/ByteBuffer;->wrap([BII)Ljava/nio/ByteBuffer;

    move-result-object v0

    move-wide v1, p1

    :goto_0
    invoke-virtual {v0}, Ljava/nio/ByteBuffer;->hasRemaining()Z

    move-result v2

    if-eqz v2, :cond_1

    :try_start_0
    invoke-interface {p0, v0, v1, v2}, Ljava/nio/channels/FileChannel;->read(Ljava/nio/ByteBuffer;J)I

    move-result v2
    :try_end_0
    .catch Ljava/lang/Exception; {:try_start_0 .. :try_end_0} :catch_0

    if-gtz v2, :cond_0

    const/4 v0, 0x0

    return v0

    :cond_0
    int-to-long v2, v2

    add-long/2addr v1, v2

    goto :goto_0

    :catch_0
    move-exception v2

    const/4 v0, 0x0

    return v0

    :cond_1
    const/4 v0, 0x1

    return v0
.end method

.method private static readFullyAt(Ljava/nio/channels/FileChannel;I[BII)Z
    .locals 8

    move-object v2, p0

    int-to-long v3, p1

    move-object v5, p2

    move v6, p3

    move v7, p4

    invoke-static/range {v2 .. v7}, Lcom/exepretranslator/app/ExecuteService;->readFully(Ljava/nio/channels/FileChannel;J[BII)Z

    move-result v0

    return v0
.end method

.method private prefs()Landroid/content/SharedPreferences;
    .locals 2

    const-string v0, "ptexe_prefs"

    const/4 v1, 0x0

    invoke-virtual {p0, v0, v1}, Landroid/app/Service;->getSharedPreferences(Ljava/lang/String;I)Landroid/content/SharedPreferences;

    move-result-object v0

    return-object v0
.end method

.method private openForFile(Ljava/lang/String;)Z
    .locals 3

    :try_start_0
    const-string v0, "content:"

    invoke-virtual {p1, v0}, Ljava/lang/String;->startsWith(Ljava/lang/String;)Z

    move-result v0

    if-eqz v0, :try_as_plain_file

    invoke-static {p1}, Landroid/net/Uri;->parse(Ljava/lang/String;)Landroid/net/Uri;

    move-result-object v0

    invoke-virtual {p0}, Landroid/app/Service;->getContentResolver()Landroid/content/ContentResolver;

    move-result-object v1

    const-string v2, "r"

    invoke-virtual {v1, v0, v2}, Landroid/content/ContentResolver;->openFileDescriptor(Landroid/net/Uri;Ljava/lang/String;)Landroid/os/ParcelFileDescriptor;

    move-result-object v0

    invoke-virtual {v0}, Landroid/os/ParcelFileDescriptor;->getFileDescriptor()Ljava/io/FileDescriptor;

    move-result-object v0

    new-instance v1, Ljava/io/FileInputStream;

    invoke-direct {v1, v0}, Ljava/io/FileInputStream;-><init>(Ljava/io/FileDescriptor;)V

    invoke-virtual {v1}, Ljava/io/FileInputStream;->getChannel()Ljava/nio/channels/FileChannel;

    move-result-object v0

    iput-object v0, p0, Lcom/exepretranslator/app/ExecuteService;->channel:Ljava/nio/channels/FileChannel;

    goto :ok

    :try_as_plain_file
    const-string v0, "file:"

    invoke-virtual {p1, v0}, Ljava/lang/String;->startsWith(Ljava/lang/String;)Z

    move-result v0

    if-eqz v0, :use_path_directly

    invoke-static {p1}, Landroid/net/Uri;->parse(Ljava/lang/String;)Landroid/net/Uri;

    move-result-object v0

    invoke-virtual {v0}, Landroid/net/Uri;->getPath()Ljava/lang/String;

    move-result-object v0

    goto :have_path

    :use_path_directly
    move-object v0, p1

    :have_path
    new-instance v1, Ljava/io/FileInputStream;

    invoke-direct {v1, v0}, Ljava/io/FileInputStream;-><init>(Ljava/lang/String;)V

    invoke-virtual {v1}, Ljava/io/FileInputStream;->getChannel()Ljava/nio/channels/FileChannel;

    move-result-object v0

    iput-object v0, p0, Lcom/exepretranslator/app/ExecuteService;->channel:Ljava/nio/channels/FileChannel;

    :ok
    :try_end_0
    .catch Ljava/lang/Exception; {:try_start_0 .. :try_end_0} :catch_0

    const/4 v0, 0x1

    return v0

    :catch_0
    move-exception v0

    const-string v0, "nao foi possivel abrir o arquivo selecionado"

    iput-object v0, p0, Lcom/exepretranslator/app/ExecuteService;->lastError:Ljava/lang/String;

    const/4 v0, 0x0

    return v0
.end method

.method private setResult(Ljava/lang/String;ILjava/lang/String;)V
    .locals 2

    invoke-direct {p0}, Lcom/exepretranslator/app/ExecuteService;->prefs()Landroid/content/SharedPreferences;

    move-result-object v0

    invoke-interface {v0}, Landroid/content/SharedPreferences;->edit()Landroid/content/SharedPreferences$Editor;

    move-result-object v0

    const-string v1, "exec_status"

    invoke-interface {v0, v1, p1}, Landroid/content/SharedPreferences$Editor;->putString(Ljava/lang/String;Ljava/lang/String;)Landroid/content/SharedPreferences$Editor;

    move-result-object v0

    const-string v1, "exec_result"

    invoke-interface {v0, v1, p2}, Landroid/content/SharedPreferences$Editor;->putInt(Ljava/lang/String;I)Landroid/content/SharedPreferences$Editor;

    move-result-object v0

    const-string v1, "exec_message"

    invoke-interface {v0, v1, p3}, Landroid/content/SharedPreferences$Editor;->putString(Ljava/lang/String;Ljava/lang/String;)Landroid/content/SharedPreferences$Editor;

    move-result-object v0

    invoke-interface {v0}, Landroid/content/SharedPreferences$Editor;->apply()V

    return-void
.end method

.method public onCreate()V
    .locals 0

    invoke-super {p0}, Landroid/app/Service;->onCreate()V

    return-void
.end method

.method public onBind(Landroid/content/Intent;)Landroid/os/IBinder;
    .locals 1

    const/4 v0, 0x0

    return-object v0
.end method

.method public onStartCommand(Landroid/content/Intent;II)I
    .locals 2

    if-eqz p1, :cond_0

    const-string v0, "uri"

    const/4 v1, 0x0

    invoke-virtual {p1, v0, v1}, Landroid/content/Intent;->getStringExtra(Ljava/lang/String;)Ljava/lang/String;

    move-result-object v0

    if-eqz v0, :cond_0

    iput-object v0, p0, Lcom/exepretranslator/app/ExecuteService;->currentUri:Ljava/lang/String;

    :cond_0
    new-instance v0, Ljava/lang/Thread;

    invoke-direct {v0, p0}, Ljava/lang/Thread;-><init>(Ljava/lang/Runnable;)V

    invoke-virtual {v0}, Ljava/lang/Thread;->start()V

    const/4 v0, 0x2

    return v0
.end method

.method public run()V
    .locals 3

    :try_start_0
    invoke-direct {p0}, Lcom/exepretranslator/app/ExecuteService;->process()V
    :try_end_0
    .catch Ljava/lang/Exception; {:try_start_0 .. :try_end_0} :catch_0

    goto :goto_0

    :catch_0
    move-exception v0

    const-string v1, "erro"

    const/4 v2, 0x0

    invoke-virtual {v0}, Ljava/lang/Exception;->toString()Ljava/lang/String;

    move-result-object v0

    invoke-direct {p0, v1, v2, v0}, Lcom/exepretranslator/app/ExecuteService;->setResult(Ljava/lang/String;ILjava/lang/String;)V

    :goto_0
    invoke-virtual {p0}, Landroid/app/Service;->stopSelf()V

    return-void
.end method

.method private process()V
    .locals 4

    const-string v0, "rodando"

    const/4 v1, 0x0

    const-string v2, ""

    invoke-direct {p0, v0, v1, v2}, Lcom/exepretranslator/app/ExecuteService;->setResult(Ljava/lang/String;ILjava/lang/String;)V

    iget-object v0, p0, Lcom/exepretranslator/app/ExecuteService;->currentUri:Ljava/lang/String;

    if-nez v0, :cond_0

    const-string v0, "erro"

    const-string v3, "nenhum arquivo selecionado"

    invoke-direct {p0, v0, v1, v3}, Lcom/exepretranslator/app/ExecuteService;->setResult(Ljava/lang/String;ILjava/lang/String;)V

    return-void

    :cond_0
    invoke-direct {p0, v0}, Lcom/exepretranslator/app/ExecuteService;->openForFile(Ljava/lang/String;)Z

    move-result v0

    if-nez v0, :cond_1

    const-string v0, "erro"

    iget-object v3, p0, Lcom/exepretranslator/app/ExecuteService;->lastError:Ljava/lang/String;

    invoke-direct {p0, v0, v1, v3}, Lcom/exepretranslator/app/ExecuteService;->setResult(Ljava/lang/String;ILjava/lang/String;)V

    return-void

    :cond_1
    invoke-direct {p0}, Lcom/exepretranslator/app/ExecuteService;->parsePE32()Z

    move-result v0

    if-nez v0, :cond_2

    const-string v0, "erro"

    iget-object v3, p0, Lcom/exepretranslator/app/ExecuteService;->lastError:Ljava/lang/String;

    invoke-direct {p0, v0, v1, v3}, Lcom/exepretranslator/app/ExecuteService;->setResult(Ljava/lang/String;ILjava/lang/String;)V

    return-void

    :cond_2
    invoke-direct {p0}, Lcom/exepretranslator/app/ExecuteService;->loadImage()Z

    move-result v0

    if-nez v0, :cond_3

    const-string v0, "erro"

    iget-object v3, p0, Lcom/exepretranslator/app/ExecuteService;->lastError:Ljava/lang/String;

    invoke-direct {p0, v0, v1, v3}, Lcom/exepretranslator/app/ExecuteService;->setResult(Ljava/lang/String;ILjava/lang/String;)V

    return-void

    :cond_3
    invoke-direct {p0}, Lcom/exepretranslator/app/ExecuteService;->preTranslate()Z

    invoke-direct {p0}, Lcom/exepretranslator/app/ExecuteService;->execute()V

    return-void
.end method

.method private parsePE32()Z
    .locals 15

    const/16 v0, 0x1000

    new-array v1, v0, [B

    iget-object v2, p0, Lcom/exepretranslator/app/ExecuteService;->channel:Ljava/nio/channels/FileChannel;

    const/4 v3, 0x0

    invoke-static {v2, v3, v1, v3, v0}, Lcom/exepretranslator/app/ExecuteService;->readFullyAt(Ljava/nio/channels/FileChannel;I[BII)Z

    move-result v2

    if-nez v2, :cond_hdr_ok

    const-string v0, "nao foi possivel ler o cabecalho (arquivo menor que 4096 bytes ou erro de leitura)"

    iput-object v0, p0, Lcom/exepretranslator/app/ExecuteService;->lastError:Ljava/lang/String;

    const/4 v0, 0x0

    return v0

    :cond_hdr_ok
    const/4 v2, 0x0

    aget-byte v2, v1, v2

    and-int/lit16 v2, v2, 0xff

    const/16 v3, 0x4d

    if-eq v2, v3, :mz_ok

    :mz_bad
    const-string v0, "arquivo nao parece ser um executavel PE (.exe) valido"

    iput-object v0, p0, Lcom/exepretranslator/app/ExecuteService;->lastError:Ljava/lang/String;

    const/4 v0, 0x0

    return v0

    :mz_ok
    const/16 v2, 0x3c

    invoke-static {v1, v2}, Lcom/exepretranslator/app/ExecuteService;->readU32([BI)I

    move-result v2

    const/16 v3, 0x200

    if-ge v2, v3, :mz_bad

    if-ltz v2, :mz_bad

    aget-byte v3, v1, v2

    and-int/lit16 v3, v3, 0xff

    const/16 v4, 0x50

    if-ne v3, v4, :mz_bad

    add-int/lit8 v4, v2, 0x1

    aget-byte v4, v1, v4

    and-int/lit16 v4, v4, 0xff

    const/16 v5, 0x45

    if-ne v4, v5, :mz_bad

    add-int/lit8 v3, v2, 0x4

    invoke-static {v1, v3}, Lcom/exepretranslator/app/ExecuteService;->readU16([BI)I

    move-result v3

    const/16 v4, 0x14c

    if-eq v3, v4, :cond_machine_ok

    const-string v0, "executor experimental so suporta PE32 de 32 bits (i386); use apenas a pre-traducao para este arquivo"

    iput-object v0, p0, Lcom/exepretranslator/app/ExecuteService;->lastError:Ljava/lang/String;

    const/4 v0, 0x0

    return v0

    :cond_machine_ok
    add-int/lit8 v4, v2, 0x6

    invoke-static {v1, v4}, Lcom/exepretranslator/app/ExecuteService;->readU16([BI)I

    move-result v4

    const/16 v5, 0x10

    if-le v4, v5, :mz_bad

    add-int/lit8 v5, v2, 0x14

    invoke-static {v1, v5}, Lcom/exepretranslator/app/ExecuteService;->readU16([BI)I

    move-result v5

    add-int/lit8 v6, v2, 0x18

    invoke-static {v1, v6}, Lcom/exepretranslator/app/ExecuteService;->readU16([BI)I

    move-result v6

    const/16 v7, 0x10b

    if-eq v6, v7, :cond_magic_ok

    const-string v0, "executor experimental so suporta PE32 (nao PE32+/64 bits)"

    iput-object v0, p0, Lcom/exepretranslator/app/ExecuteService;->lastError:Ljava/lang/String;

    const/4 v0, 0x0

    return v0

    :cond_magic_ok
    add-int/lit8 v6, v2, 0x18

    add-int/lit8 v6, v6, 0x10

    invoke-static {v1, v6}, Lcom/exepretranslator/app/ExecuteService;->readU32([BI)I

    move-result v6

    iput v6, p0, Lcom/exepretranslator/app/ExecuteService;->entryRva:I

    add-int/lit8 v6, v2, 0x18

    add-int/lit8 v6, v6, 0x1c

    invoke-static {v1, v6}, Lcom/exepretranslator/app/ExecuteService;->readU32([BI)I

    move-result v6

    iput v6, p0, Lcom/exepretranslator/app/ExecuteService;->imageBase:I

    add-int/lit8 v6, v2, 0x18

    add-int/lit8 v6, v6, 0x38

    invoke-static {v1, v6}, Lcom/exepretranslator/app/ExecuteService;->readU32([BI)I

    move-result v6

    iput v6, p0, Lcom/exepretranslator/app/ExecuteService;->sizeOfImage:I

    const v7, 0x1000000

    if-le v6, v7, :cond_size_ok

    const-string v0, "imagem grande demais para o modo de execucao experimental (limite 16MB)"

    iput-object v0, p0, Lcom/exepretranslator/app/ExecuteService;->lastError:Ljava/lang/String;

    const/4 v0, 0x0

    return v0

    :cond_size_ok
    add-int/lit8 v7, v2, 0x18

    add-int v7, v7, v5

    add-int/lit8 v8, v2, 0x4

    const/16 v9, 0x10

    if-gt v4, v9, :cap_sections

    move v9, v4

    goto :sections_count_set

    :cap_sections
    const/16 v9, 0x10

    :sections_count_set
    const/4 v2, 0x0

    new-array v2, v9, [I

    const/4 v3, 0x0

    new-array v3, v9, [I

    const/4 v4, 0x0

    new-array v4, v9, [I

    const/4 v6, 0x0

    :loop_sec
    if-ge v6, v9, :sec_done

    mul-int/lit8 v8, v6, 0x28

    add-int v8, v7, v8

    add-int/lit8 v10, v8, 0x8

    invoke-static {v1, v10}, Lcom/exepretranslator/app/ExecuteService;->readU32([BI)I

    move-result v11

    add-int/lit8 v10, v8, 0xc

    invoke-static {v1, v10}, Lcom/exepretranslator/app/ExecuteService;->readU32([BI)I

    move-result v12

    add-int/lit8 v10, v8, 0x10

    invoke-static {v1, v10}, Lcom/exepretranslator/app/ExecuteService;->readU32([BI)I

    move-result v13

    add-int/lit8 v10, v8, 0x14

    invoke-static {v1, v10}, Lcom/exepretranslator/app/ExecuteService;->readU32([BI)I

    move-result v14

    aput v12, v2, v6

    aput v14, v3, v6

    if-le v13, v11, :use_vsize

    move v10, v11

    goto :size_picked

    :use_vsize
    move v10, v13

    :size_picked
    aput v10, v4, v6

    add-int/lit8 v6, v6, 0x1

    goto :loop_sec

    :sec_done
    iget-object v0, p0, Lcom/exepretranslator/app/ExecuteService;->channel:Ljava/nio/channels/FileChannel;

    iput-object v2, p0, Lcom/exepretranslator/app/ExecuteService;->secVAddr:[I

    iput-object v3, p0, Lcom/exepretranslator/app/ExecuteService;->secRawPtr:[I

    iput-object v4, p0, Lcom/exepretranslator/app/ExecuteService;->secRawSize:[I

    iput v9, p0, Lcom/exepretranslator/app/ExecuteService;->numSec:I

    const/4 v6, 0x0

    :find_entry_sec
    if-ge v6, v9, :entry_not_found

    aget v10, v2, v6

    iget v11, p0, Lcom/exepretranslator/app/ExecuteService;->entryRva:I

    if-gt v10, v11, :next_sec

    aget v12, v4, v6

    add-int v12, v10, v12

    if-ge v11, v12, :next_sec

    iput v10, p0, Lcom/exepretranslator/app/ExecuteService;->codeVAddr:I

    aget v12, v4, v6

    const v13, 0x10000

    if-le v12, v13, :cond_cap_ok

    const-string v0, "secao de codigo grande demais para o modo de execucao experimental (limite 64KB)"

    iput-object v0, p0, Lcom/exepretranslator/app/ExecuteService;->lastError:Ljava/lang/String;

    const/4 v0, 0x0

    return v0

    :cond_cap_ok
    iput v12, p0, Lcom/exepretranslator/app/ExecuteService;->codeCap:I

    const/4 v0, 0x1

    return v0

    :next_sec
    add-int/lit8 v6, v6, 0x1

    goto :find_entry_sec

    :entry_not_found
    const-string v0, "ponto de entrada fora de qualquer secao conhecida"

    iput-object v0, p0, Lcom/exepretranslator/app/ExecuteService;->lastError:Ljava/lang/String;

    const/4 v0, 0x0

    return v0
.end method

.method private loadImage()Z
    .locals 12

    iget v0, p0, Lcom/exepretranslator/app/ExecuteService;->sizeOfImage:I

    const v1, 0x10000

    add-int/2addr v0, v1

    iput v0, p0, Lcom/exepretranslator/app/ExecuteService;->memTotal:I

    new-array v1, v0, [B

    iput-object v1, p0, Lcom/exepretranslator/app/ExecuteService;->mem:[B

    const/16 v1, 0x8

    new-array v1, v1, [I

    iput-object v1, p0, Lcom/exepretranslator/app/ExecuteService;->regs:[I

    iget v1, p0, Lcom/exepretranslator/app/ExecuteService;->codeCap:I

    new-array v2, v1, [I

    iput-object v2, p0, Lcom/exepretranslator/app/ExecuteService;->opClass:[I

    new-array v2, v1, [I

    iput-object v2, p0, Lcom/exepretranslator/app/ExecuteService;->modKind:[I

    new-array v2, v1, [I

    iput-object v2, p0, Lcom/exepretranslator/app/ExecuteService;->modReg:[I

    new-array v2, v1, [I

    iput-object v2, p0, Lcom/exepretranslator/app/ExecuteService;->modDisp:[I

    new-array v2, v1, [I

    iput-object v2, p0, Lcom/exepretranslator/app/ExecuteService;->regSel:[I

    new-array v2, v1, [I

    iput-object v2, p0, Lcom/exepretranslator/app/ExecuteService;->immVal:[I

    new-array v1, v1, [I

    iput-object v1, p0, Lcom/exepretranslator/app/ExecuteService;->instrLen:[I

    iget v1, p0, Lcom/exepretranslator/app/ExecuteService;->numSec:I

    const/4 v2, 0x0

    :loop_load
    if-ge v2, v1, :load_done

    iget-object v3, p0, Lcom/exepretranslator/app/ExecuteService;->secRawSize:[I

    aget v3, v3, v2

    if-gtz v3, :cond_nonempty

    goto :next_load

    :cond_nonempty
    iget-object v4, p0, Lcom/exepretranslator/app/ExecuteService;->secVAddr:[I

    aget v4, v4, v2

    iget v5, p0, Lcom/exepretranslator/app/ExecuteService;->sizeOfImage:I

    add-int v6, v4, v3

    if-le v6, v5, :cond_fits

    goto :next_load

    :cond_fits
    new-array v6, v3, [B

    iget-object v7, p0, Lcom/exepretranslator/app/ExecuteService;->channel:Ljava/nio/channels/FileChannel;

    iget-object v8, p0, Lcom/exepretranslator/app/ExecuteService;->secRawPtr:[I

    aget v8, v8, v2

    const/4 v9, 0x0

    invoke-static {v7, v8, v6, v9, v3}, Lcom/exepretranslator/app/ExecuteService;->readFullyAt(Ljava/nio/channels/FileChannel;I[BII)Z

    move-result v7

    if-nez v7, :cond_read_ok

    const-string v0, "falha ao carregar uma secao na memoria virtual"

    iput-object v0, p0, Lcom/exepretranslator/app/ExecuteService;->lastError:Ljava/lang/String;

    const/4 v0, 0x0

    return v0

    :cond_read_ok
    iget-object v7, p0, Lcom/exepretranslator/app/ExecuteService;->mem:[B

    invoke-static {v6, v9, v7, v4, v3}, Ljava/lang/System;->arraycopy(Ljava/lang/Object;ILjava/lang/Object;II)V

    :next_load
    add-int/lit8 v2, v2, 0x1

    goto :loop_load

    :load_done
    iget-object v0, p0, Lcom/exepretranslator/app/ExecuteService;->regs:[I

    const/4 v1, 0x4

    iget v2, p0, Lcom/exepretranslator/app/ExecuteService;->memTotal:I

    const/16 v3, 0x10

    sub-int/2addr v2, v3

    aput v2, v0, v1

    const/4 v0, 0x1

    return v0
.end method

.method private decodeModRM(I)I
    .locals 6

    iget-object v0, p0, Lcom/exepretranslator/app/ExecuteService;->mem:[B

    aget-byte v0, v0, p1

    and-int/lit16 v0, v0, 0xff

    shr-int/lit8 v1, v0, 0x6

    and-int/lit8 v1, v1, 0x3

    shr-int/lit8 v2, v0, 0x3

    and-int/lit8 v2, v2, 0x7

    and-int/lit8 v3, v0, 0x7

    const/4 v4, 0x0

    iput-boolean v4, p0, Lcom/exepretranslator/app/ExecuteService;->mrBad:Z

    const/4 v4, 0x3

    if-ne v1, v4, :mod_not3

    const/4 v4, 0x0

    iput v4, p0, Lcom/exepretranslator/app/ExecuteService;->mrKind:I

    iput v3, p0, Lcom/exepretranslator/app/ExecuteService;->mrVal:I

    iput v2, p0, Lcom/exepretranslator/app/ExecuteService;->mrReg:I

    add-int/lit8 v4, p1, 0x1

    return v4

    :mod_not3
    const/4 v4, 0x4

    if-ne v3, v4, :bad_addr

    const/4 v4, 0x0

    if-nez v1, :mod_disp_chk

    const/4 v4, 0x5

    if-ne v3, v4, :bad_addr

    const/4 v4, 0x1

    iput v4, p0, Lcom/exepretranslator/app/ExecuteService;->mrKind:I

    iput v3, p0, Lcom/exepretranslator/app/ExecuteService;->mrVal:I

    iput v2, p0, Lcom/exepretranslator/app/ExecuteService;->mrReg:I

    const/4 v4, 0x0

    iput v4, p0, Lcom/exepretranslator/app/ExecuteService;->mrDisp:I

    add-int/lit8 v4, p1, 0x1

    return v4

    :mod_disp_chk
    const/4 v4, 0x1

    if-ne v1, v4, :mod2

    add-int/lit8 v4, p1, 0x1

    iget-object v5, p0, Lcom/exepretranslator/app/ExecuteService;->mem:[B

    aget-byte v4, v5, v4

    const/4 v5, 0x1

    iput v5, p0, Lcom/exepretranslator/app/ExecuteService;->mrKind:I

    iput v3, p0, Lcom/exepretranslator/app/ExecuteService;->mrVal:I

    iput v2, p0, Lcom/exepretranslator/app/ExecuteService;->mrReg:I

    iput v4, p0, Lcom/exepretranslator/app/ExecuteService;->mrDisp:I

    add-int/lit8 v4, p1, 0x2

    return v4

    :mod2
    add-int/lit8 v4, p1, 0x1

    iget-object v5, p0, Lcom/exepretranslator/app/ExecuteService;->mem:[B

    invoke-static {v5, v4}, Lcom/exepretranslator/app/ExecuteService;->readU32([BI)I

    move-result v4

    const/4 v5, 0x1

    iput v5, p0, Lcom/exepretranslator/app/ExecuteService;->mrKind:I

    iput v3, p0, Lcom/exepretranslator/app/ExecuteService;->mrVal:I

    iput v2, p0, Lcom/exepretranslator/app/ExecuteService;->mrReg:I

    iput v4, p0, Lcom/exepretranslator/app/ExecuteService;->mrDisp:I

    add-int/lit8 v4, p1, 0x5

    return v4

    :bad_addr
    const/4 v4, 0x1

    iput-boolean v4, p0, Lcom/exepretranslator/app/ExecuteService;->mrBad:Z

    return p1
.end method

.method private decodeAt(I)I
    .locals 8

    iget-object v0, p0, Lcom/exepretranslator/app/ExecuteService;->mem:[B

    aget-byte v0, v0, p1

    and-int/lit16 v0, v0, 0xff

    const/16 v1, 0x50

    if-lt v0, v1, :chk_pop

    const/16 v1, 0x57

    if-gt v0, v1, :chk_pop

    const/16 v1, 0x50

    sub-int/2addr v0, v1

    iget v1, p0, Lcom/exepretranslator/app/ExecuteService;->codeVAddr:I

    sub-int v1, p1, v1

    iget-object v2, p0, Lcom/exepretranslator/app/ExecuteService;->opClass:[I

    const/4 v3, 0x1

    aput v3, v2, v1

    iget-object v2, p0, Lcom/exepretranslator/app/ExecuteService;->regSel:[I

    aput v0, v2, v1

    iget-object v2, p0, Lcom/exepretranslator/app/ExecuteService;->instrLen:[I

    const/4 v3, 0x1

    aput v3, v2, v1

    const/4 v0, 0x1

    return v0

    :chk_pop
    const/16 v1, 0x58

    if-lt v0, v1, :chk_89

    const/16 v1, 0x5f

    if-gt v0, v1, :chk_89

    const/16 v1, 0x58

    sub-int/2addr v0, v1

    iget v1, p0, Lcom/exepretranslator/app/ExecuteService;->codeVAddr:I

    sub-int v1, p1, v1

    iget-object v2, p0, Lcom/exepretranslator/app/ExecuteService;->opClass:[I

    const/4 v3, 0x2

    aput v3, v2, v1

    iget-object v2, p0, Lcom/exepretranslator/app/ExecuteService;->regSel:[I

    aput v0, v2, v1

    iget-object v2, p0, Lcom/exepretranslator/app/ExecuteService;->instrLen:[I

    const/4 v3, 0x1

    aput v3, v2, v1

    const/4 v0, 0x1

    return v0

    :chk_89
    const/16 v1, 0x89

    if-ne v0, v1, :chk_8b

    add-int/lit8 v1, p1, 0x1

    invoke-direct {p0, v1}, Lcom/exepretranslator/app/ExecuteService;->decodeModRM(I)I

    move-result v2

    iget-boolean v1, p0, Lcom/exepretranslator/app/ExecuteService;->mrBad:Z

    if-eqz v1, :mov89_ok

    const/4 v0, 0x0

    return v0

    :mov89_ok
    sub-int v3, v2, p1

    const/4 v4, 0x3

    invoke-direct {p0, p1, v4, v3}, Lcom/exepretranslator/app/ExecuteService;->storeDecoded(III)V

    return v3

    :chk_8b
    const/16 v1, 0x8b

    if-ne v0, v1, :chk_c7

    add-int/lit8 v1, p1, 0x1

    invoke-direct {p0, v1}, Lcom/exepretranslator/app/ExecuteService;->decodeModRM(I)I

    move-result v2

    iget-boolean v1, p0, Lcom/exepretranslator/app/ExecuteService;->mrBad:Z

    if-eqz v1, :mov8b_ok

    const/4 v0, 0x0

    return v0

    :mov8b_ok
    sub-int v3, v2, p1

    const/4 v4, 0x4

    invoke-direct {p0, p1, v4, v3}, Lcom/exepretranslator/app/ExecuteService;->storeDecoded(III)V

    return v3

    :chk_c7
    const/16 v1, 0xc7

    if-ne v0, v1, :chk_03

    add-int/lit8 v1, p1, 0x1

    invoke-direct {p0, v1}, Lcom/exepretranslator/app/ExecuteService;->decodeModRM(I)I

    move-result v2

    iget-boolean v1, p0, Lcom/exepretranslator/app/ExecuteService;->mrBad:Z

    if-eqz v1, :c7_chk_digit

    const/4 v0, 0x0

    return v0

    :c7_chk_digit
    iget v1, p0, Lcom/exepretranslator/app/ExecuteService;->mrReg:I

    if-eqz v1, :c7_ok

    const/4 v0, 0x0

    return v0

    :c7_ok
    iget-object v1, p0, Lcom/exepretranslator/app/ExecuteService;->mem:[B

    invoke-static {v1, v2}, Lcom/exepretranslator/app/ExecuteService;->readU32([BI)I

    move-result v3

    iget v4, p0, Lcom/exepretranslator/app/ExecuteService;->codeVAddr:I

    sub-int v4, p1, v4

    iget-object v5, p0, Lcom/exepretranslator/app/ExecuteService;->immVal:[I

    aput v3, v5, v4

    add-int/lit8 v5, v2, 0x4

    sub-int v5, v5, p1

    const/4 v6, 0x5

    invoke-direct {p0, p1, v6, v5}, Lcom/exepretranslator/app/ExecuteService;->storeDecoded(III)V

    return v5

    :chk_03
    const/16 v1, 0x3

    if-ne v0, v1, :chk_83

    add-int/lit8 v1, p1, 0x1

    invoke-direct {p0, v1}, Lcom/exepretranslator/app/ExecuteService;->decodeModRM(I)I

    move-result v2

    iget-boolean v1, p0, Lcom/exepretranslator/app/ExecuteService;->mrBad:Z

    if-eqz v1, :add03_ok

    const/4 v0, 0x0

    return v0

    :add03_ok
    sub-int v3, v2, p1

    const/4 v4, 0x6

    invoke-direct {p0, p1, v4, v3}, Lcom/exepretranslator/app/ExecuteService;->storeDecoded(III)V

    return v3

    :chk_83
    const/16 v1, 0x83

    if-ne v0, v1, :chk_7f

    add-int/lit8 v1, p1, 0x1

    invoke-direct {p0, v1}, Lcom/exepretranslator/app/ExecuteService;->decodeModRM(I)I

    move-result v2

    iget-boolean v1, p0, Lcom/exepretranslator/app/ExecuteService;->mrBad:Z

    if-eqz v1, :g1_chk_digit

    const/4 v0, 0x0

    return v0

    :g1_chk_digit
    iget v1, p0, Lcom/exepretranslator/app/ExecuteService;->mrReg:I

    if-eqz v1, :g1_digit_ok

    const/4 v3, 0x5

    if-eq v1, v3, :g1_digit_ok

    const/4 v3, 0x7

    if-eq v1, v3, :g1_digit_ok

    const/4 v0, 0x0

    return v0

    :g1_digit_ok
    iget-object v1, p0, Lcom/exepretranslator/app/ExecuteService;->mem:[B

    aget-byte v3, v1, v2

    iget v4, p0, Lcom/exepretranslator/app/ExecuteService;->codeVAddr:I

    sub-int v4, p1, v4

    iget-object v5, p0, Lcom/exepretranslator/app/ExecuteService;->immVal:[I

    aput v3, v5, v4

    add-int/lit8 v5, v2, 0x1

    sub-int v5, v5, p1

    const/4 v6, 0x7

    invoke-direct {p0, p1, v6, v5}, Lcom/exepretranslator/app/ExecuteService;->storeDecoded(III)V

    return v5

    :chk_7f
    const/16 v1, 0x7f

    if-ne v0, v1, :chk_eb

    add-int/lit8 v1, p1, 0x1

    iget-object v2, p0, Lcom/exepretranslator/app/ExecuteService;->mem:[B

    aget-byte v1, v2, v1

    add-int/lit8 v2, p1, 0x2

    add-int/2addr v2, v1

    iget v3, p0, Lcom/exepretranslator/app/ExecuteService;->codeVAddr:I

    sub-int v3, p1, v3

    iget-object v4, p0, Lcom/exepretranslator/app/ExecuteService;->opClass:[I

    const/16 v5, 0x8

    aput v5, v4, v3

    iget-object v4, p0, Lcom/exepretranslator/app/ExecuteService;->immVal:[I

    aput v2, v4, v3

    iget-object v4, p0, Lcom/exepretranslator/app/ExecuteService;->instrLen:[I

    const/4 v5, 0x2

    aput v5, v4, v3

    const/4 v0, 0x2

    return v0

    :chk_eb
    const/16 v1, 0xeb

    if-ne v0, v1, :chk_c3

    add-int/lit8 v1, p1, 0x1

    iget-object v2, p0, Lcom/exepretranslator/app/ExecuteService;->mem:[B

    aget-byte v1, v2, v1

    add-int/lit8 v2, p1, 0x2

    add-int/2addr v2, v1

    iget v3, p0, Lcom/exepretranslator/app/ExecuteService;->codeVAddr:I

    sub-int v3, p1, v3

    iget-object v4, p0, Lcom/exepretranslator/app/ExecuteService;->opClass:[I

    const/16 v5, 0x9

    aput v5, v4, v3

    iget-object v4, p0, Lcom/exepretranslator/app/ExecuteService;->immVal:[I

    aput v2, v4, v3

    iget-object v4, p0, Lcom/exepretranslator/app/ExecuteService;->instrLen:[I

    const/4 v5, 0x2

    aput v5, v4, v3

    const/4 v0, 0x2

    return v0

    :chk_c3
    const/16 v1, 0xc3

    if-ne v0, v1, :chk_90

    iget v1, p0, Lcom/exepretranslator/app/ExecuteService;->codeVAddr:I

    sub-int v1, p1, v1

    iget-object v2, p0, Lcom/exepretranslator/app/ExecuteService;->opClass:[I

    const/16 v3, 0xa

    aput v3, v2, v1

    iget-object v2, p0, Lcom/exepretranslator/app/ExecuteService;->instrLen:[I

    const/4 v3, 0x1

    aput v3, v2, v1

    const/4 v0, 0x1

    return v0

    :chk_90
    const/16 v1, 0x90

    if-ne v0, v1, :unsupported

    iget v1, p0, Lcom/exepretranslator/app/ExecuteService;->codeVAddr:I

    sub-int v1, p1, v1

    iget-object v2, p0, Lcom/exepretranslator/app/ExecuteService;->opClass:[I

    const/16 v3, 0xb

    aput v3, v2, v1

    iget-object v2, p0, Lcom/exepretranslator/app/ExecuteService;->instrLen:[I

    const/4 v3, 0x1

    aput v3, v2, v1

    const/4 v0, 0x1

    return v0

    :unsupported
    const/4 v0, 0x0

    return v0
.end method

.method private storeDecoded(III)V
    .locals 2

    iget v0, p0, Lcom/exepretranslator/app/ExecuteService;->codeVAddr:I

    sub-int v0, p1, v0

    iget-object v1, p0, Lcom/exepretranslator/app/ExecuteService;->opClass:[I

    aput p2, v1, v0

    iget-object v1, p0, Lcom/exepretranslator/app/ExecuteService;->modKind:[I

    iget v2, p0, Lcom/exepretranslator/app/ExecuteService;->mrKind:I

    aput v2, v1, v0

    iget-object v1, p0, Lcom/exepretranslator/app/ExecuteService;->modReg:[I

    iget v2, p0, Lcom/exepretranslator/app/ExecuteService;->mrVal:I

    aput v2, v1, v0

    iget-object v1, p0, Lcom/exepretranslator/app/ExecuteService;->modDisp:[I

    iget v2, p0, Lcom/exepretranslator/app/ExecuteService;->mrDisp:I

    aput v2, v1, v0

    iget-object v1, p0, Lcom/exepretranslator/app/ExecuteService;->regSel:[I

    iget v2, p0, Lcom/exepretranslator/app/ExecuteService;->mrReg:I

    aput v2, v1, v0

    iget-object v1, p0, Lcom/exepretranslator/app/ExecuteService;->instrLen:[I

    aput p3, v1, v0

    return-void
.end method

.method private memSet32(II)V
    .locals 3

    iget-object v0, p0, Lcom/exepretranslator/app/ExecuteService;->mem:[B

    aput-byte p2, v0, p1

    shr-int/lit8 v1, p2, 0x8

    add-int/lit8 v2, p1, 0x1

    aput-byte v1, v0, v2

    shr-int/lit8 v1, p2, 0x10

    add-int/lit8 v2, p1, 0x2

    aput-byte v1, v0, v2

    shr-int/lit8 v1, p2, 0x18

    add-int/lit8 v2, p1, 0x3

    aput-byte v1, v0, v2

    return-void
.end method

.method private setFlagsSub(III)V
    .locals 3

    if-nez p3, :nz

    const/4 v0, 0x1

    goto :zfset

    :nz
    const/4 v0, 0x0

    :zfset
    iput-boolean v0, p0, Lcom/exepretranslator/app/ExecuteService;->zf:Z

    if-gez p3, :nonneg

    const/4 v0, 0x1

    goto :sfset

    :nonneg
    const/4 v0, 0x0

    :sfset
    iput-boolean v0, p0, Lcom/exepretranslator/app/ExecuteService;->sfFlag:Z

    xor-int v1, p1, p2

    xor-int v2, p1, p3

    and-int/2addr v1, v2

    if-gez v1, :ofclear

    const/4 v0, 0x1

    goto :ofset

    :ofclear
    const/4 v0, 0x0

    :ofset
    iput-boolean v0, p0, Lcom/exepretranslator/app/ExecuteService;->ofFlag:Z

    return-void
.end method

.method private execute()V
    .locals 15

    iget v0, p0, Lcom/exepretranslator/app/ExecuteService;->entryRva:I

    const/4 v1, 0x0

    :loop_exec
    add-int/lit8 v1, v1, 0x1

    const v2, 0x186a0

    if-le v1, v2, :steps_ok

    const-string v2, "erro"

    const/4 v3, 0x0

    const-string v4, "limite de passos excedido (possivel loop infinito)"

    invoke-direct {p0, v2, v3, v4}, Lcom/exepretranslator/app/ExecuteService;->setResult(Ljava/lang/String;ILjava/lang/String;)V

    return-void

    :steps_ok
    iget v2, p0, Lcom/exepretranslator/app/ExecuteService;->codeVAddr:I

    sub-int v3, v0, v2

    iget v2, p0, Lcom/exepretranslator/app/ExecuteService;->codeCap:I

    if-ltz v3, :halt_oob

    if-ge v3, v2, :halt_oob

    iget-object v2, p0, Lcom/exepretranslator/app/ExecuteService;->opClass:[I

    aget v4, v2, v3

    if-nez v4, :known_op

    goto :halt_oob

    :known_op
    const/4 v2, 0x1

    if-ne v4, v2, :op_pop

    iget-object v5, p0, Lcom/exepretranslator/app/ExecuteService;->regs:[I

    const/4 v6, 0x4

    aget v7, v5, v6

    const/4 v8, 0x4

    sub-int/2addr v7, v8

    aput v7, v5, v6

    iget-object v8, p0, Lcom/exepretranslator/app/ExecuteService;->regSel:[I

    aget v8, v8, v3

    aget v8, v5, v8

    invoke-direct {p0, v7, v8}, Lcom/exepretranslator/app/ExecuteService;->memSet32(II)V

    iget-object v5, p0, Lcom/exepretranslator/app/ExecuteService;->instrLen:[I

    aget v5, v5, v3

    add-int/2addr v0, v5

    goto :loop_exec

    :op_pop
    const/4 v2, 0x2

    if-ne v4, v2, :op_mov_rm_r

    iget-object v5, p0, Lcom/exepretranslator/app/ExecuteService;->regs:[I

    const/4 v6, 0x4

    aget v7, v5, v6

    iget-object v8, p0, Lcom/exepretranslator/app/ExecuteService;->mem:[B

    invoke-static {v8, v7}, Lcom/exepretranslator/app/ExecuteService;->readU32([BI)I

    move-result v8

    iget-object v9, p0, Lcom/exepretranslator/app/ExecuteService;->regSel:[I

    aget v9, v9, v3

    aput v8, v5, v9

    const/4 v8, 0x4

    add-int/2addr v7, v8

    aput v7, v5, v6

    iget-object v5, p0, Lcom/exepretranslator/app/ExecuteService;->instrLen:[I

    aget v5, v5, v3

    add-int/2addr v0, v5

    goto :loop_exec

    :op_mov_rm_r
    const/4 v2, 0x3

    if-ne v4, v2, :op_mov_r_rm

    iget-object v5, p0, Lcom/exepretranslator/app/ExecuteService;->modKind:[I

    aget v5, v5, v3

    iget-object v6, p0, Lcom/exepretranslator/app/ExecuteService;->regs:[I

    iget-object v7, p0, Lcom/exepretranslator/app/ExecuteService;->regSel:[I

    aget v7, v7, v3

    aget v7, v6, v7

    if-nez v5, :mov89_mem

    iget-object v8, p0, Lcom/exepretranslator/app/ExecuteService;->modReg:[I

    aget v8, v8, v3

    aput v7, v6, v8

    goto :mov89_done

    :mov89_mem
    iget-object v8, p0, Lcom/exepretranslator/app/ExecuteService;->modReg:[I

    aget v8, v8, v3

    aget v8, v6, v8

    iget-object v9, p0, Lcom/exepretranslator/app/ExecuteService;->modDisp:[I

    aget v9, v9, v3

    add-int/2addr v8, v9

    invoke-direct {p0, v8, v7}, Lcom/exepretranslator/app/ExecuteService;->memSet32(II)V

    :mov89_done
    iget-object v5, p0, Lcom/exepretranslator/app/ExecuteService;->instrLen:[I

    aget v5, v5, v3

    add-int/2addr v0, v5

    goto :loop_exec

    :op_mov_r_rm
    const/4 v2, 0x4

    if-ne v4, v2, :op_mov_rm_imm

    iget-object v5, p0, Lcom/exepretranslator/app/ExecuteService;->modKind:[I

    aget v5, v5, v3

    iget-object v6, p0, Lcom/exepretranslator/app/ExecuteService;->regs:[I

    iget-object v8, p0, Lcom/exepretranslator/app/ExecuteService;->modReg:[I

    aget v8, v8, v3

    if-nez v5, :mov8b_mem

    aget v7, v6, v8

    goto :mov8b_have

    :mov8b_mem
    aget v9, v6, v8

    iget-object v10, p0, Lcom/exepretranslator/app/ExecuteService;->modDisp:[I

    aget v10, v10, v3

    add-int/2addr v9, v10

    iget-object v11, p0, Lcom/exepretranslator/app/ExecuteService;->mem:[B

    invoke-static {v11, v9}, Lcom/exepretranslator/app/ExecuteService;->readU32([BI)I

    move-result v7

    :mov8b_have
    iget-object v9, p0, Lcom/exepretranslator/app/ExecuteService;->regSel:[I

    aget v9, v9, v3

    aput v7, v6, v9

    iget-object v5, p0, Lcom/exepretranslator/app/ExecuteService;->instrLen:[I

    aget v5, v5, v3

    add-int/2addr v0, v5

    goto :loop_exec

    :op_mov_rm_imm
    const/4 v2, 0x5

    if-ne v4, v2, :op_add_r_rm

    iget-object v5, p0, Lcom/exepretranslator/app/ExecuteService;->modKind:[I

    aget v5, v5, v3

    iget-object v6, p0, Lcom/exepretranslator/app/ExecuteService;->regs:[I

    iget-object v7, p0, Lcom/exepretranslator/app/ExecuteService;->immVal:[I

    aget v7, v7, v3

    if-nez v5, :c7_mem

    iget-object v8, p0, Lcom/exepretranslator/app/ExecuteService;->modReg:[I

    aget v8, v8, v3

    aput v7, v6, v8

    goto :c7_done

    :c7_mem
    iget-object v8, p0, Lcom/exepretranslator/app/ExecuteService;->modReg:[I

    aget v8, v8, v3

    aget v8, v6, v8

    iget-object v9, p0, Lcom/exepretranslator/app/ExecuteService;->modDisp:[I

    aget v9, v9, v3

    add-int/2addr v8, v9

    invoke-direct {p0, v8, v7}, Lcom/exepretranslator/app/ExecuteService;->memSet32(II)V

    :c7_done
    iget-object v5, p0, Lcom/exepretranslator/app/ExecuteService;->instrLen:[I

    aget v5, v5, v3

    add-int/2addr v0, v5

    goto :loop_exec

    :op_add_r_rm
    const/4 v2, 0x6

    if-ne v4, v2, :op_grp1

    iget-object v5, p0, Lcom/exepretranslator/app/ExecuteService;->modKind:[I

    aget v5, v5, v3

    iget-object v6, p0, Lcom/exepretranslator/app/ExecuteService;->regs:[I

    iget-object v8, p0, Lcom/exepretranslator/app/ExecuteService;->modReg:[I

    aget v8, v8, v3

    if-nez v5, :add03_mem

    aget v7, v6, v8

    goto :add03_have

    :add03_mem
    aget v9, v6, v8

    iget-object v10, p0, Lcom/exepretranslator/app/ExecuteService;->modDisp:[I

    aget v10, v10, v3

    add-int/2addr v9, v10

    iget-object v11, p0, Lcom/exepretranslator/app/ExecuteService;->mem:[B

    invoke-static {v11, v9}, Lcom/exepretranslator/app/ExecuteService;->readU32([BI)I

    move-result v7

    :add03_have
    iget-object v9, p0, Lcom/exepretranslator/app/ExecuteService;->regSel:[I

    aget v9, v9, v3

    aget v10, v6, v9

    add-int v10, v10, v7

    aput v10, v6, v9

    iget-object v5, p0, Lcom/exepretranslator/app/ExecuteService;->instrLen:[I

    aget v5, v5, v3

    add-int/2addr v0, v5

    goto :loop_exec

    :op_grp1
    const/4 v2, 0x7

    if-ne v4, v2, :op_jg

    iget-object v5, p0, Lcom/exepretranslator/app/ExecuteService;->modKind:[I

    aget v5, v5, v3

    iget-object v6, p0, Lcom/exepretranslator/app/ExecuteService;->regs:[I

    iget-object v8, p0, Lcom/exepretranslator/app/ExecuteService;->modReg:[I

    aget v8, v8, v3

    iget-object v9, p0, Lcom/exepretranslator/app/ExecuteService;->immVal:[I

    aget v9, v9, v3

    if-nez v5, :g1_mem

    aget v7, v6, v8

    goto :g1_have

    :g1_mem
    aget v10, v6, v8

    iget-object v11, p0, Lcom/exepretranslator/app/ExecuteService;->modDisp:[I

    aget v11, v11, v3

    add-int/2addr v10, v11

    iget-object v12, p0, Lcom/exepretranslator/app/ExecuteService;->mem:[B

    invoke-static {v12, v10}, Lcom/exepretranslator/app/ExecuteService;->readU32([BI)I

    move-result v7

    :g1_have
    iget-object v10, p0, Lcom/exepretranslator/app/ExecuteService;->regSel:[I

    aget v10, v10, v3

    if-nez v10, :g1_not_add

    add-int v11, v7, v9

    if-nez v5, :g1_add_mem

    aput v11, v6, v8

    goto :g1_done

    :g1_add_mem
    aget v12, v6, v8

    iget-object v13, p0, Lcom/exepretranslator/app/ExecuteService;->modDisp:[I

    aget v13, v13, v3

    add-int/2addr v12, v13

    invoke-direct {p0, v12, v11}, Lcom/exepretranslator/app/ExecuteService;->memSet32(II)V

    goto :g1_done

    :g1_not_add
    const/4 v11, 0x5

    if-ne v10, v11, :g1_cmp

    sub-int v11, v7, v9

    invoke-direct {p0, v7, v9, v11}, Lcom/exepretranslator/app/ExecuteService;->setFlagsSub(III)V

    if-nez v5, :g1_sub_mem

    aput v11, v6, v8

    goto :g1_done

    :g1_sub_mem
    aget v12, v6, v8

    iget-object v13, p0, Lcom/exepretranslator/app/ExecuteService;->modDisp:[I

    aget v13, v13, v3

    add-int/2addr v12, v13

    invoke-direct {p0, v12, v11}, Lcom/exepretranslator/app/ExecuteService;->memSet32(II)V

    goto :g1_done

    :g1_cmp
    sub-int v11, v7, v9

    invoke-direct {p0, v7, v9, v11}, Lcom/exepretranslator/app/ExecuteService;->setFlagsSub(III)V

    :g1_done
    iget-object v5, p0, Lcom/exepretranslator/app/ExecuteService;->instrLen:[I

    aget v5, v5, v3

    add-int/2addr v0, v5

    goto :loop_exec

    :op_jg
    const/16 v2, 0x8

    if-ne v4, v2, :op_jmp

    iget-boolean v5, p0, Lcom/exepretranslator/app/ExecuteService;->zf:Z

    if-nez v5, :jg_no

    iget-boolean v5, p0, Lcom/exepretranslator/app/ExecuteService;->sfFlag:Z

    iget-boolean v6, p0, Lcom/exepretranslator/app/ExecuteService;->ofFlag:Z

    if-ne v5, v6, :jg_no

    iget-object v5, p0, Lcom/exepretranslator/app/ExecuteService;->immVal:[I

    aget v0, v5, v3

    goto :loop_exec

    :jg_no
    iget-object v5, p0, Lcom/exepretranslator/app/ExecuteService;->instrLen:[I

    aget v5, v5, v3

    add-int/2addr v0, v5

    goto :loop_exec

    :op_jmp
    const/16 v2, 0x9

    if-ne v4, v2, :op_ret

    iget-object v5, p0, Lcom/exepretranslator/app/ExecuteService;->immVal:[I

    aget v0, v5, v3

    goto :loop_exec

    :op_ret
    const/16 v2, 0xa

    if-ne v4, v2, :op_nop

    iget-object v5, p0, Lcom/exepretranslator/app/ExecuteService;->regs:[I

    const/4 v6, 0x0

    aget v5, v5, v6

    const-string v6, "concluido"

    const-string v7, ""

    invoke-direct {p0, v6, v5, v7}, Lcom/exepretranslator/app/ExecuteService;->setResult(Ljava/lang/String;ILjava/lang/String;)V

    return-void

    :op_nop
    iget-object v5, p0, Lcom/exepretranslator/app/ExecuteService;->instrLen:[I

    aget v5, v5, v3

    add-int/2addr v0, v5

    goto :loop_exec

    :halt_oob
    const-string v5, "erro"

    const/4 v6, 0x0

    new-instance v7, Ljava/lang/StringBuilder;

    invoke-direct {v7}, Ljava/lang/StringBuilder;-><init>()V

    const-string v8, "execucao chegou a um ponto nao suportado (chamada externa/instrucao fora do codigo pre-traduzido) em rva=0x"

    invoke-virtual {v7, v8}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-static {v0}, Ljava/lang/Integer;->toHexString(I)Ljava/lang/String;

    move-result-object v8

    invoke-virtual {v7, v8}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-virtual {v7}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;

    move-result-object v7

    invoke-direct {p0, v5, v6, v7}, Lcom/exepretranslator/app/ExecuteService;->setResult(Ljava/lang/String;ILjava/lang/String;)V

    return-void
.end method

.method private preTranslate()Z
    .locals 6

    iget v0, p0, Lcom/exepretranslator/app/ExecuteService;->codeVAddr:I

    iget v1, p0, Lcom/exepretranslator/app/ExecuteService;->codeCap:I

    const/4 v2, 0x0

    :loop_pt
    if-ge v2, v1, :pt_done

    add-int v3, v0, v2

    invoke-direct {p0, v3}, Lcom/exepretranslator/app/ExecuteService;->decodeAt(I)I

    move-result v4

    if-gtz v4, :pt_advance

    goto :pt_done

    :pt_advance
    add-int/2addr v2, v4

    goto :loop_pt

    :pt_done
    const/4 v0, 0x1

    return v0
.end method
