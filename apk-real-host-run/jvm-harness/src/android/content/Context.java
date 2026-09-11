package android.content;

import java.io.File;

/**
 * Stub mínimo de android.content.Context.
 *
 * O código REAL do APK (ModelStore.load / ChatStore.load) só usa
 * Context.getFilesDir() no caminho de inicialização. Este stub fornece
 * exatamente esse método, apontando para um diretório temporário, para que o
 * bytecode REAL (extraído do GGUF-Chat.apk e convertido por enjarify) rode num
 * JVM comum.
 */
public class Context {
    private final File filesDir;

    public Context(File filesDir) {
        this.filesDir = filesDir;
    }

    public File getFilesDir() {
        return filesDir;
    }
}
