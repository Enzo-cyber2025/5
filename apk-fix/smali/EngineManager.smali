.class public final Lcom/ggufchat/app/EngineManager;
.super Ljava/lang/Object;
.source "EngineManager.java"


# static fields
.field private static final LOCK:Ljava/lang/Object;

.field private static handle:J

.field private static loadedMmproj:Ljava/lang/String;

.field private static loadedPath:Ljava/lang/String;

# Every engine-creation option participates in the cache key.
.field private static loadedContext:I
.field private static loadedThreads:I
.field private static loadedGpuLayers:I
.field private static loadedMmap:Z


# direct methods
.method static constructor <clinit>()V
    .locals 3

    .prologue
    const/4 v2, 0x0

    .line 14
    new-instance v0, Ljava/lang/Object;

    invoke-direct {v0}, Ljava/lang/Object;-><init>()V

    sput-object v0, Lcom/ggufchat/app/EngineManager;->LOCK:Ljava/lang/Object;

    .line 15
    const-wide/16 v0, 0x0

    sput-wide v0, Lcom/ggufchat/app/EngineManager;->handle:J

    .line 16
    sput-object v2, Lcom/ggufchat/app/EngineManager;->loadedPath:Ljava/lang/String;

    .line 17
    sput-object v2, Lcom/ggufchat/app/EngineManager;->loadedMmproj:Ljava/lang/String;

    return-void
.end method

.method private constructor <init>()V
    .locals 0

    .prologue
    .line 19
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V

    .line 20
    return-void
.end method

.method public static backend()Ljava/lang/String;
    .locals 6

    .prologue
    .line 55
    sget-object v1, Lcom/ggufchat/app/EngineManager;->LOCK:Ljava/lang/Object;

    monitor-enter v1

    .line 56
    :try_start_0
    sget-wide v2, Lcom/ggufchat/app/EngineManager;->handle:J

    const-wide/16 v4, 0x0

    cmp-long v0, v2, v4

    if-eqz v0, :cond_0

    sget-wide v2, Lcom/ggufchat/app/EngineManager;->handle:J

    invoke-static {v2, v3}, Lcom/ggufchat/app/Native;->backendName(J)Ljava/lang/String;

    move-result-object v0

    :goto_0
    monitor-exit v1

    return-object v0

    :cond_0
    const-string v0, "\u2014"

    goto :goto_0

    .line 57
    :catchall_0
    move-exception v0

    monitor-exit v1
    :try_end_0
    .catchall {:try_start_0 .. :try_end_0} :catchall_0

    throw v0
.end method

.method public static currentHandle()J
    .locals 4

    .prologue
    .line 49
    sget-object v1, Lcom/ggufchat/app/EngineManager;->LOCK:Ljava/lang/Object;

    monitor-enter v1

    .line 50
    :try_start_0
    sget-wide v2, Lcom/ggufchat/app/EngineManager;->handle:J

    monitor-exit v1

    return-wide v2

    .line 51
    :catchall_0
    move-exception v0

    monitor-exit v1
    :try_end_0
    .catchall {:try_start_0 .. :try_end_0} :catchall_0

    throw v0
.end method

