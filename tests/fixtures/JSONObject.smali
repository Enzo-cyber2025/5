.class public Lorg/json/JSONObject;
.super Ljava/util/HashMap;

# Minimal Android JSONObject contract for host tests only.
.field public static final NULL:Ljava/lang/Object;

.method static constructor <clinit>()V
    .locals 1
    new-instance v0, Ljava/lang/Object;
    invoke-direct {v0}, Ljava/lang/Object;-><init>()V
    sput-object v0, Lorg/json/JSONObject;->NULL:Ljava/lang/Object;
    return-void
.end method

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Ljava/util/HashMap;-><init>()V
    return-void
.end method

.method public put(Ljava/lang/String;Ljava/lang/Object;)Lorg/json/JSONObject;
    .locals 0
    invoke-super {p0, p1, p2}, Ljava/util/HashMap;->put(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;
    return-object p0
.end method

.method public put(Ljava/lang/String;J)Lorg/json/JSONObject;
    .locals 1
    invoke-static {p2, p3}, Ljava/lang/Long;->valueOf(J)Ljava/lang/Long;
    move-result-object v0
    invoke-virtual {p0, p1, v0}, Lorg/json/JSONObject;->put(Ljava/lang/String;Ljava/lang/Object;)Lorg/json/JSONObject;
    return-object p0
.end method

.method public put(Ljava/lang/String;Z)Lorg/json/JSONObject;
    .locals 1
    invoke-static {p2}, Ljava/lang/Boolean;->valueOf(Z)Ljava/lang/Boolean;
    move-result-object v0
    invoke-virtual {p0, p1, v0}, Lorg/json/JSONObject;->put(Ljava/lang/String;Ljava/lang/Object;)Lorg/json/JSONObject;
    return-object p0
.end method

.method public optString(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;
    .locals 2
    invoke-virtual {p0, p1}, Ljava/util/HashMap;->get(Ljava/lang/Object;)Ljava/lang/Object;
    move-result-object v0
    if-eqz v0, :default
    sget-object v1, Lorg/json/JSONObject;->NULL:Ljava/lang/Object;
    if-eq v0, v1, :default
    invoke-static {v0}, Ljava/lang/String;->valueOf(Ljava/lang/Object;)Ljava/lang/String;
    move-result-object v0
    return-object v0
    :default
    return-object p2
.end method

.method public optLong(Ljava/lang/String;J)J
    .locals 2
    invoke-virtual {p0, p1}, Ljava/util/HashMap;->get(Ljava/lang/Object;)Ljava/lang/Object;
    move-result-object v0
    instance-of v1, v0, Ljava/lang/Number;
    if-eqz v1, :default
    check-cast v0, Ljava/lang/Number;
    invoke-virtual {v0}, Ljava/lang/Number;->longValue()J
    move-result-wide v0
    return-wide v0
    :default
    return-wide p2
.end method

.method public optBoolean(Ljava/lang/String;Z)Z
    .locals 2
    invoke-virtual {p0, p1}, Ljava/util/HashMap;->get(Ljava/lang/Object;)Ljava/lang/Object;
    move-result-object v0
    instance-of v1, v0, Ljava/lang/Boolean;
    if-eqz v1, :default
    check-cast v0, Ljava/lang/Boolean;
    invoke-virtual {v0}, Ljava/lang/Boolean;->booleanValue()Z
    move-result v0
    return v0
    :default
    return p2
.end method

.method public optInt(Ljava/lang/String;I)I
    .locals 2
    invoke-virtual {p0, p1}, Ljava/util/HashMap;->get(Ljava/lang/Object;)Ljava/lang/Object;
    move-result-object v0
    instance-of v1, v0, Ljava/lang/Number;
    if-eqz v1, :default
    check-cast v0, Ljava/lang/Number;
    invoke-virtual {v0}, Ljava/lang/Number;->intValue()I
    move-result v0
    return v0
    :default
    return p2
.end method

.method public optDouble(Ljava/lang/String;D)D
    .locals 2
    invoke-virtual {p0, p1}, Ljava/util/HashMap;->get(Ljava/lang/Object;)Ljava/lang/Object;
    move-result-object v0
    instance-of v1, v0, Ljava/lang/Number;
    if-eqz v1, :default
    check-cast v0, Ljava/lang/Number;
    invoke-virtual {v0}, Ljava/lang/Number;->doubleValue()D
    move-result-wide v0
    return-wide v0
    :default
    return-wide p2
.end method

.method public put(Ljava/lang/String;D)Lorg/json/JSONObject;
    .locals 1
    invoke-static {p2, p3}, Ljava/lang/Double;->valueOf(D)Ljava/lang/Double;
    move-result-object v0
    invoke-virtual {p0, p1, v0}, Lorg/json/JSONObject;->put(Ljava/lang/String;Ljava/lang/Object;)Lorg/json/JSONObject;
    return-object p0
.end method

.method public optJSONArray(Ljava/lang/String;)Lorg/json/JSONArray;
    .locals 1
    invoke-virtual {p0, p1}, Ljava/util/HashMap;->get(Ljava/lang/Object;)Ljava/lang/Object;
    move-result-object v0
    check-cast v0, Lorg/json/JSONArray;
    return-object v0
.end method

.method public put(Ljava/lang/String;I)Lorg/json/JSONObject;
    .locals 1
    invoke-static {p2}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;
    move-result-object v0
    invoke-virtual {p0, p1, v0}, Lorg/json/JSONObject;->put(Ljava/lang/String;Ljava/lang/Object;)Lorg/json/JSONObject;
    return-object p0
.end method

.method public has(Ljava/lang/String;)Z
    .locals 1
    invoke-virtual {p0, p1}, Ljava/util/HashMap;->containsKey(Ljava/lang/Object;)Z
    move-result v0
    return v0
.end method
.method public isNull(Ljava/lang/String;)Z
    .locals 2
    invoke-virtual {p0, p1}, Ljava/util/HashMap;->get(Ljava/lang/Object;)Ljava/lang/Object;
    move-result-object v0
    if-eqz v0, :yes
    sget-object v1, Lorg/json/JSONObject;->NULL:Ljava/lang/Object;
    if-eq v0, v1, :yes
    const/4 v0, 0x0
    return v0
    :yes
    const/4 v0, 0x1
    return v0
.end method
.method public getString(Ljava/lang/String;)Ljava/lang/String;
    .locals 1
    invoke-virtual {p0, p1}, Ljava/util/HashMap;->get(Ljava/lang/Object;)Ljava/lang/Object;
    move-result-object v0
    check-cast v0, Ljava/lang/String;
    return-object v0
.end method
