package android.app;

/**
 * Stub mínimo de android.app.Application usado para executar o bytecode REAL
 * de com.ggufchat.app.App (do APK) numa JVM pura. Fornece apenas o que
 * App.<init>/App.onCreate referenciam.
 */
public class Application {
    public Application() {}

    public void onCreate() {}

    public Object getSystemService(String name) {
        // "notification" -> NotificationManager (stub); o resto retorna null
        if ("notification".equals(name)) return new NotificationManager();
        return null;
    }
}
