"""Attachment storage and binary-manifest regressions; device UI covered separately."""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile
import pytest
import jdk4py

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apk-fix'))
from attachment_manifest import attachment_manifest
from mobile_manifest import enforce_min_sdk


def test_private_provider_is_only_manifest_change_besides_minimum():
    from androguard.core.axml import AXMLPrinter
    from lxml import etree
    with zipfile.ZipFile(ROOT/'.cache/gguf/GGUF-Chat.apk') as z:original=z.read('AndroidManifest.xml')
    before=AXMLPrinter(enforce_min_sdk(original)).get_xml_obj()
    after=AXMLPrinter(attachment_manifest(original)).get_xml_obj()
    ns='{http://schemas.android.com/apk/res/android}'
    providers=after.findall('./application/provider');assert len(providers)==1
    p=providers[0]
    assert p.attrib=={ns+'name':'com.ggufchat.app.AttachmentProvider',ns+'exported':'false',ns+'authorities':'com.ggufchat.app.attachments',ns+'grantUriPermissions':'true'}
    after.find('application').remove(p)
    assert etree.tostring(before)==etree.tostring(after)
    with pytest.raises(ValueError,match='already present'):attachment_manifest(attachment_manifest(original))


def test_real_stream_copy_handles_over_2gb_empty_and_cancellation(tmp_path):
    javac=shutil.which('javac')
    if not javac:pytest.skip('JDK compiler supplied by CI')
    source=(ROOT/'apk-fix/java/com/ggufchat/app/AttachmentStore.java').read_text()
    method=re.search(r'    static long copy\(.*?\n    }',source,re.S).group()
    code='import java.io.*;import java.util.concurrent.atomic.AtomicBoolean;\npublic class CopyTest {\n'+method+r'''
    public static void main(String[] args) throws Exception {
        final long size=3L*1024*1024*1024+17;
        InputStream in=new InputStream(){long left=size;public int read(){throw new AssertionError();}
            public int read(byte[] b){assert b.length==128*1024;if(left==0)return -1;int n=(int)Math.min(left,b.length);left-=n;return n;}};
        OutputStream sink=new OutputStream(){public void write(int b){throw new AssertionError();}public void write(byte[] b,int off,int n){assert n<=128*1024;}};
        assert copy(in,sink,new AtomicBoolean())==size;
        assert copy(new ByteArrayInputStream(new byte[0]),sink,new AtomicBoolean())==0;
        try{copy(new ByteArrayInputStream(new byte[20]),sink,new AtomicBoolean(true));throw new AssertionError();}catch(InterruptedIOException expected){}
        OutputStream full=new OutputStream(){public void write(int b)throws IOException{throw new IOException("disk full");}};
        try{copy(new ByteArrayInputStream(new byte[20]),full,new AtomicBoolean());throw new AssertionError();}catch(IOException expected){}
    }
}'''
    file=tmp_path/'CopyTest.java';file.write_text(code)
    subprocess.run([javac,'-d',str(tmp_path),str(file)],check=True)
    subprocess.run([str(jdk4py.JAVA_HOME/'bin/java'),'-ea','-Xmx32m','-cp',str(tmp_path),'CopyTest'],check=True)


def test_pickers_and_storage_have_no_file_type_size_or_count_quota():
    ui=(ROOT/'apk-fix/java/com/ggufchat/app/Attachments.java').read_text()
    store=(ROOT/'apk-fix/java/com/ggufchat/app/AttachmentStore.java').read_text()
    assert 'Intent.EXTRA_ALLOW_MULTIPLE,true' in ui
    assert 's.pick("*/*",FILES)' in ui and 'pick("image/*",PHOTOS)' in ui
    assert 'MediaStore.EXTRA_OUTPUT,uri' in ui and 'Tirar outra foto' in ui
    assert 's.camera.setEnabled(s.multimodal())' in ui
    assert 'ByteArrayOutputStream' not in store and 'Bitmap' not in store
    assert 'long total=0' in store and 'new byte[128*1024]' in store
    assert 'Native;' not in ui and 'Leitura local:' in ui
    assert 'Anexos vinculados a esta mensagem para leitura.' in ui
