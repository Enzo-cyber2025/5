import com.ggufchat.app.App;

/**
 * Roda o bytecode REAL de com.ggufchat.app.App.onCreate() (Application do APK)
 * numa JVM pura, simulando diferentes versões de Android.
 *
 * Uso: LaunchCrashRepro <sdk_int>
 *   sdk_int = 25  -> Android 7.1 (o guard de API 26 deve pular o NotificationChannel)
 *   sdk_int = 33  -> Android 13 (cria o canal via stubs)
 */
public class LaunchCrashRepro {
    public static void main(String[] args) {
        int sdk = args.length > 0 ? Integer.parseInt(args[0]) : 0;
        android.os.Build.VERSION.SDK_INT = sdk;

        boolean hasChannel;
        try {
            Class.forName("android.app.NotificationChannel");
            hasChannel = true;
        } catch (Throwable t) {
            hasChannel = false;
        }
        System.out.println("[LaunchCrashRepro] SDK_INT=" + sdk
                + " | NotificationChannel no runtime=" + hasChannel
                + (hasChannel ? " (API>=26)" : " (API<26)"));

        try {
            App app = new App();
            System.out.println("[LaunchCrashRepro] App instanciado. Executando app.onCreate() ...");
            app.onCreate();
            System.out.println("[LaunchCrashRepro] App.onCreate() terminou SEM erro -> app abriria normalmente.");
        } catch (Throwable t) {
            System.out.println("[LaunchCrashRepro] >>> CRASH: " + t.getClass().getName()
                    + (t.getMessage() != null ? ": " + t.getMessage() : ""));
            for (StackTraceElement e : t.getStackTrace()) {
                if (e.getClassName().startsWith("com.ggufchat")) {
                    System.out.println("        at " + e);
                }
            }
        }
    }
}
