package android.app;

/**
 * Stub de android.app.NotificationManager.
 * O descriptor precisa bater com o invokevirtual do App.onCreate:
 *   createNotificationChannel(Landroid/app/NotificationChannel;)V
 */
public class NotificationManager {
    public NotificationManager() {}

    public void createNotificationChannel(NotificationChannel channel) {
        // no-op: o stub só precisa existir para o bytecode real avançar
    }
}
