.class public final Lcom/ggufchat/app/GenerationResult;
.super Ljava/lang/Object;
.source "GenerationResult.java"

# Native.generate() returning false must not be announced as a completed reply.
# The caller's existing Exception handler broadcasts ERROR and releases the wake lock.
.method public static check(ZJ)V
    .locals 2
    if-eqz p0, :failed
    sget-object v0, Ljava/lang/System;->out:Ljava/io/PrintStream;
    const-string v1, "GGUF_REPAIR_GENERATION_OK"
    invoke-virtual {v0, v1}, Ljava/io/PrintStream;->println(Ljava/lang/String;)V
    return-void
    :failed
    sget-object v0, Ljava/lang/System;->out:Ljava/io/PrintStream;
    const-string v1, "GGUF_REPAIR_GENERATION_FAILED"
    invoke-virtual {v0, v1}, Ljava/io/PrintStream;->println(Ljava/lang/String;)V
    invoke-static {p1, p2}, Lcom/ggufchat/app/Native;->lastError(J)Ljava/lang/String;
    move-result-object v0
    if-eqz v0, :default_error
    invoke-virtual {v0}, Ljava/lang/String;->isEmpty()Z
    move-result v1
    if-eqz v1, :throw_error
    :default_error
    const-string v0, "Geração interrompida ou falhou. Nenhuma resposta completa foi produzida."
    :throw_error
    new-instance v1, Ljava/lang/Exception;
    invoke-direct {v1, v0}, Ljava/lang/Exception;-><init>(Ljava/lang/String;)V
    throw v1
.end method
