-keep class com.vulcanmind.vulkanmind.inference.** { *; }
-keep class com.vulcanmind.vulkanmind.data.** { *; }
-keepclasseswithmembers class * {
    native <methods>;
}
-keep class org.ggml.** { *; }
