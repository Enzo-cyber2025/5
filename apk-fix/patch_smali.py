"""Apply structural changes after size-preserving patches and APK decoding."""
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
GENERATE = "    invoke-static/range {v4 .. v15}, Lcom/ggufchat/app/Native;->generate(JLjava/lang/String;IFFFFFIILcom/ggufchat/app/Native$GenerateCallback;)Z\n"


def apply(decoded: Path):
    app = decoded / "smali/com/ggufchat/app"
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
    for name in ("EngineManager", "GenerationResult"):
        shutil.copyfile(HERE / "smali" / f"{name}.smali", app / f"{name}.smali")
