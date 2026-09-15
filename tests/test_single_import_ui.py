from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apk-fix'))
from single_import_ui import patch_single_import_ui

def test_one_import_entry_and_legacy_redirect(tmp_path):
    # Minimal smali method fixture; the actual APK is assembled and tested separately.
    (tmp_path/'MainActivity.smali').write_text('''const-string v0, "Importar .gguf"
.method protected onCreate(Landroid/os/Bundle;)V
    .locals 1
    return-void
.end method
''')
    (tmp_path/'ModelsActivity.smali').write_text('''
.method protected onCreate(Landroid/os/Bundle;)V
    .locals 1
    const-string v0, "Importar 2 GGUFs"
    return-void
.end method
.method protected onResume()V
    .locals 1
    return-void
.end method
''')
    patch_single_import_ui(tmp_path)
    main=(tmp_path/'MainActivity.smali').read_text();legacy=(tmp_path/'ModelsActivity.smali').read_text()
    assert '"Importar GGUF"' in main and 'Importar 2' not in legacy
    assert 'consumeImportNavigation()V' in main and 'onNewIntent' in main
    assert 'ggufchat.openImport' in legacy and '->finish()V' in legacy
    assert '0x24000000' in legacy # CLEAR_TOP + SINGLE_TOP; no duplicate Main instance
