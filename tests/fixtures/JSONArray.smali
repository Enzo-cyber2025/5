.class public Lorg/json/JSONArray;
.super Ljava/util/ArrayList;
.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Ljava/util/ArrayList;-><init>()V
    return-void
.end method
.method public put(Ljava/lang/Object;)Lorg/json/JSONArray;
    .locals 0
    invoke-virtual {p0, p1}, Ljava/util/ArrayList;->add(Ljava/lang/Object;)Z
    return-object p0
.end method
.method public length()I
    .locals 1
    invoke-virtual {p0}, Ljava/util/ArrayList;->size()I
    move-result v0
    return v0
.end method
.method public optJSONObject(I)Lorg/json/JSONObject;
    .locals 1
    invoke-virtual {p0, p1}, Ljava/util/ArrayList;->get(I)Ljava/lang/Object;
    move-result-object v0
    check-cast v0, Lorg/json/JSONObject;
    return-object v0
.end method
