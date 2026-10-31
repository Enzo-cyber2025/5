.class public Lcom/exepretranslator/app/TranslateService;
.super Landroid/app/Service;
.implements Ljava/lang/Runnable;


# static fields
.field private static ONE_INFO:[B

.field private static TWO_INFO:[B

.field private static MNEMONIC:[Ljava/lang/String;

.field private static ARM_HINT:[Ljava/lang/String;


# instance fields
.field private codeOff:I

.field private codeSize:I

.field private pe64:I

.field private lastError:Ljava/lang/String;

.field private currentUri:Ljava/lang/String;

.field private channel:Ljava/nio/channels/FileChannel;

.field private out:Ljava/io/PrintStream;

.field private wakeLock:Landroid/os/PowerManager$WakeLock;


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

    shl-int/lit8 v1, v1, 0x8

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

    shl-int/lit8 v1, v1, 0x8

    or-int/2addr v0, v1

    add-int/lit8 v1, p1, 0x2

    aget-byte v1, p0, v1

    and-int/lit16 v1, v1, 0xff

    shl-int/lit8 v1, v1, 0x10

    or-int/2addr v0, v1

    add-int/lit8 v1, p1, 0x3

    aget-byte v1, p0, v1

    and-int/lit16 v1, v1, 0xff

    shl-int/lit8 v1, v1, 0x18

    or-int/2addr v0, v1

    return v0
.end method

.method private static readFully(Ljava/nio/channels/FileChannel;J[BII)Z
    .locals 3

    invoke-virtual {p0, p1, p2}, Ljava/nio/channels/FileChannel;->position(J)Ljava/nio/channels/FileChannel;

    invoke-static {p3, p4, p5}, Ljava/nio/ByteBuffer;->wrap([BII)Ljava/nio/ByteBuffer;

    move-result-object v0

    :goto_0
    invoke-virtual {v0}, Ljava/nio/ByteBuffer;->hasRemaining()Z

    move-result v1

    if-eqz v1, :cond_1

    invoke-virtual {p0, v0}, Ljava/nio/channels/FileChannel;->read(Ljava/nio/ByteBuffer;)I

    move-result v1

    if-gez v1, :cond_0

    const/4 v2, 0x0

    return v2

    :cond_0
    goto :goto_0

    :cond_1
    const/4 v1, 0x1

    return v1
.end method

.method private static mnemonicFor(IZ)Ljava/lang/String;
    .locals 2

    if-eqz p1, :cond_0

    const-string v0, "0F xx"

    return-object v0

    :cond_0
    sget-object v0, Lcom/exepretranslator/app/TranslateService;->MNEMONIC:[Ljava/lang/String;

    aget-object v0, v0, p0

    if-nez v0, :cond_1

    const-string v0, "db (opcode nao mapeado)"

    :cond_1
    return-object v0
.end method

.method private static armHintFor(IZ)Ljava/lang/String;
    .locals 2

    if-eqz p1, :cond_0

    const-string v0, "(sem mapeamento)"

    return-object v0

    :cond_0
    sget-object v0, Lcom/exepretranslator/app/TranslateService;->ARM_HINT:[Ljava/lang/String;

    aget-object v0, v0, p0

    if-nez v0, :cond_1

    const-string v0, "(sem mapeamento)"

    :cond_1
    return-object v0
.end method

.method private static hex2(Ljava/lang/StringBuilder;I)V
    .locals 2

    const-string v0, "0123456789abcdef"

    shr-int/lit8 v1, p1, 0x4

    and-int/lit8 v1, v1, 0xf

    invoke-virtual {v0, v1}, Ljava/lang/String;->charAt(I)C

    move-result v1

    invoke-virtual {p0, v1}, Ljava/lang/StringBuilder;->append(C)Ljava/lang/StringBuilder;

    and-int/lit8 v1, p1, 0xf

    invoke-virtual {v0, v1}, Ljava/lang/String;->charAt(I)C

    move-result v1

    invoke-virtual {p0, v1}, Ljava/lang/StringBuilder;->append(C)Ljava/lang/StringBuilder;

    return-void
.end method

.method private static hex8(Ljava/lang/StringBuilder;I)V
    .locals 1

    shr-int/lit8 v0, p1, 0x18

    and-int/lit16 v0, v0, 0xff

    invoke-static {p0, v0}, Lcom/exepretranslator/app/TranslateService;->hex2(Ljava/lang/StringBuilder;I)V

    shr-int/lit8 v0, p1, 0x10

    and-int/lit16 v0, v0, 0xff

    invoke-static {p0, v0}, Lcom/exepretranslator/app/TranslateService;->hex2(Ljava/lang/StringBuilder;I)V

    shr-int/lit8 v0, p1, 0x8

    and-int/lit16 v0, v0, 0xff

    invoke-static {p0, v0}, Lcom/exepretranslator/app/TranslateService;->hex2(Ljava/lang/StringBuilder;I)V

    and-int/lit16 v0, p1, 0xff

    invoke-static {p0, v0}, Lcom/exepretranslator/app/TranslateService;->hex2(Ljava/lang/StringBuilder;I)V

    return-void
.end method

.method private static appendInstrLine(Ljava/io/PrintStream;I[BII)V
    .locals 5

    and-int/lit16 v4, p4, 0xffff

    new-instance v0, Ljava/lang/StringBuilder;

    invoke-direct {v0}, Ljava/lang/StringBuilder;-><init>()V

    const-string v1, "+0x"

    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-static {v0, p1}, Lcom/exepretranslator/app/TranslateService;->hex8(Ljava/lang/StringBuilder;I)V

    const-string v1, "  bytes="

    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    const/4 v1, 0x0

    :goto_0
    if-ge v1, v4, :cond_0

    add-int v2, p3, v1

    aget-byte v2, p2, v2

    and-int/lit16 v2, v2, 0xff

    invoke-static {v0, v2}, Lcom/exepretranslator/app/TranslateService;->hex2(Ljava/lang/StringBuilder;I)V

    add-int/lit8 v1, v1, 0x1

    goto :goto_0

    :cond_0
    shr-int/lit8 v1, p4, 0x10

    and-int/lit16 v1, v1, 0xff

    shr-int/lit8 v2, p4, 0x18

    and-int/lit8 v2, v2, 0x1

    const-string v3, "  x86="

    invoke-virtual {v0, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-static {v1, v2}, Lcom/exepretranslator/app/TranslateService;->mnemonicFor(IZ)Ljava/lang/String;

    move-result-object v3

    invoke-virtual {v0, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    const-string v3, "  arm64~"

    invoke-virtual {v0, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-static {v1, v2}, Lcom/exepretranslator/app/TranslateService;->armHintFor(IZ)Ljava/lang/String;

    move-result-object v1

    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;

    move-result-object v0

    invoke-virtual {p0, v0}, Ljava/io/PrintStream;->println(Ljava/lang/String;)V

    return-void
.end method

.method private static decodeOne([BIII)I
    .locals 16

    move/from16 v0, p1

    move/from16 v14, p2

    move/from16 v15, p3

    const/4 v1, 0x0

    :prefix_loop
    if-ge v0, v14, :prefix_done

    aget-byte v2, p0, v0

    and-int/lit16 v2, v2, 0xff

    sget-object v5, Lcom/exepretranslator/app/TranslateService;->ONE_INFO:[B

    aget-byte v3, v5, v2

    and-int/lit8 v4, v3, 0x8

    if-eqz v4, :prefix_done

    const/16 v5, 0x66

    if-ne v2, v5, :prefix_skipmark

    const/4 v1, 0x1

    :prefix_skipmark
    add-int/lit8 v0, v0, 0x1

    goto :prefix_loop

    :prefix_done
    const/4 v6, 0x0

    if-eqz v15, :rex_skip

    if-ge v0, v14, :rex_skip

    aget-byte v2, p0, v0

    and-int/lit16 v2, v2, 0xff

    const/16 v5, 0x40

    if-lt v2, v5, :rex_skip

    const/16 v5, 0x4f

    if-gt v2, v5, :rex_skip

    and-int/lit8 v5, v2, 0x8

    if-eqz v5, :rex_noW

    const/4 v6, 0x1

    :rex_noW
    add-int/lit8 v0, v0, 0x1

    :rex_skip
    const/4 v7, 0x0

    if-ge v0, v14, :op_fallback

    aget-byte v2, p0, v0

    and-int/lit16 v2, v2, 0xff

    add-int/lit8 v0, v0, 0x1

    const/16 v5, 0xf

    if-ne v2, v5, :op_not0f

    const/4 v7, 0x1

    if-ge v0, v14, :op_fallback

    aget-byte v8, p0, v0

    and-int/lit16 v8, v8, 0xff

    add-int/lit8 v0, v0, 0x1

    move v2, v8

    sget-object v5, Lcom/exepretranslator/app/TranslateService;->TWO_INFO:[B

    aget-byte v10, v5, v2

    goto :have_info

    :op_not0f
    sget-object v5, Lcom/exepretranslator/app/TranslateService;->ONE_INFO:[B

    aget-byte v10, v5, v2

    :have_info
    and-int/lit8 v11, v10, 0x1

    shr-int/lit8 v9, v10, 0x1

    and-int/lit8 v10, v9, 0x3

    const/4 v12, 0x0

    if-eqz v11, :no_modrm

    if-ge v0, v14, :finalize

    aget-byte v13, p0, v0

    and-int/lit16 v13, v13, 0xff

    add-int/lit8 v0, v0, 0x1

    shr-int/lit8 v3, v13, 0x6

    and-int/lit8 v3, v3, 0x3

    and-int/lit8 v4, v13, 0x7

    shr-int/lit8 v12, v13, 0x3

    and-int/lit8 v12, v12, 0x7

    const/4 v8, -0x1

    const/4 v5, 0x3

    if-eq v3, v5, :no_sib

    const/4 v5, 0x4

    if-ne v4, v5, :no_sib

    if-ge v0, v14, :finalize

    aget-byte v8, p0, v0

    and-int/lit16 v8, v8, 0xff

    add-int/lit8 v0, v0, 0x1

    and-int/lit8 v8, v8, 0x7

    :no_sib
    const/4 v9, 0x0

    if-nez v3, :mod_not0

    const/4 v5, 0x5

    if-eq v4, v5, :disp_set4

    if-ne v8, v5, :disp_done

    :disp_set4
    const/4 v9, 0x4

    goto :disp_done

    :mod_not0
    const/4 v5, 0x1

    if-ne v3, v5, :mod_not1

    const/4 v9, 0x1

    goto :disp_done

    :mod_not1
    const/4 v5, 0x2

    if-ne v3, v5, :disp_done

    const/4 v9, 0x4

    :disp_done
    add-int/2addr v0, v9

    if-le v0, v14, :no_clamp1

    move v0, v14

    :no_clamp1
    :no_modrm
    const/4 v9, 0x0

    const/4 v5, 0x1

    if-ne v10, v5, :not_imm8

    const/4 v9, 0x1

    goto :imm_done

    :not_imm8
    const/4 v5, 0x2

    if-ne v10, v5, :not_immz

    if-eqz v1, :immz4

    const/4 v9, 0x2

    goto :imm_done

    :immz4
    const/4 v9, 0x4

    goto :imm_done

    :not_immz
    const/4 v5, 0x3

    if-ne v10, v5, :imm_done

    const/4 v9, 0x2

    :imm_done
    if-nez v7, :after_special

    const/16 v5, 0xf6

    if-ne v2, v5, :chk_f7

    const/4 v9, 0x0

    const/4 v5, 0x2

    if-ge v12, v5, :after_special

    const/4 v9, 0x1

    goto :after_special

    :chk_f7
    const/16 v5, 0xf7

    if-ne v2, v5, :chk_b8

    const/4 v9, 0x0

    const/4 v5, 0x2

    if-ge v12, v5, :after_special

    if-eqz v1, :f7_4

    const/4 v9, 0x2

    goto :after_special

    :f7_4
    const/4 v9, 0x4

    goto :after_special

    :chk_b8
    const/16 v5, 0xb8

    if-lt v2, v5, :after_special

    const/16 v5, 0xbf

    if-gt v2, v5, :after_special

    if-eqz v15, :after_special

    if-eqz v6, :after_special

    const/16 v9, 0x8

    :after_special
    add-int/2addr v0, v9

    if-le v0, v14, :no_clamp2

    move v0, v14

    :no_clamp2
    :finalize
    sub-int v5, v0, p1

    const/4 v9, 0x1

    if-ge v5, v9, :len_ok

    const/4 v5, 0x1

    :len_ok
    shl-int/lit8 v4, v2, 0x10

    or-int/2addr v5, v4

    shl-int/lit8 v4, v7, 0x18

    or-int/2addr v5, v4

    return v5

    :op_fallback
    const/4 v5, 0x1

    return v5
.end method
.method static constructor <clinit>()V
    .locals 3

    const/16 v0, 0x100
    new-array v0, v0, [B
    fill-array-data v0, :one_info_data
    sput-object v0, Lcom/exepretranslator/app/TranslateService;->ONE_INFO:[B

    const/16 v0, 0x100
    new-array v0, v0, [B
    fill-array-data v0, :two_info_data
    sput-object v0, Lcom/exepretranslator/app/TranslateService;->TWO_INFO:[B

    const/16 v0, 0x100
    new-array v0, v0, [Ljava/lang/String;
    const-string v1, "add"
    const/16 v2, 0x0
    aput-object v1, v0, v2
    const-string v1, "add"
    const/16 v2, 0x1
    aput-object v1, v0, v2
    const-string v1, "add"
    const/16 v2, 0x2
    aput-object v1, v0, v2
    const-string v1, "add"
    const/16 v2, 0x3
    aput-object v1, v0, v2
    const-string v1, "add"
    const/16 v2, 0x4
    aput-object v1, v0, v2
    const-string v1, "add"
    const/16 v2, 0x5
    aput-object v1, v0, v2
    const-string v1, "or"
    const/16 v2, 0x8
    aput-object v1, v0, v2
    const-string v1, "or"
    const/16 v2, 0x9
    aput-object v1, v0, v2
    const-string v1, "or"
    const/16 v2, 0xa
    aput-object v1, v0, v2
    const-string v1, "or"
    const/16 v2, 0xb
    aput-object v1, v0, v2
    const-string v1, "or"
    const/16 v2, 0xc
    aput-object v1, v0, v2
    const-string v1, "or"
    const/16 v2, 0xd
    aput-object v1, v0, v2
    const-string v1, "adc"
    const/16 v2, 0x10
    aput-object v1, v0, v2
    const-string v1, "adc"
    const/16 v2, 0x11
    aput-object v1, v0, v2
    const-string v1, "adc"
    const/16 v2, 0x12
    aput-object v1, v0, v2
    const-string v1, "adc"
    const/16 v2, 0x13
    aput-object v1, v0, v2
    const-string v1, "adc"
    const/16 v2, 0x14
    aput-object v1, v0, v2
    const-string v1, "adc"
    const/16 v2, 0x15
    aput-object v1, v0, v2
    const-string v1, "sbb"
    const/16 v2, 0x18
    aput-object v1, v0, v2
    const-string v1, "sbb"
    const/16 v2, 0x19
    aput-object v1, v0, v2
    const-string v1, "sbb"
    const/16 v2, 0x1a
    aput-object v1, v0, v2
    const-string v1, "sbb"
    const/16 v2, 0x1b
    aput-object v1, v0, v2
    const-string v1, "sbb"
    const/16 v2, 0x1c
    aput-object v1, v0, v2
    const-string v1, "sbb"
    const/16 v2, 0x1d
    aput-object v1, v0, v2
    const-string v1, "and"
    const/16 v2, 0x20
    aput-object v1, v0, v2
    const-string v1, "and"
    const/16 v2, 0x21
    aput-object v1, v0, v2
    const-string v1, "and"
    const/16 v2, 0x22
    aput-object v1, v0, v2
    const-string v1, "and"
    const/16 v2, 0x23
    aput-object v1, v0, v2
    const-string v1, "and"
    const/16 v2, 0x24
    aput-object v1, v0, v2
    const-string v1, "and"
    const/16 v2, 0x25
    aput-object v1, v0, v2
    const-string v1, "sub"
    const/16 v2, 0x28
    aput-object v1, v0, v2
    const-string v1, "sub"
    const/16 v2, 0x29
    aput-object v1, v0, v2
    const-string v1, "sub"
    const/16 v2, 0x2a
    aput-object v1, v0, v2
    const-string v1, "sub"
    const/16 v2, 0x2b
    aput-object v1, v0, v2
    const-string v1, "sub"
    const/16 v2, 0x2c
    aput-object v1, v0, v2
    const-string v1, "sub"
    const/16 v2, 0x2d
    aput-object v1, v0, v2
    const-string v1, "xor"
    const/16 v2, 0x30
    aput-object v1, v0, v2
    const-string v1, "xor"
    const/16 v2, 0x31
    aput-object v1, v0, v2
    const-string v1, "xor"
    const/16 v2, 0x32
    aput-object v1, v0, v2
    const-string v1, "xor"
    const/16 v2, 0x33
    aput-object v1, v0, v2
    const-string v1, "xor"
    const/16 v2, 0x34
    aput-object v1, v0, v2
    const-string v1, "xor"
    const/16 v2, 0x35
    aput-object v1, v0, v2
    const-string v1, "cmp"
    const/16 v2, 0x38
    aput-object v1, v0, v2
    const-string v1, "cmp"
    const/16 v2, 0x39
    aput-object v1, v0, v2
    const-string v1, "cmp"
    const/16 v2, 0x3a
    aput-object v1, v0, v2
    const-string v1, "cmp"
    const/16 v2, 0x3b
    aput-object v1, v0, v2
    const-string v1, "cmp"
    const/16 v2, 0x3c
    aput-object v1, v0, v2
    const-string v1, "cmp"
    const/16 v2, 0x3d
    aput-object v1, v0, v2
    const-string v1, "push r"
    const/16 v2, 0x50
    aput-object v1, v0, v2
    const-string v1, "push r"
    const/16 v2, 0x51
    aput-object v1, v0, v2
    const-string v1, "push r"
    const/16 v2, 0x52
    aput-object v1, v0, v2
    const-string v1, "push r"
    const/16 v2, 0x53
    aput-object v1, v0, v2
    const-string v1, "push r"
    const/16 v2, 0x54
    aput-object v1, v0, v2
    const-string v1, "push r"
    const/16 v2, 0x55
    aput-object v1, v0, v2
    const-string v1, "push r"
    const/16 v2, 0x56
    aput-object v1, v0, v2
    const-string v1, "push r"
    const/16 v2, 0x57
    aput-object v1, v0, v2
    const-string v1, "pop r"
    const/16 v2, 0x58
    aput-object v1, v0, v2
    const-string v1, "pop r"
    const/16 v2, 0x59
    aput-object v1, v0, v2
    const-string v1, "pop r"
    const/16 v2, 0x5a
    aput-object v1, v0, v2
    const-string v1, "pop r"
    const/16 v2, 0x5b
    aput-object v1, v0, v2
    const-string v1, "pop r"
    const/16 v2, 0x5c
    aput-object v1, v0, v2
    const-string v1, "pop r"
    const/16 v2, 0x5d
    aput-object v1, v0, v2
    const-string v1, "pop r"
    const/16 v2, 0x5e
    aput-object v1, v0, v2
    const-string v1, "pop r"
    const/16 v2, 0x5f
    aput-object v1, v0, v2
    const-string v1, "push imm"
    const/16 v2, 0x68
    aput-object v1, v0, v2
    const-string v1, "imul"
    const/16 v2, 0x69
    aput-object v1, v0, v2
    const-string v1, "push imm8"
    const/16 v2, 0x6a
    aput-object v1, v0, v2
    const-string v1, "imul"
    const/16 v2, 0x6b
    aput-object v1, v0, v2
    const-string v1, "jcc rel8"
    const/16 v2, 0x70
    aput-object v1, v0, v2
    const-string v1, "jcc rel8"
    const/16 v2, 0x71
    aput-object v1, v0, v2
    const-string v1, "jcc rel8"
    const/16 v2, 0x72
    aput-object v1, v0, v2
    const-string v1, "jcc rel8"
    const/16 v2, 0x73
    aput-object v1, v0, v2
    const-string v1, "jcc rel8"
    const/16 v2, 0x74
    aput-object v1, v0, v2
    const-string v1, "jcc rel8"
    const/16 v2, 0x75
    aput-object v1, v0, v2
    const-string v1, "jcc rel8"
    const/16 v2, 0x76
    aput-object v1, v0, v2
    const-string v1, "jcc rel8"
    const/16 v2, 0x77
    aput-object v1, v0, v2
    const-string v1, "jcc rel8"
    const/16 v2, 0x78
    aput-object v1, v0, v2
    const-string v1, "jcc rel8"
    const/16 v2, 0x79
    aput-object v1, v0, v2
    const-string v1, "jcc rel8"
    const/16 v2, 0x7a
    aput-object v1, v0, v2
    const-string v1, "jcc rel8"
    const/16 v2, 0x7b
    aput-object v1, v0, v2
    const-string v1, "jcc rel8"
    const/16 v2, 0x7c
    aput-object v1, v0, v2
    const-string v1, "jcc rel8"
    const/16 v2, 0x7d
    aput-object v1, v0, v2
    const-string v1, "jcc rel8"
    const/16 v2, 0x7e
    aput-object v1, v0, v2
    const-string v1, "jcc rel8"
    const/16 v2, 0x7f
    aput-object v1, v0, v2
    const-string v1, "test"
    const/16 v2, 0x84
    aput-object v1, v0, v2
    const-string v1, "test"
    const/16 v2, 0x85
    aput-object v1, v0, v2
    const-string v1, "xchg"
    const/16 v2, 0x86
    aput-object v1, v0, v2
    const-string v1, "xchg"
    const/16 v2, 0x87
    aput-object v1, v0, v2
    const-string v1, "mov"
    const/16 v2, 0x88
    aput-object v1, v0, v2
    const-string v1, "mov"
    const/16 v2, 0x89
    aput-object v1, v0, v2
    const-string v1, "mov"
    const/16 v2, 0x8a
    aput-object v1, v0, v2
    const-string v1, "mov"
    const/16 v2, 0x8b
    aput-object v1, v0, v2
    const-string v1, "lea"
    const/16 v2, 0x8d
    aput-object v1, v0, v2
    const-string v1, "mov seg"
    const/16 v2, 0x8e
    aput-object v1, v0, v2
    const-string v1, "pop r/m"
    const/16 v2, 0x8f
    aput-object v1, v0, v2
    const-string v1, "nop"
    const/16 v2, 0x90
    aput-object v1, v0, v2
    const-string v1, "cwde/cdqe"
    const/16 v2, 0x98
    aput-object v1, v0, v2
    const-string v1, "cdq/cqo"
    const/16 v2, 0x99
    aput-object v1, v0, v2
    const-string v1, "pushf"
    const/16 v2, 0x9c
    aput-object v1, v0, v2
    const-string v1, "popf"
    const/16 v2, 0x9d
    aput-object v1, v0, v2
    const-string v1, "test al,imm8"
    const/16 v2, 0xa8
    aput-object v1, v0, v2
    const-string v1, "test eax,imm"
    const/16 v2, 0xa9
    aput-object v1, v0, v2
    const-string v1, "mov r8,imm8"
    const/16 v2, 0xb0
    aput-object v1, v0, v2
    const-string v1, "mov r8,imm8"
    const/16 v2, 0xb1
    aput-object v1, v0, v2
    const-string v1, "mov r8,imm8"
    const/16 v2, 0xb2
    aput-object v1, v0, v2
    const-string v1, "mov r8,imm8"
    const/16 v2, 0xb3
    aput-object v1, v0, v2
    const-string v1, "mov r8,imm8"
    const/16 v2, 0xb4
    aput-object v1, v0, v2
    const-string v1, "mov r8,imm8"
    const/16 v2, 0xb5
    aput-object v1, v0, v2
    const-string v1, "mov r8,imm8"
    const/16 v2, 0xb6
    aput-object v1, v0, v2
    const-string v1, "mov r8,imm8"
    const/16 v2, 0xb7
    aput-object v1, v0, v2
    const-string v1, "mov r,imm"
    const/16 v2, 0xb8
    aput-object v1, v0, v2
    const-string v1, "mov r,imm"
    const/16 v2, 0xb9
    aput-object v1, v0, v2
    const-string v1, "mov r,imm"
    const/16 v2, 0xba
    aput-object v1, v0, v2
    const-string v1, "mov r,imm"
    const/16 v2, 0xbb
    aput-object v1, v0, v2
    const-string v1, "mov r,imm"
    const/16 v2, 0xbc
    aput-object v1, v0, v2
    const-string v1, "mov r,imm"
    const/16 v2, 0xbd
    aput-object v1, v0, v2
    const-string v1, "mov r,imm"
    const/16 v2, 0xbe
    aput-object v1, v0, v2
    const-string v1, "mov r,imm"
    const/16 v2, 0xbf
    aput-object v1, v0, v2
    const-string v1, "ret imm16"
    const/16 v2, 0xc2
    aput-object v1, v0, v2
    const-string v1, "ret"
    const/16 v2, 0xc3
    aput-object v1, v0, v2
    const-string v1, "mov r/m8,imm8"
    const/16 v2, 0xc6
    aput-object v1, v0, v2
    const-string v1, "mov r/m,imm"
    const/16 v2, 0xc7
    aput-object v1, v0, v2
    const-string v1, "leave"
    const/16 v2, 0xc9
    aput-object v1, v0, v2
    const-string v1, "int3"
    const/16 v2, 0xcc
    aput-object v1, v0, v2
    const-string v1, "int imm8"
    const/16 v2, 0xcd
    aput-object v1, v0, v2
    const-string v1, "loop/jecxz rel8"
    const/16 v2, 0xe0
    aput-object v1, v0, v2
    const-string v1, "loop/jecxz rel8"
    const/16 v2, 0xe1
    aput-object v1, v0, v2
    const-string v1, "loop/jecxz rel8"
    const/16 v2, 0xe2
    aput-object v1, v0, v2
    const-string v1, "loop/jecxz rel8"
    const/16 v2, 0xe3
    aput-object v1, v0, v2
    const-string v1, "call rel32"
    const/16 v2, 0xe8
    aput-object v1, v0, v2
    const-string v1, "jmp rel32"
    const/16 v2, 0xe9
    aput-object v1, v0, v2
    const-string v1, "jmp rel8"
    const/16 v2, 0xeb
    aput-object v1, v0, v2
    const-string v1, "hlt"
    const/16 v2, 0xf4
    aput-object v1, v0, v2
    const-string v1, "inc/dec r/m8"
    const/16 v2, 0xfe
    aput-object v1, v0, v2
    const-string v1, "grupo5 (call/jmp/push ind.)"
    const/16 v2, 0xff
    aput-object v1, v0, v2
    sput-object v0, Lcom/exepretranslator/app/TranslateService;->MNEMONIC:[Ljava/lang/String;

    const/16 v0, 0x100
    new-array v0, v0, [Ljava/lang/String;
    const-string v1, "add"
    const/16 v2, 0x0
    aput-object v1, v0, v2
    const-string v1, "add"
    const/16 v2, 0x1
    aput-object v1, v0, v2
    const-string v1, "add"
    const/16 v2, 0x2
    aput-object v1, v0, v2
    const-string v1, "add"
    const/16 v2, 0x3
    aput-object v1, v0, v2
    const-string v1, "add"
    const/16 v2, 0x4
    aput-object v1, v0, v2
    const-string v1, "add"
    const/16 v2, 0x5
    aput-object v1, v0, v2
    const-string v1, "orr"
    const/16 v2, 0x8
    aput-object v1, v0, v2
    const-string v1, "orr"
    const/16 v2, 0x9
    aput-object v1, v0, v2
    const-string v1, "orr"
    const/16 v2, 0xa
    aput-object v1, v0, v2
    const-string v1, "orr"
    const/16 v2, 0xb
    aput-object v1, v0, v2
    const-string v1, "orr"
    const/16 v2, 0xc
    aput-object v1, v0, v2
    const-string v1, "orr"
    const/16 v2, 0xd
    aput-object v1, v0, v2
    const-string v1, "adcs"
    const/16 v2, 0x10
    aput-object v1, v0, v2
    const-string v1, "adcs"
    const/16 v2, 0x11
    aput-object v1, v0, v2
    const-string v1, "adcs"
    const/16 v2, 0x12
    aput-object v1, v0, v2
    const-string v1, "adcs"
    const/16 v2, 0x13
    aput-object v1, v0, v2
    const-string v1, "adcs"
    const/16 v2, 0x14
    aput-object v1, v0, v2
    const-string v1, "adcs"
    const/16 v2, 0x15
    aput-object v1, v0, v2
    const-string v1, "sbcs"
    const/16 v2, 0x18
    aput-object v1, v0, v2
    const-string v1, "sbcs"
    const/16 v2, 0x19
    aput-object v1, v0, v2
    const-string v1, "sbcs"
    const/16 v2, 0x1a
    aput-object v1, v0, v2
    const-string v1, "sbcs"
    const/16 v2, 0x1b
    aput-object v1, v0, v2
    const-string v1, "sbcs"
    const/16 v2, 0x1c
    aput-object v1, v0, v2
    const-string v1, "sbcs"
    const/16 v2, 0x1d
    aput-object v1, v0, v2
    const-string v1, "and"
    const/16 v2, 0x20
    aput-object v1, v0, v2
    const-string v1, "and"
    const/16 v2, 0x21
    aput-object v1, v0, v2
    const-string v1, "and"
    const/16 v2, 0x22
    aput-object v1, v0, v2
    const-string v1, "and"
    const/16 v2, 0x23
    aput-object v1, v0, v2
    const-string v1, "and"
    const/16 v2, 0x24
    aput-object v1, v0, v2
    const-string v1, "and"
    const/16 v2, 0x25
    aput-object v1, v0, v2
    const-string v1, "sub"
    const/16 v2, 0x28
    aput-object v1, v0, v2
    const-string v1, "sub"
    const/16 v2, 0x29
    aput-object v1, v0, v2
    const-string v1, "sub"
    const/16 v2, 0x2a
    aput-object v1, v0, v2
    const-string v1, "sub"
    const/16 v2, 0x2b
    aput-object v1, v0, v2
    const-string v1, "sub"
    const/16 v2, 0x2c
    aput-object v1, v0, v2
    const-string v1, "sub"
    const/16 v2, 0x2d
    aput-object v1, v0, v2
    const-string v1, "eor"
    const/16 v2, 0x30
    aput-object v1, v0, v2
    const-string v1, "eor"
    const/16 v2, 0x31
    aput-object v1, v0, v2
    const-string v1, "eor"
    const/16 v2, 0x32
    aput-object v1, v0, v2
    const-string v1, "eor"
    const/16 v2, 0x33
    aput-object v1, v0, v2
    const-string v1, "eor"
    const/16 v2, 0x34
    aput-object v1, v0, v2
    const-string v1, "eor"
    const/16 v2, 0x35
    aput-object v1, v0, v2
    const-string v1, "cmp"
    const/16 v2, 0x38
    aput-object v1, v0, v2
    const-string v1, "cmp"
    const/16 v2, 0x39
    aput-object v1, v0, v2
    const-string v1, "cmp"
    const/16 v2, 0x3a
    aput-object v1, v0, v2
    const-string v1, "cmp"
    const/16 v2, 0x3b
    aput-object v1, v0, v2
    const-string v1, "cmp"
    const/16 v2, 0x3c
    aput-object v1, v0, v2
    const-string v1, "cmp"
    const/16 v2, 0x3d
    aput-object v1, v0, v2
    const-string v1, "str (heuristico)"
    const/16 v2, 0x50
    aput-object v1, v0, v2
    const-string v1, "str (heuristico)"
    const/16 v2, 0x51
    aput-object v1, v0, v2
    const-string v1, "str (heuristico)"
    const/16 v2, 0x52
    aput-object v1, v0, v2
    const-string v1, "str (heuristico)"
    const/16 v2, 0x53
    aput-object v1, v0, v2
    const-string v1, "str (heuristico)"
    const/16 v2, 0x54
    aput-object v1, v0, v2
    const-string v1, "str (heuristico)"
    const/16 v2, 0x55
    aput-object v1, v0, v2
    const-string v1, "str (heuristico)"
    const/16 v2, 0x56
    aput-object v1, v0, v2
    const-string v1, "str (heuristico)"
    const/16 v2, 0x57
    aput-object v1, v0, v2
    const-string v1, "ldr (heuristico)"
    const/16 v2, 0x58
    aput-object v1, v0, v2
    const-string v1, "ldr (heuristico)"
    const/16 v2, 0x59
    aput-object v1, v0, v2
    const-string v1, "ldr (heuristico)"
    const/16 v2, 0x5a
    aput-object v1, v0, v2
    const-string v1, "ldr (heuristico)"
    const/16 v2, 0x5b
    aput-object v1, v0, v2
    const-string v1, "ldr (heuristico)"
    const/16 v2, 0x5c
    aput-object v1, v0, v2
    const-string v1, "ldr (heuristico)"
    const/16 v2, 0x5d
    aput-object v1, v0, v2
    const-string v1, "ldr (heuristico)"
    const/16 v2, 0x5e
    aput-object v1, v0, v2
    const-string v1, "ldr (heuristico)"
    const/16 v2, 0x5f
    aput-object v1, v0, v2
    const-string v1, "str (heuristico)"
    const/16 v2, 0x68
    aput-object v1, v0, v2
    const-string v1, "mul (heuristico)"
    const/16 v2, 0x69
    aput-object v1, v0, v2
    const-string v1, "str (heuristico)"
    const/16 v2, 0x6a
    aput-object v1, v0, v2
    const-string v1, "mul (heuristico)"
    const/16 v2, 0x6b
    aput-object v1, v0, v2
    const-string v1, "b.cc (heuristico)"
    const/16 v2, 0x70
    aput-object v1, v0, v2
    const-string v1, "b.cc (heuristico)"
    const/16 v2, 0x71
    aput-object v1, v0, v2
    const-string v1, "b.cc (heuristico)"
    const/16 v2, 0x72
    aput-object v1, v0, v2
    const-string v1, "b.cc (heuristico)"
    const/16 v2, 0x73
    aput-object v1, v0, v2
    const-string v1, "b.cc (heuristico)"
    const/16 v2, 0x74
    aput-object v1, v0, v2
    const-string v1, "b.cc (heuristico)"
    const/16 v2, 0x75
    aput-object v1, v0, v2
    const-string v1, "b.cc (heuristico)"
    const/16 v2, 0x76
    aput-object v1, v0, v2
    const-string v1, "b.cc (heuristico)"
    const/16 v2, 0x77
    aput-object v1, v0, v2
    const-string v1, "b.cc (heuristico)"
    const/16 v2, 0x78
    aput-object v1, v0, v2
    const-string v1, "b.cc (heuristico)"
    const/16 v2, 0x79
    aput-object v1, v0, v2
    const-string v1, "b.cc (heuristico)"
    const/16 v2, 0x7a
    aput-object v1, v0, v2
    const-string v1, "b.cc (heuristico)"
    const/16 v2, 0x7b
    aput-object v1, v0, v2
    const-string v1, "b.cc (heuristico)"
    const/16 v2, 0x7c
    aput-object v1, v0, v2
    const-string v1, "b.cc (heuristico)"
    const/16 v2, 0x7d
    aput-object v1, v0, v2
    const-string v1, "b.cc (heuristico)"
    const/16 v2, 0x7e
    aput-object v1, v0, v2
    const-string v1, "b.cc (heuristico)"
    const/16 v2, 0x7f
    aput-object v1, v0, v2
    const-string v1, "tst"
    const/16 v2, 0x84
    aput-object v1, v0, v2
    const-string v1, "tst"
    const/16 v2, 0x85
    aput-object v1, v0, v2
    const-string v1, "mov/ldr/str (heuristico)"
    const/16 v2, 0x88
    aput-object v1, v0, v2
    const-string v1, "mov/ldr/str (heuristico)"
    const/16 v2, 0x89
    aput-object v1, v0, v2
    const-string v1, "mov/ldr/str (heuristico)"
    const/16 v2, 0x8a
    aput-object v1, v0, v2
    const-string v1, "mov/ldr/str (heuristico)"
    const/16 v2, 0x8b
    aput-object v1, v0, v2
    const-string v1, "add (heuristico)"
    const/16 v2, 0x8d
    aput-object v1, v0, v2
    const-string v1, "ldr (heuristico)"
    const/16 v2, 0x8f
    aput-object v1, v0, v2
    const-string v1, "nop"
    const/16 v2, 0x90
    aput-object v1, v0, v2
    const-string v1, "tst"
    const/16 v2, 0xa8
    aput-object v1, v0, v2
    const-string v1, "tst"
    const/16 v2, 0xa9
    aput-object v1, v0, v2
    const-string v1, "mov (heuristico)"
    const/16 v2, 0xb0
    aput-object v1, v0, v2
    const-string v1, "mov (heuristico)"
    const/16 v2, 0xb1
    aput-object v1, v0, v2
    const-string v1, "mov (heuristico)"
    const/16 v2, 0xb2
    aput-object v1, v0, v2
    const-string v1, "mov (heuristico)"
    const/16 v2, 0xb3
    aput-object v1, v0, v2
    const-string v1, "mov (heuristico)"
    const/16 v2, 0xb4
    aput-object v1, v0, v2
    const-string v1, "mov (heuristico)"
    const/16 v2, 0xb5
    aput-object v1, v0, v2
    const-string v1, "mov (heuristico)"
    const/16 v2, 0xb6
    aput-object v1, v0, v2
    const-string v1, "mov (heuristico)"
    const/16 v2, 0xb7
    aput-object v1, v0, v2
    const-string v1, "mov (heuristico)"
    const/16 v2, 0xb8
    aput-object v1, v0, v2
    const-string v1, "mov (heuristico)"
    const/16 v2, 0xb9
    aput-object v1, v0, v2
    const-string v1, "mov (heuristico)"
    const/16 v2, 0xba
    aput-object v1, v0, v2
    const-string v1, "mov (heuristico)"
    const/16 v2, 0xbb
    aput-object v1, v0, v2
    const-string v1, "mov (heuristico)"
    const/16 v2, 0xbc
    aput-object v1, v0, v2
    const-string v1, "mov (heuristico)"
    const/16 v2, 0xbd
    aput-object v1, v0, v2
    const-string v1, "mov (heuristico)"
    const/16 v2, 0xbe
    aput-object v1, v0, v2
    const-string v1, "mov (heuristico)"
    const/16 v2, 0xbf
    aput-object v1, v0, v2
    const-string v1, "ret"
    const/16 v2, 0xc2
    aput-object v1, v0, v2
    const-string v1, "ret"
    const/16 v2, 0xc3
    aput-object v1, v0, v2
    const-string v1, "strb (heuristico)"
    const/16 v2, 0xc6
    aput-object v1, v0, v2
    const-string v1, "str (heuristico)"
    const/16 v2, 0xc7
    aput-object v1, v0, v2
    const-string v1, "mov sp,x29 (heuristico)"
    const/16 v2, 0xc9
    aput-object v1, v0, v2
    const-string v1, "brk"
    const/16 v2, 0xcc
    aput-object v1, v0, v2
    const-string v1, "cbz/b (heuristico)"
    const/16 v2, 0xe0
    aput-object v1, v0, v2
    const-string v1, "cbz/b (heuristico)"
    const/16 v2, 0xe1
    aput-object v1, v0, v2
    const-string v1, "cbz/b (heuristico)"
    const/16 v2, 0xe2
    aput-object v1, v0, v2
    const-string v1, "cbz/b (heuristico)"
    const/16 v2, 0xe3
    aput-object v1, v0, v2
    const-string v1, "bl"
    const/16 v2, 0xe8
    aput-object v1, v0, v2
    const-string v1, "b"
    const/16 v2, 0xe9
    aput-object v1, v0, v2
    const-string v1, "b"
    const/16 v2, 0xeb
    aput-object v1, v0, v2
    sput-object v0, Lcom/exepretranslator/app/TranslateService;->ARM_HINT:[Ljava/lang/String;

    return-void

    :one_info_data
        .array-data 1
            0x01t 0x01t 0x01t 0x01t 0x02t 0x04t 0x00t 0x00t 0x01t 0x01t 0x01t 0x01t 0x02t 0x04t 0x00t 0x10t
            0x01t 0x01t 0x01t 0x01t 0x02t 0x04t 0x00t 0x00t 0x01t 0x01t 0x01t 0x01t 0x02t 0x04t 0x00t 0x00t
            0x01t 0x01t 0x01t 0x01t 0x02t 0x04t 0x08t 0x00t 0x01t 0x01t 0x01t 0x01t 0x02t 0x04t 0x08t 0x00t
            0x01t 0x01t 0x01t 0x01t 0x02t 0x04t 0x08t 0x00t 0x01t 0x01t 0x01t 0x01t 0x02t 0x04t 0x08t 0x00t
            0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t
            0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t
            0x00t 0x00t 0x01t 0x01t 0x08t 0x08t 0x08t 0x08t 0x04t 0x05t 0x02t 0x03t 0x00t 0x00t 0x00t 0x00t
            0x02t 0x02t 0x02t 0x02t 0x02t 0x02t 0x02t 0x02t 0x02t 0x02t 0x02t 0x02t 0x02t 0x02t 0x02t 0x02t
            0x03t 0x05t 0x00t 0x03t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x00t 0x01t 0x00t 0x01t
            0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t
            0x04t 0x04t 0x04t 0x04t 0x00t 0x00t 0x00t 0x00t 0x02t 0x04t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t
            0x02t 0x02t 0x02t 0x02t 0x02t 0x02t 0x02t 0x02t 0x04t 0x04t 0x04t 0x04t 0x04t 0x04t 0x04t 0x04t
            0x03t 0x03t 0x06t 0x00t 0x01t 0x01t 0x03t 0x05t 0x00t 0x00t 0x00t 0x00t 0x00t 0x02t 0x00t 0x00t
            0x01t 0x01t 0x01t 0x01t 0x00t 0x00t 0x00t 0x00t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t
            0x02t 0x02t 0x02t 0x02t 0x00t 0x00t 0x00t 0x00t 0x04t 0x04t 0x00t 0x02t 0x00t 0x00t 0x00t 0x00t
            0x08t 0x00t 0x08t 0x08t 0x00t 0x00t 0x01t 0x01t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x01t 0x01t
        .end array-data

    :two_info_data
        .array-data 1
            0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t
            0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x01t
            0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t
            0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t
            0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t
            0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t
            0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t
            0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t
            0x04t 0x04t 0x04t 0x04t 0x04t 0x04t 0x04t 0x04t 0x04t 0x04t 0x04t 0x04t 0x04t 0x04t 0x04t 0x04t
            0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t 0x01t
            0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x01t
            0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x01t 0x01t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x01t 0x01t
            0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t
            0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t
            0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t
            0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t 0x00t
        .end array-data
.end method
.method private prefs()Landroid/content/SharedPreferences;
    .locals 2

    const-string v0, "ptexe_prefs"

    const/4 v1, 0x0

    invoke-virtual {p0, v0, v1}, Landroid/app/Service;->getSharedPreferences(Ljava/lang/String;I)Landroid/content/SharedPreferences;

    move-result-object v0

    return-object v0
.end method

.method private setStatus(Ljava/lang/String;)V
    .locals 2

    invoke-direct {p0}, Lcom/exepretranslator/app/TranslateService;->prefs()Landroid/content/SharedPreferences;

    move-result-object v0

    invoke-interface {v0}, Landroid/content/SharedPreferences;->edit()Landroid/content/SharedPreferences$Editor;

    move-result-object v0

    const-string v1, "status"

    invoke-interface {v0, v1, p1}, Landroid/content/SharedPreferences$Editor;->putString(Ljava/lang/String;Ljava/lang/String;)Landroid/content/SharedPreferences$Editor;

    move-result-object v0

    invoke-interface {v0}, Landroid/content/SharedPreferences$Editor;->apply()V

    return-void
.end method

.method private fail(Ljava/lang/String;)V
    .locals 2

    new-instance v0, Ljava/lang/StringBuilder;

    invoke-direct {v0}, Ljava/lang/StringBuilder;-><init>()V

    const-string v1, "erro: "

    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-virtual {v0, p1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;

    move-result-object v0

    invoke-direct {p0, v0}, Lcom/exepretranslator/app/TranslateService;->setStatus(Ljava/lang/String;)V

    return-void
.end method

.method private ensureChannel()V
    .locals 4

    new-instance v0, Landroid/app/NotificationChannel;

    const-string v1, "ptexe_channel"

    const-string v2, "Pre-traducao de EXE"

    const/4 v3, 0x2

    invoke-direct {v0, v1, v2, v3}, Landroid/app/NotificationChannel;-><init>(Ljava/lang/String;Ljava/lang/CharSequence;I)V

    const-string v1, "notification"

    invoke-virtual {p0, v1}, Landroid/app/Service;->getSystemService(Ljava/lang/String;)Ljava/lang/Object;

    move-result-object v1

    check-cast v1, Landroid/app/NotificationManager;

    invoke-virtual {v1, v0}, Landroid/app/NotificationManager;->createNotificationChannel(Landroid/app/NotificationChannel;)V

    return-void
.end method

.method private buildNotification(Ljava/lang/String;)Landroid/app/Notification;
    .locals 4

    invoke-virtual {p0}, Landroid/app/Service;->getResources()Landroid/content/res/Resources;

    move-result-object v0

    const-string v1, "sym_def_app_icon"

    const-string v2, "drawable"

    const-string v3, "android"

    invoke-virtual {v0, v1, v2, v3}, Landroid/content/res/Resources;->getIdentifier(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)I

    move-result v0

    new-instance v1, Landroid/app/Notification$Builder;

    const-string v2, "ptexe_channel"

    invoke-direct {v1, p0, v2}, Landroid/app/Notification$Builder;-><init>(Landroid/content/Context;Ljava/lang/String;)V

    const-string v2, "Pre-Tradutor EXE"

    invoke-virtual {v1, v2}, Landroid/app/Notification$Builder;->setContentTitle(Ljava/lang/CharSequence;)Landroid/app/Notification$Builder;

    invoke-virtual {v1, p1}, Landroid/app/Notification$Builder;->setContentText(Ljava/lang/CharSequence;)Landroid/app/Notification$Builder;

    invoke-virtual {v1, v0}, Landroid/app/Notification$Builder;->setSmallIcon(I)Landroid/app/Notification$Builder;

    const/4 v2, 0x1

    invoke-virtual {v1, v2}, Landroid/app/Notification$Builder;->setOngoing(Z)Landroid/app/Notification$Builder;

    invoke-virtual {v1}, Landroid/app/Notification$Builder;->build()Landroid/app/Notification;

    move-result-object v0

    return-object v0
.end method

.method private updateNotification(Ljava/lang/String;)V
    .locals 2

    invoke-direct {p0, p1}, Lcom/exepretranslator/app/TranslateService;->buildNotification(Ljava/lang/String;)Landroid/app/Notification;

    move-result-object v0

    const/16 v1, 0x3e8

    invoke-virtual {p0, v1, v0}, Landroid/app/Service;->startForeground(ILandroid/app/Notification;)V

    return-void
.end method

.method public onCreate()V
    .locals 0

    invoke-super {p0}, Landroid/app/Service;->onCreate()V

    invoke-direct {p0}, Lcom/exepretranslator/app/TranslateService;->ensureChannel()V

    return-void
.end method

.method public onBind(Landroid/content/Intent;)Landroid/os/IBinder;
    .locals 1

    const/4 v0, 0x0

    return-object v0
.end method

.method public onStartCommand(Landroid/content/Intent;II)I
    .locals 4

    const-string v0, "uri"

    const/4 v1, 0x0

    if-eqz p1, :cond_0

    invoke-virtual {p1, v0}, Landroid/content/Intent;->getStringExtra(Ljava/lang/String;)Ljava/lang/String;

    move-result-object v1

    :cond_0
    if-nez v1, :cond_1

    invoke-direct {p0}, Lcom/exepretranslator/app/TranslateService;->prefs()Landroid/content/SharedPreferences;

    move-result-object v2

    const-string v3, "uri"

    invoke-interface {v2, v3, v1}, Landroid/content/SharedPreferences;->getString(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;

    move-result-object v1

    :cond_1
    if-nez v1, :cond_2

    invoke-virtual {p0}, Landroid/app/Service;->stopSelf()V

    const/4 v0, 0x2

    return v0

    :cond_2
    iput-object v1, p0, Lcom/exepretranslator/app/TranslateService;->currentUri:Ljava/lang/String;

    const-string v0, "Iniciando..."

    invoke-direct {p0, v0}, Lcom/exepretranslator/app/TranslateService;->updateNotification(Ljava/lang/String;)V

    new-instance v0, Ljava/lang/Thread;

    invoke-direct {v0, p0}, Ljava/lang/Thread;-><init>(Ljava/lang/Runnable;)V

    invoke-virtual {v0}, Ljava/lang/Thread;->start()V

    const/4 v0, 0x1

    return v0
.end method

.method private openForFile(Ljava/lang/String;)Z
    .locals 3

    :try_start_0
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

    iput-object v0, p0, Lcom/exepretranslator/app/TranslateService;->channel:Ljava/nio/channels/FileChannel;
    :try_end_0
    .catch Ljava/lang/Exception; {:try_start_0 .. :try_end_0} :catch_0

    const/4 v0, 0x1

    return v0

    :catch_0
    move-exception v0

    const-string v0, "nao foi possivel abrir o arquivo selecionado"

    iput-object v0, p0, Lcom/exepretranslator/app/TranslateService;->lastError:Ljava/lang/String;

    const/4 v0, 0x0

    return v0
.end method

.method private parseHeader()Z
    .locals 10

    const/16 v0, 0x1000

    new-array v1, v0, [B

    iget-object v2, p0, Lcom/exepretranslator/app/TranslateService;->channel:Ljava/nio/channels/FileChannel;

    const/4 v3, 0x0

    const/4 v5, 0x0

    invoke-static {v2, v3, v1, v5, v0}, Lcom/exepretranslator/app/TranslateService;->readFullyAt(Ljava/nio/channels/FileChannel;I[BII)Z

    move-result v2

    if-nez v2, :cond_ok0

    const-string v0, "nao foi possivel ler o cabecalho do arquivo"

    iput-object v0, p0, Lcom/exepretranslator/app/TranslateService;->lastError:Ljava/lang/String;

    const/4 v0, 0x0

    return v0

    :cond_ok0
    const/4 v2, 0x0

    aget-byte v2, v1, v2

    and-int/lit16 v2, v2, 0xff

    const/16 v3, 0x4d

    if-eq v2, v3, :mz_ok

    :mz_bad
    const-string v0, "arquivo nao parece ser um executavel PE (.exe) valido"

    iput-object v0, p0, Lcom/exepretranslator/app/TranslateService;->lastError:Ljava/lang/String;

    const/4 v0, 0x0

    return v0

    :mz_ok
    const/4 v2, 0x1

    aget-byte v2, v1, v2

    and-int/lit16 v2, v2, 0xff

    const/16 v3, 0x5a

    if-ne v2, v3, :mz_bad

    const/16 v2, 0x3c

    invoke-static {v1, v2}, Lcom/exepretranslator/app/TranslateService;->readU32([BI)I

    move-result v2

    const/16 v3, 0x18

    add-int v4, v2, v3

    if-ge v4, v0, :mz_bad2

    if-ltz v2, :mz_bad2

    goto :lfanew_ok

    :mz_bad2
    const-string v0, "cabecalho PE fora do intervalo lido (nao suportado nesta versao)"

    iput-object v0, p0, Lcom/exepretranslator/app/TranslateService;->lastError:Ljava/lang/String;

    const/4 v0, 0x0

    return v0

    :lfanew_ok
    aget-byte v3, v1, v2

    and-int/lit16 v3, v3, 0xff

    const/16 v4, 0x50

    if-ne v3, v4, :mz_bad2

    add-int/lit8 v4, v2, 0x1

    aget-byte v4, v1, v4

    and-int/lit16 v4, v4, 0xff

    const/16 v5, 0x45

    if-ne v4, v5, :mz_bad2

    add-int/lit8 v4, v2, 0x6

    invoke-static {v1, v4}, Lcom/exepretranslator/app/TranslateService;->readU16([BI)I

    move-result v4

    add-int/lit8 v5, v2, 0x14

    invoke-static {v1, v5}, Lcom/exepretranslator/app/TranslateService;->readU16([BI)I

    move-result v5

    add-int/lit8 v6, v2, 0x18

    invoke-static {v1, v6}, Lcom/exepretranslator/app/TranslateService;->readU16([BI)I

    move-result v6

    const/4 v7, 0x0

    const/16 v8, 0x20b

    if-ne v6, v8, :not64

    const/4 v7, 0x1

    :not64
    iput v7, p0, Lcom/exepretranslator/app/TranslateService;->pe64:I

    add-int/lit8 v6, v2, 0x18

    add-int/2addr v6, v5

    const/4 v7, 0x0

    const/4 v8, 0x0

    const/4 v9, 0x0

    :sect_loop
    if-ge v9, v4, :sect_done

    mul-int/lit8 v2, v9, 0x28

    add-int v2, v6, v2

    add-int/lit8 v3, v2, 0x28

    if-gt v3, v0, :sect_done

    add-int/lit8 v3, v2, 0x24

    invoke-static {v1, v3}, Lcom/exepretranslator/app/TranslateService;->readU32([BI)I

    move-result v3

    and-int/lit8 v5, v3, 0x20

    if-nez v5, :is_code

    const/high16 v5, 0x20000000

    and-int/2addr v5, v3

    if-eqz v5, :sect_next

    :is_code
    add-int/lit8 v3, v2, 0x10

    invoke-static {v1, v3}, Lcom/exepretranslator/app/TranslateService;->readU32([BI)I

    move-result v3

    if-le v3, v7, :sect_next

    move v7, v3

    add-int/lit8 v3, v2, 0x14

    invoke-static {v1, v3}, Lcom/exepretranslator/app/TranslateService;->readU32([BI)I

    move-result v8

    :sect_next
    add-int/lit8 v9, v9, 0x1

    goto :sect_loop

    :sect_done
    if-nez v7, :have_section

    const-string v0, "secao de codigo executavel nao encontrada no arquivo"

    iput-object v0, p0, Lcom/exepretranslator/app/TranslateService;->lastError:Ljava/lang/String;

    const/4 v0, 0x0

    return v0

    :have_section
    iput v8, p0, Lcom/exepretranslator/app/TranslateService;->codeOff:I

    iput v7, p0, Lcom/exepretranslator/app/TranslateService;->codeSize:I

    const/4 v0, 0x1

    return v0
.end method

.method private saveSectionInfo()V
    .locals 3

    invoke-direct {p0}, Lcom/exepretranslator/app/TranslateService;->prefs()Landroid/content/SharedPreferences;

    move-result-object v0

    invoke-interface {v0}, Landroid/content/SharedPreferences;->edit()Landroid/content/SharedPreferences$Editor;

    move-result-object v0

    const-string v1, "code_off"

    iget v2, p0, Lcom/exepretranslator/app/TranslateService;->codeOff:I

    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences$Editor;->putInt(Ljava/lang/String;I)Landroid/content/SharedPreferences$Editor;

    move-result-object v0

    const-string v1, "code_size"

    iget v2, p0, Lcom/exepretranslator/app/TranslateService;->codeSize:I

    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences$Editor;->putInt(Ljava/lang/String;I)Landroid/content/SharedPreferences$Editor;

    move-result-object v0

    const-string v1, "uri"

    iget-object v2, p0, Lcom/exepretranslator/app/TranslateService;->currentUri:Ljava/lang/String;

    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences$Editor;->putString(Ljava/lang/String;Ljava/lang/String;)Landroid/content/SharedPreferences$Editor;

    move-result-object v0

    invoke-interface {v0}, Landroid/content/SharedPreferences$Editor;->apply()V

    return-void
.end method

.method private loadResumeOffset()I
    .locals 6

    invoke-direct {p0}, Lcom/exepretranslator/app/TranslateService;->prefs()Landroid/content/SharedPreferences;

    move-result-object v0

    const-string v1, "uri"

    const/4 v2, 0x0

    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences;->getString(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;

    move-result-object v1

    iget-object v2, p0, Lcom/exepretranslator/app/TranslateService;->currentUri:Ljava/lang/String;

    if-eqz v1, :mismatch

    invoke-virtual {v1, v2}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z

    move-result v3

    if-eqz v3, :mismatch

    const-string v1, "code_off"

    const/4 v3, 0x0

    invoke-interface {v0, v1, v3}, Landroid/content/SharedPreferences;->getInt(Ljava/lang/String;I)I

    move-result v1

    iget v3, p0, Lcom/exepretranslator/app/TranslateService;->codeOff:I

    if-ne v1, v3, :mismatch

    const-string v1, "code_size"

    const/4 v3, 0x0

    invoke-interface {v0, v1, v3}, Landroid/content/SharedPreferences;->getInt(Ljava/lang/String;I)I

    move-result v1

    iget v3, p0, Lcom/exepretranslator/app/TranslateService;->codeSize:I

    if-ne v1, v3, :mismatch

    const-string v1, "proc_off"

    const-wide/16 v3, 0x0

    invoke-interface {v0, v1, v3, v4}, Landroid/content/SharedPreferences;->getLong(Ljava/lang/String;J)J

    move-result-wide v3

    long-to-int v1, v3

    if-ltz v1, :mismatch

    iget v5, p0, Lcom/exepretranslator/app/TranslateService;->codeSize:I

    if-lt v1, v5, :return_val

    :mismatch
    const/4 v1, 0x0

    :return_val
    return v1
.end method

.method private openOutput(Z)Z
    .locals 4

    :try_start_0
    const-string v0, "pretranslated.txt"

    const/4 v1, 0x0

    if-eqz p1, :do_append

    goto :have_mode

    :do_append
    sget v1, Landroid/content/Context;->MODE_APPEND:I

    :have_mode
    invoke-virtual {p0, v0, v1}, Landroid/app/Service;->openFileOutput(Ljava/lang/String;I)Ljava/io/FileOutputStream;

    move-result-object v0

    new-instance v1, Ljava/io/PrintStream;

    const/4 v2, 0x1

    const-string v3, "UTF-8"

    invoke-direct {v1, v0, v2, v3}, Ljava/io/PrintStream;-><init>(Ljava/io/OutputStream;ZLjava/lang/String;)V

    iput-object v1, p0, Lcom/exepretranslator/app/TranslateService;->out:Ljava/io/PrintStream;
    :try_end_0
    .catch Ljava/lang/Exception; {:try_start_0 .. :try_end_0} :catch_0

    const/4 v0, 0x1

    return v0

    :catch_0
    move-exception v0

    const-string v0, "nao foi possivel abrir o arquivo de progresso"

    iput-object v0, p0, Lcom/exepretranslator/app/TranslateService;->lastError:Ljava/lang/String;

    const/4 v0, 0x0

    return v0
.end method

.method private static readFullyAt(Ljava/nio/channels/FileChannel;I[BII)Z
    .locals 8

    move-object v2, p0

    int-to-long v3, p1

    move-object v5, p2

    move v6, p3

    move v7, p4

    invoke-static/range {v2 .. v7}, Lcom/exepretranslator/app/TranslateService;->readFully(Ljava/nio/channels/FileChannel;J[BII)Z

    move-result v0

    return v0
.end method

.method private saveProgress(I)V
    .locals 4

    invoke-direct {p0}, Lcom/exepretranslator/app/TranslateService;->prefs()Landroid/content/SharedPreferences;

    move-result-object v0

    invoke-interface {v0}, Landroid/content/SharedPreferences;->edit()Landroid/content/SharedPreferences$Editor;

    move-result-object v0

    const-string v1, "proc_off"

    int-to-long v2, p1

    invoke-interface {v0, v1, v2, v3}, Landroid/content/SharedPreferences$Editor;->putLong(Ljava/lang/String;J)Landroid/content/SharedPreferences$Editor;

    move-result-object v0

    invoke-interface {v0}, Landroid/content/SharedPreferences$Editor;->apply()V

    iget v1, p0, Lcom/exepretranslator/app/TranslateService;->codeSize:I

    if-lez v1, :skip_notify

    mul-int/lit8 v2, p1, 0x64

    div-int/2addr v2, v1

    new-instance v1, Ljava/lang/StringBuilder;

    invoke-direct {v1}, Ljava/lang/StringBuilder;-><init>()V

    const-string v3, "Pre-traduzindo... "

    invoke-virtual {v1, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-virtual {v1, v2}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;

    const-string v2, "%"

    invoke-virtual {v1, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-virtual {v1}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;

    move-result-object v1

    invoke-direct {p0, v1}, Lcom/exepretranslator/app/TranslateService;->updateNotification(Ljava/lang/String;)V

    :skip_notify
    return-void
.end method

.method private stopRequested()Z
    .locals 3

    invoke-direct {p0}, Lcom/exepretranslator/app/TranslateService;->prefs()Landroid/content/SharedPreferences;

    move-result-object v0

    const-string v1, "stop_requested"

    const/4 v2, 0x0

    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences;->getBoolean(Ljava/lang/String;Z)Z

    move-result v0

    return v0
.end method

.method private runLoop(I)V
    .locals 13

    move-object/from16 v12, p0

    move/from16 v0, p1

    const v1, 0x10000

    new-array v2, v1, [B

    :outer_loop
    iget v10, v12, Lcom/exepretranslator/app/TranslateService;->codeSize:I

    sub-int v3, v10, v0

    if-gtz v3, :have_remaining

    goto :outer_done

    :have_remaining
    if-le v3, v1, :size_ok

    move v3, v1

    :size_ok
    iget v10, v12, Lcom/exepretranslator/app/TranslateService;->codeOff:I

    add-int v10, v10, v0

    iget-object v4, v12, Lcom/exepretranslator/app/TranslateService;->channel:Ljava/nio/channels/FileChannel;

    const/4 v11, 0x0

    invoke-static {v4, v10, v2, v11, v3}, Lcom/exepretranslator/app/TranslateService;->readFullyAt(Ljava/nio/channels/FileChannel;I[BII)Z

    move-result v4

    if-nez v4, :read_ok

    goto :outer_done

    :read_ok
    iget v10, v12, Lcom/exepretranslator/app/TranslateService;->codeSize:I

    add-int v11, v0, v3

    if-lt v11, v10, :not_last_chunk

    move v6, v3

    goto :safe_end_set

    :not_last_chunk
    const/16 v10, 0x10

    sub-int v6, v3, v10

    if-gtz v6, :safe_end_set

    move v6, v3

    :safe_end_set
    const/4 v5, 0x0

    :inner_loop
    if-ge v5, v6, :inner_done

    iget v10, v12, Lcom/exepretranslator/app/TranslateService;->pe64:I

    invoke-static {v2, v5, v3, v10}, Lcom/exepretranslator/app/TranslateService;->decodeOne([BIII)I

    move-result v8

    and-int/lit16 v9, v8, 0xffff

    const/4 v10, 0x1

    if-ge v9, v10, :len_ok2

    move v9, v10

    :len_ok2
    iget-object v10, v12, Lcom/exepretranslator/app/TranslateService;->out:Ljava/io/PrintStream;

    iget v11, v12, Lcom/exepretranslator/app/TranslateService;->codeOff:I

    add-int/2addr v11, v0

    add-int/2addr v11, v5

    invoke-static {v10, v11, v2, v5, v8}, Lcom/exepretranslator/app/TranslateService;->appendInstrLine(Ljava/io/PrintStream;I[BII)V

    add-int/2addr v5, v9

    goto :inner_loop

    :inner_done
    add-int/2addr v0, v5

    invoke-direct {v12, v0}, Lcom/exepretranslator/app/TranslateService;->saveProgress(I)V

    invoke-direct {v12}, Lcom/exepretranslator/app/TranslateService;->stopRequested()Z

    move-result v10

    if-eqz v10, :outer_loop

    :outer_done
    return-void
.end method

.method private process()V
    .locals 3

    iget-object v0, p0, Lcom/exepretranslator/app/TranslateService;->currentUri:Ljava/lang/String;

    invoke-direct {p0, v0}, Lcom/exepretranslator/app/TranslateService;->openForFile(Ljava/lang/String;)Z

    move-result v0

    if-nez v0, :cont1

    iget-object v0, p0, Lcom/exepretranslator/app/TranslateService;->lastError:Ljava/lang/String;

    invoke-direct {p0, v0}, Lcom/exepretranslator/app/TranslateService;->fail(Ljava/lang/String;)V

    return-void

    :cont1
    invoke-direct {p0}, Lcom/exepretranslator/app/TranslateService;->parseHeader()Z

    move-result v0

    if-nez v0, :cont2

    iget-object v0, p0, Lcom/exepretranslator/app/TranslateService;->lastError:Ljava/lang/String;

    invoke-direct {p0, v0}, Lcom/exepretranslator/app/TranslateService;->fail(Ljava/lang/String;)V

    return-void

    :cont2
    invoke-direct {p0}, Lcom/exepretranslator/app/TranslateService;->saveSectionInfo()V

    invoke-direct {p0}, Lcom/exepretranslator/app/TranslateService;->loadResumeOffset()I

    move-result v0

    if-nez v0, :is_resume

    const/4 v1, 0x0

    goto :open_out

    :is_resume
    const/4 v1, 0x1

    :open_out
    invoke-direct {p0, v1}, Lcom/exepretranslator/app/TranslateService;->openOutput(Z)Z

    move-result v1

    if-nez v1, :cont3

    iget-object v1, p0, Lcom/exepretranslator/app/TranslateService;->lastError:Ljava/lang/String;

    invoke-direct {p0, v1}, Lcom/exepretranslator/app/TranslateService;->fail(Ljava/lang/String;)V

    return-void

    :cont3
    const-string v1, "traduzindo"

    invoke-direct {p0, v1}, Lcom/exepretranslator/app/TranslateService;->setStatus(Ljava/lang/String;)V

    invoke-direct {p0, v0}, Lcom/exepretranslator/app/TranslateService;->runLoop(I)V

    iget-object v1, p0, Lcom/exepretranslator/app/TranslateService;->out:Ljava/io/PrintStream;

    invoke-virtual {v1}, Ljava/io/PrintStream;->close()V

    invoke-direct {p0}, Lcom/exepretranslator/app/TranslateService;->stopRequested()Z

    move-result v1

    if-eqz v1, :mark_paused

    const-string v1, "pausado"

    invoke-direct {p0, v1}, Lcom/exepretranslator/app/TranslateService;->setStatus(Ljava/lang/String;)V

    goto :proc_end

    :mark_paused
    const-string v1, "concluido (100%)"

    invoke-direct {p0, v1}, Lcom/exepretranslator/app/TranslateService;->setStatus(Ljava/lang/String;)V

    :proc_end
    invoke-direct {p0, v1}, Lcom/exepretranslator/app/TranslateService;->updateNotification(Ljava/lang/String;)V

    return-void
.end method

.method public run()V
    .locals 4

    const-string v0, "power"

    invoke-virtual {p0, v0}, Landroid/app/Service;->getSystemService(Ljava/lang/String;)Ljava/lang/Object;

    move-result-object v0

    check-cast v0, Landroid/os/PowerManager;

    sget v1, Landroid/os/PowerManager;->PARTIAL_WAKE_LOCK:I

    const-string v2, "ptexe:work"

    invoke-virtual {v0, v1, v2}, Landroid/os/PowerManager;->newWakeLock(ILjava/lang/String;)Landroid/os/PowerManager$WakeLock;

    move-result-object v0

    iput-object v0, p0, Lcom/exepretranslator/app/TranslateService;->wakeLock:Landroid/os/PowerManager$WakeLock;

    invoke-virtual {v0}, Landroid/os/PowerManager$WakeLock;->acquire()V

    :try_start_0
    invoke-direct {p0}, Lcom/exepretranslator/app/TranslateService;->process()V
    :try_end_0
    .catch Ljava/lang/Exception; {:try_start_0 .. :try_end_0} :catch_0

    goto :after_try

    :catch_0
    move-exception v1

    invoke-virtual {v1}, Ljava/lang/Exception;->getMessage()Ljava/lang/String;

    move-result-object v2

    if-nez v2, :has_msg

    const-string v2, "falha desconhecida"

    :has_msg
    invoke-direct {p0, v2}, Lcom/exepretranslator/app/TranslateService;->fail(Ljava/lang/String;)V

    :after_try
    iget-object v1, p0, Lcom/exepretranslator/app/TranslateService;->wakeLock:Landroid/os/PowerManager$WakeLock;

    if-eqz v1, :skip_rel

    invoke-virtual {v1}, Landroid/os/PowerManager$WakeLock;->release()V

    :skip_rel
    const/4 v1, 0x1

    invoke-virtual {p0, v1}, Landroid/app/Service;->stopForeground(Z)V

    invoke-virtual {p0}, Landroid/app/Service;->stopSelf()V

    return-void
.end method
