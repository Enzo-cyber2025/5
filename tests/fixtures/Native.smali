.class public Lcom/ggufchat/app/Native;
.super Ljava/lang/Object;

# TEST DOUBLE ONLY. Never included in the delivered APK.
.field public static calls:I
.field public static destroys:I
.field public static mmproj:Ljava/lang/String;
.field public static gpu:I
.field public static failGpu:Z
.field public static failAll:Z

.method public static create(Ljava/lang/String;Ljava/lang/String;IIIZ)J
    .locals 2
    sget v0, Lcom/ggufchat/app/Native;->calls:I
    add-int/lit8 v0, v0, 0x1
    sput v0, Lcom/ggufchat/app/Native;->calls:I
    sput-object p1, Lcom/ggufchat/app/Native;->mmproj:Ljava/lang/String;
    sput p4, Lcom/ggufchat/app/Native;->gpu:I
    sget-boolean v0, Lcom/ggufchat/app/Native;->failAll:Z
    if-nez v0, :failed
    if-eqz p4, :success
    sget-boolean v0, Lcom/ggufchat/app/Native;->failGpu:Z
    if-nez v0, :failed
    :success
    sget v0, Lcom/ggufchat/app/Native;->calls:I
    int-to-long v0, v0
    return-wide v0
    :failed
    const-wide/16 v0, 0x0
    return-wide v0
.end method

.method public static destroy(J)V
    .locals 1
    sget v0, Lcom/ggufchat/app/Native;->destroys:I
    add-int/lit8 v0, v0, 0x1
    sput v0, Lcom/ggufchat/app/Native;->destroys:I
    return-void
.end method

.method public static backendName(J)Ljava/lang/String;
    .locals 1
    const-string v0, "TEST DOUBLE, not native inference"
    return-object v0
.end method

.field public static error:Ljava/lang/String;
.method public static lastError(J)Ljava/lang/String;
    .locals 1
    sget-object v0, Lcom/ggufchat/app/Native;->error:Ljava/lang/String;
    return-object v0
.end method
