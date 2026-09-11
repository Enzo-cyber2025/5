package android.app;

/**
 * Stub de android.app.NotificationChannel (API 26+).
 * PRESENÇA desta classe no classpath simula Android 8.0+;
 * AUSÊNCIA simula Android 7.0/7.1 (API 24-25), onde o APK (minSdk 24)
 * crasha na abertura com NoClassDefFoundError.
 */
public class NotificationChannel {
    public NotificationChannel(String id, CharSequence name, int importance) {}

    public void setDescription(String description) {}
}