.method public static load(Ljava/lang/String;Ljava/lang/String;IIIZ)J
    .locals 7
    .annotation system Ldalvik/annotation/Throws;
        value = {
            Ljava/lang/Exception;
        }
    .end annotation

    .prologue
    # Preserve the requested backend even if create() falls back to CPU.
    move v6, p4
    const-wide/16 v4, 0x0

    if-eqz p1, :cond_1

    invoke-virtual {p1}, Ljava/lang/String;->isEmpty()Z

    move-result v0

    if-eqz v0, :cond_0

    const/4 p1, 0x0

    goto :goto_0

    :cond_0
    const-string v0, "null"

    invoke-virtual {p1, v0}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z

    move-result v0

    if-eqz v0, :cond_1

    const/4 p1, 0x0

    .line 25
    :cond_1
    :goto_0
    # Never hand a missing/truncated/non-GGUF file to the native loader.
    # Validate before releasing an existing good engine.
    invoke-static {p0}, Lcom/ggufchat/app/EngineManager;->validateFile(Ljava/lang/String;)V
    if-eqz p1, :validated
    invoke-static {p1}, Lcom/ggufchat/app/EngineManager;->validateFile(Ljava/lang/String;)V
    :validated
    sget-object v2, Lcom/ggufchat/app/EngineManager;->LOCK:Ljava/lang/Object;

    monitor-enter v2

    .line 26
    :try_start_0
    sget-wide v0, Lcom/ggufchat/app/EngineManager;->handle:J

    cmp-long v0, v0, v4

    if-eqz v0, :cond_4

    sget v0, Lcom/ggufchat/app/EngineManager;->loadedContext:I
    if-ne v0, p2, :cond_4
    sget v0, Lcom/ggufchat/app/EngineManager;->loadedThreads:I
    if-ne v0, p3, :cond_4
    sget v0, Lcom/ggufchat/app/EngineManager;->loadedGpuLayers:I
    if-ne v0, p4, :cond_4
    sget-boolean v0, Lcom/ggufchat/app/EngineManager;->loadedMmap:Z
    if-ne v0, p5, :cond_4

    sget-object v0, Lcom/ggufchat/app/EngineManager;->loadedPath:Ljava/lang/String;
    if-eqz v0, :cond_4

    sget-object v0, Lcom/ggufchat/app/EngineManager;->loadedPath:Ljava/lang/String;

    invoke-virtual {v0, p0}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z

    move-result v0

    if-eqz v0, :cond_4

    sget-object v0, Lcom/ggufchat/app/EngineManager;->loadedMmproj:Ljava/lang/String;

    if-eqz v0, :cond_2

    invoke-virtual {v0, p1}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z

    move-result v0

    if-eqz v0, :cond_4

    goto :goto_1

    :cond_2
    if-eqz p1, :cond_3

    goto :goto_3

    .line 27
    :cond_3
    :goto_1
    sget-wide v0, Lcom/ggufchat/app/EngineManager;->handle:J

    monitor-exit v2

    .line 44
    :goto_2
    return-wide v0

    .line 29
    :cond_4
    :goto_3
    sget-wide v0, Lcom/ggufchat/app/EngineManager;->handle:J

    cmp-long v0, v0, v4

    if-eqz v0, :cond_5

    .line 30
    sget-wide v0, Lcom/ggufchat/app/EngineManager;->handle:J

    invoke-static {v0, v1}, Lcom/ggufchat/app/Native;->destroy(J)V

    .line 31
    const-wide/16 v0, 0x0

    sput-wide v0, Lcom/ggufchat/app/EngineManager;->handle:J

    .line 32
    const/4 v0, 0x0

    sput-object v0, Lcom/ggufchat/app/EngineManager;->loadedPath:Ljava/lang/String;

    .line 33
    const/4 v0, 0x0

    sput-object v0, Lcom/ggufchat/app/EngineManager;->loadedMmproj:Ljava/lang/String;

    .line 35
    :cond_5
    invoke-static/range {p0 .. p5}, Lcom/ggufchat/app/Native;->create(Ljava/lang/String;Ljava/lang/String;IIIZ)J

    move-result-wide v0

    .line 37
    cmp-long v3, v0, v4

    if-nez v3, :cond_7

    if-eqz p4, :cond_6

    const/4 p4, 0x0

    invoke-static/range {p0 .. p5}, Lcom/ggufchat/app/Native;->create(Ljava/lang/String;Ljava/lang/String;IIIZ)J

    move-result-wide v0

    cmp-long v3, v0, v4

    if-nez v3, :cond_7

    .line 38
    :cond_6
    new-instance v0, Ljava/lang/Exception;

    const-string v1, "N\u00e3o foi poss\u00edvel carregar o modelo. Verifique se o arquivo GGUF est\u00e1 \u00edntegro."

    invoke-direct {v0, v1}, Ljava/lang/Exception;-><init>(Ljava/lang/String;)V

    throw v0

    .line 45
    :catchall_0
    move-exception v0

    monitor-exit v2
    :try_end_0
    .catchall {:try_start_0 .. :try_end_0} :catchall_0

    throw v0

    .line 41
    :cond_7
    :try_start_1
    sput-wide v0, Lcom/ggufchat/app/EngineManager;->handle:J

    .line 42
    sput-object p0, Lcom/ggufchat/app/EngineManager;->loadedPath:Ljava/lang/String;

    .line 43
    sput-object p1, Lcom/ggufchat/app/EngineManager;->loadedMmproj:Ljava/lang/String;
    sput p2, Lcom/ggufchat/app/EngineManager;->loadedContext:I
    sput p3, Lcom/ggufchat/app/EngineManager;->loadedThreads:I
    sput v6, Lcom/ggufchat/app/EngineManager;->loadedGpuLayers:I
    sput-boolean p5, Lcom/ggufchat/app/EngineManager;->loadedMmap:Z

    .line 44
    monitor-exit v2
    :try_end_1
    .catchall {:try_start_1 .. :try_end_1} :catchall_0

    goto :goto_2
