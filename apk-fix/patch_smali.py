"""Apply structural changes after size-preserving patches and APK decoding."""
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
GENERATE = "    invoke-static/range {v4 .. v15}, Lcom/ggufchat/app/Native;->generate(JLjava/lang/String;IFFFFFIILcom/ggufchat/app/Native$GenerateCallback;)Z\n"


MODEL_PICKER_METHOD = ".method private showModelPicker(Ljava/util/ArrayList;Lcom/ggufchat/app/MainActivity$ModelPickListener;)V"
MODEL_PICKER_FILTER = """    const-string v6, "mmproj"

    invoke-virtual {v1, v6}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z

    move-result v1

    if-nez v1, :cond_0

    goto :goto_0"""


def patch_model_picker(source):
    start = source.index(MODEL_PICKER_METHOD)
    end = source.index(".end method", start)
    method = source[start:end]
    if method.count(MODEL_PICKER_FILTER) != 1:
        raise ValueError("Filtro de modelos diferente do original ou já corrigido.")
    method = method.replace(MODEL_PICKER_FILTER, MODEL_PICKER_FILTER.replace("if-nez v1", "if-eqz v1"))
    return source[:start] + method + source[end:]


def apply(decoded: Path):
    app = decoded / "smali/com/ggufchat/app"
    activity = app / "MainActivity.smali"
    activity_source = patch_model_picker(activity.read_text())
    service = app / "GenerationService.smali"
    source = service.read_text()
    if source.count(GENERATE) != 1 or "GenerationResult;->check" in source:
        raise ValueError("GenerationService diferente da versão esperada ou já modificado.")
    # Insert before try_end so native false results go through the existing
    # broadcastError / notifyFinished(error) / wake-lock cleanup path.
    source = source.replace(GENERATE, GENERATE + """
    move-result v6
    invoke-static {v6, v4, v5}, Lcom/ggufchat/app/GenerationResult;->check(ZJ)V
""")
    service.write_text(source)
    activity.write_text(activity_source)
    for name in ("EngineManager", "GenerationResult"):
        shutil.copyfile(HERE / "smali" / f"{name}.smali", app / f"{name}.smali")
