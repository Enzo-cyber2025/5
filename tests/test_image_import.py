from pathlib import Path
import shutil,subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
def test_content_sniffer_not_names_or_mime(tmp_path):
    javac=shutil.which('javac');java=shutil.which('java')
    if not javac or not java:pytest.skip('JDK supplied in CI')
    p=tmp_path/'ImageTest.java';p.write_text(r'''import com.ggufchat.app.ImageFormats;
public class ImageTest {
 static void test(boolean want,byte[] b){if(ImageFormats.matches(b,b.length)!=want)throw new AssertionError();}
 public static void main(String[] args)throws Exception {
  test(true,new byte[]{(byte)255,(byte)216,(byte)255});
  test(true,"\u0089PNG\r\n\u001a\n".getBytes("ISO-8859-1"));
  test(true,"GIF89a".getBytes("US-ASCII"));
  test(true,"RIFFxxxxWEBP".getBytes("US-ASCII"));
  test(true,"xxxxftypheicxxxx".getBytes("US-ASCII"));
  test(true,"xxxxftypavifxxxx".getBytes("US-ASCII"));
  test(false,"xxxxftypisomxxxxmp42".getBytes("US-ASCII"));
  test(false,"plain text containing PNG and image/jpeg".getBytes("UTF-8"));
  test(false,"RIFFxxxxWAVE".getBytes("US-ASCII"));
  test(false,new byte[0]);test(false,new byte[]{(byte)255});
  test(false,"BMP is a file format".getBytes("UTF-8"));
 }
}''')
    subprocess.run([javac,'-d',str(tmp_path),'apk-fix/java/com/ggufchat/app/ImageFormats.java',str(p)],check=True)
    subprocess.run([java,'-cp',str(tmp_path),'ImageTest'],check=True)
def test_real_loaded_vision_and_target_decode():
    s=(ROOT/'apk-fix/java/com/ggufchat/app/AttachmentInference.java').read_text()
    n=(ROOT/'apk-fix/native/mobile.cpp').read_text();d=(ROOT/'apk-fix/java/com/ggufchat/app/ImagePixels.java').read_text()
    assert 'boolean vision=supportsVision(handle)' in s
    assert 'AttachmentInference_supportsVision' in n and 'e->projector && mtmd_support_vision' in n
    assert 'ImageFormats.isImage(f)' in s and 'ImagePixels.decode(f)' in s
    assert 'new ExifInterface' not in s # decoder already applies orientation; no double rotation
    assert 'ALLOCATOR_SOFTWARE' in d and 'setTargetSize' in d and 'ColorSpace.Named.SRGB' in d
    assert 'setOnPartialImageListener(error->false)' in d and 'canvas.drawColor(Color.WHITE)' in d
    assert 'finally{bitmap.recycle();}' in s