.end method

.method public static release()V
    .locals 6

    .prologue
    const-wide/16 v4, 0x0

    .line 62
    sget-object v1, Lcom/ggufchat/app/EngineManager;->LOCK:Ljava/lang/Object;

    monitor-enter v1

    .line 63
    :try_start_0
    sget-wide v2, Lcom/ggufchat/app/EngineManager;->handle:J

    cmp-long v0, v2, v4

    if-eqz v0, :cond_0

    .line 64
    sget-wide v2, Lcom/ggufchat/app/EngineManager;->handle:J

    invoke-static {v2, v3}, Lcom/ggufchat/app/Native;->destroy(J)V

    .line 65
    const-wide/16 v2, 0x0

    sput-wide v2, Lcom/ggufchat/app/EngineManager;->handle:J

    .line 66
    const/4 v0, 0x0

    sput-object v0, Lcom/ggufchat/app/EngineManager;->loadedPath:Ljava/lang/String;

    .line 67
    const/4 v0, 0x0

    sput-object v0, Lcom/ggufchat/app/EngineManager;->loadedMmproj:Ljava/lang/String;

    .line 69
    :cond_0
    monitor-exit v1

    .line 70
    return-void

    .line 69
    :catchall_0
    move-exception v0

    monitor-exit v1
    :try_end_0
    .catchall {:try_start_0 .. :try_end_0} :catchall_0

    throw v0
.end method

# Basic header guard, not a complete GGUF/tensor compatibility validator.
.method private static validateFile(Ljava/lang/String;)V
    .locals 6
    if-eqz p0, :invalid
    new-instance v0, Ljava/io/File;
    invoke-direct {v0, p0}, Ljava/io/File;-><init>(Ljava/lang/String;)V
    invoke-virtual {v0}, Ljava/io/File;->isFile()Z
    move-result v1
    if-eqz v1, :invalid
    invoke-virtual {v0}, Ljava/io/File;->canRead()Z
    move-result v1
    if-eqz v1, :invalid
    invoke-virtual {v0}, Ljava/io/File;->length()J
    move-result-wide v1
    const-wide/16 v3, 0x18
    cmp-long v1, v1, v3
    if-ltz v1, :invalid

    new-instance v1, Ljava/io/RandomAccessFile;
    const-string v2, "r"
    invoke-direct {v1, v0, v2}, Ljava/io/RandomAccessFile;-><init>(Ljava/io/File;Ljava/lang/String;)V
    :read_start
    invoke-virtual {v1}, Ljava/io/RandomAccessFile;->readInt()I
    move-result v2
    const v3, 0x47475546
    if-ne v2, v3, :bad_header
    invoke-virtual {v1}, Ljava/io/RandomAccessFile;->readInt()I
    move-result v2
    const v3, 0x02000000
    if-eq v2, v3, :good_header
    const v3, 0x03000000
    if-ne v2, v3, :bad_header
    :good_header
    const/4 v5, 0x1
    goto :close_file
    :bad_header
    const/4 v5, 0x0
    :read_end
    .catchall {:read_start .. :read_end} :read_failed
    :close_file
    invoke-virtual {v1}, Ljava/io/RandomAccessFile;->close()V
    if-eqz v5, :invalid
    return-void

    :read_failed
    move-exception v0
    :cleanup_start
    invoke-virtual {v1}, Ljava/io/RandomAccessFile;->close()V
    :cleanup_end
    .catchall {:cleanup_start .. :cleanup_end} :close_failed
    throw v0
    :close_failed
    move-exception v2
    throw v0

    :invalid
    new-instance v0, Ljava/io/IOException;
    const-string v1, "Arquivo GGUF ausente, ilegível ou com cabeçalho inválido. Importe novamente o modelo/projetor."
    invoke-direct {v0, v1}, Ljava/io/IOException;-><init>(Ljava/lang/String;)V
    throw v0
.end method
