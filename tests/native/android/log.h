// Host-only logger stand-in. Never packaged into the APK.
#define ANDROID_LOG_INFO 4
#define ANDROID_LOG_WARN 5
int __android_log_write(int priority, const char *tag, const char *text);
int __android_log_print(int priority, const char *tag, const char *format, ...);
