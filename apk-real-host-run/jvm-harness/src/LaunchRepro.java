import android.content.Context;
import com.ggufchat.app.ChatStore;
import com.ggufchat.app.ModelStore;

import java.io.File;
import java.io.FileOutputStream;
import java.lang.reflect.Field;

/**
 * Reproduz, num JVM, o caminho de ABERTURA do APK REAL GGUF-Chat.apk.
 * (bytecode real extraído do classes.dex via enjarify; org.json real; apenas
 * Context.getFilesDir() é simulado).
 */
public class LaunchRepro {

    static void writeFile(File f, String s) throws Exception {
        FileOutputStream fo = new FileOutputStream(f);
        fo.write(s.getBytes("UTF-8"));
        fo.close();
    }

    static void dump(Object o) {
        if (o == null) { System.out.println("      <null>"); return; }
        Class<?> c = o.getClass();
        StringBuilder sb = new StringBuilder();
        for (Field f : c.getDeclaredFields()) {
            try {
                f.setAccessible(true);
                Object v = f.get(o);
                if (v instanceof String || v instanceof Number || v instanceof Boolean) {
                    sb.append(f.getName()).append('=').append(v).append("  ");
                }
            } catch (Throwable ignored) {}
        }
        System.out.println("      " + c.getSimpleName() + " { " + sb + "}");
    }

    static void runCase(String title, Runnable r) {
        System.out.println("\n=== " + title + " ===");
        try {
            r.run();
            System.out.println("  RESULTADO: OK (sem crash)");
        } catch (Throwable t) {
            System.out.println("  RESULTADO: CRASH  ->  " + t.getClass().getName() + ": " + t.getMessage());
            StackTraceElement[] st = t.getStackTrace();
            int n = Math.min(st.length, 10);
            for (int i = 0; i < n; i++) System.out.println("        at " + st[i]);
        }
    }

    public static void main(String[] args) throws Exception {
        File base = File.createTempFile("ggufchat-launch", ".dir");
        base.delete();
        base.mkdirs();
        final File filesDir = base;
        System.out.println("filesDir (simulado) = " + filesDir);
        final Context ctx = new Context(filesDir);

        runCase("T1 - models.json AUSENTE (instalação limpa)", new Runnable() {
            public void run() {
                Object r = ModelStore.load(ctx);
                System.out.println("  load() -> " + r);
            }
        });

        runCase("T2 - models.json VAZIO (0 bytes)", new Runnable() {
            public void run() {
                try { new File(filesDir, "models.json").createNewFile(); } catch (Exception e) {}
                ModelStore.load(ctx);
            }
        });

        runCase("T3 - models.json CORROMPIDO ('{oops')", new Runnable() {
            public void run() {
                try { writeFile(new File(filesDir, "models.json"), "{oops"); } catch (Exception e) {}
                ModelStore.load(ctx);
            }
        });

        runCase("T4 - models.json VÁLIDO (schema real)", new Runnable() {
            public void run() {
                try {
                    String json = "[{\"id\":\"m1\",\"name\":\"tiny-llama-022\",\"architecture\":\"llama\","
                        + "\"path\":\"/data/data/com.ggufchat.app/files/models/tiny-llama-022.gguf\","
                        + "\"size\":117152,\"importedAt\":1700000000000,\"fileName\":\"tiny-llama-022.gguf\","
                        + "\"mmprojPath\":null,\"multimodal\":false}]";
                    writeFile(new File(filesDir, "models.json"), json);
                } catch (Exception e) {}
                java.util.ArrayList<?> r = ModelStore.load(ctx);
                System.out.println("  load() -> " + r.size() + " modelo(s)");
                if (!r.isEmpty()) dump(r.get(0));
            }
        });

        runCase("T5 - chats.json VAZIO (0 bytes)", new Runnable() {
            public void run() {
                try {
                    new File(filesDir, "models.json").delete();
                    new File(filesDir, "chats.json").createNewFile();
                } catch (Exception e) {}
                ChatStore.load(ctx);
            }
        });

        runCase("T6 - chats.json VÁLIDO (schema real)", new Runnable() {
            public void run() {
                try {
                    String json = "[{\"id\":\"c1\",\"title\":\"CPU\",\"modelPath\":\"/data/data/com.ggufchat.app/files/models/tiny-llama-022.gguf\","
                        + "\"mmprojPath\":null,\"createdAt\":1700000000000,\"updatedAt\":1700000000000,"
                        + "\"messages\":[{\"role\":\"user\",\"content\":\"oi\"}],\"nPredict\":64,\"temperature\":0.8,"
                        + "\"topP\":0.95,\"topK\":40,\"minP\":0.05,\"repeatPenalty\":1.1,\"repeatLastN\":64,"
                        + "\"contextSize\":256,\"nThreads\":4,\"gpuLayers\":0,\"useMmap\":false,\"thinking\":false,\"webSearch\":false}]";
                    writeFile(new File(filesDir, "chats.json"), json);
                } catch (Exception e) {}
                java.util.ArrayList<?> r = ChatStore.load(ctx);
                System.out.println("  load() -> " + r.size() + " conversa(s)");
                if (!r.isEmpty()) dump(r.get(0));
            }
        });

        runCase("T7 - Native.<clinit> (System.loadLibrary(\"aijni\"))", new Runnable() {
            public void run() {
                // Neste JVM não existe libaijni.so => mostra o UnsatisfiedLinkError
                // que ocorreria se a .so nativa faltasse/fosse de ABI errada.
                try { Class.forName("com.ggufchat.app.Native"); }
                catch (Throwable t) { throw new RuntimeException(t); }
                System.out.println("  Native carregou OK");
            }
        });

        System.out.println("\nFIM.");
    }
}
