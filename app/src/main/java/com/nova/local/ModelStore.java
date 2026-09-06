package com.nova.local;

import android.content.Context;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import android.database.Cursor;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.Locale;
import java.util.Set;

/** Keeps only SAF references. The model bytes stay in the provider and are mmap'ed on demand. */
public final class ModelStore {
    private static final String PREFS = "nova_models";
    private static final String KEY_URIS = "uris";
    private final Context context;
    private final ArrayList<ModelRef> models = new ArrayList<>();

    public ModelStore(Context context) {
        this.context = context.getApplicationContext();
    }

    public ArrayList<ModelRef> loadPersisted() {
        models.clear();
        SharedPreferences preferences = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        Set<String> saved = preferences.getStringSet(KEY_URIS, new LinkedHashSet<>());
        for (String raw : saved) {
            try {
                Uri uri = Uri.parse(raw);
                ModelRef ref = inspect(uri, null);
                if (ref != null) models.add(ref);
            } catch (Throwable ignored) { }
        }
        return new ArrayList<>(models);
    }

    public ModelRef inspect(Uri uri, String fallbackName) {
        if (uri == null) return null;
        ParcelFileDescriptor descriptor = null;
        try {
            descriptor = context.getContentResolver().openFileDescriptor(uri, "r");
            if (descriptor == null) return null;
            long size = descriptor.getStatSize();
            String probe = NativeRuntime.probe(descriptor, size);
            String displayName = queryDisplayName(uri);
            if (displayName == null || displayName.trim().isEmpty()) displayName = fallbackName;
            if (displayName == null || displayName.trim().isEmpty()) displayName = "modelo.gguf";
            String metadataName = field(probe, "name");
            String arch = field(probe, "arch");
            if (metadataName != null && !metadataName.trim().isEmpty()) displayName = metadataName;
            boolean vision = boolField(probe, "vision") || looksVision(displayName, arch);
            boolean projector = looksProjector(displayName, arch);
            return new ModelRef(uri.toString(), displayName, size, arch, vision, projector, probe);
        } catch (Throwable ignored) {
            return new ModelRef(uri.toString(), fallbackName == null ? "modelo.gguf" : fallbackName,
                    0L, "", looksVision(fallbackName, ""), looksProjector(fallbackName, ""), "");
        } finally {
            if (descriptor != null) {
                try { descriptor.close(); } catch (Throwable ignored) { }
            }
        }
    }

    public boolean add(ModelRef ref) {
        if (ref == null) return false;
        for (ModelRef existing : models) {
            if (existing.uri.equals(ref.uri)) return false;
        }
        if (models.size() >= 2) return false;
        models.add(ref);
        persist();
        return true;
    }

    public void remove(ModelRef ref) {
        if (ref == null) return;
        models.remove(ref);
        persist();
    }

    public ArrayList<ModelRef> all() {
        return new ArrayList<>(models);
    }

    public ModelRef firstLanguageModel() {
        for (ModelRef ref : models) if (!ref.projector) return ref;
        return models.isEmpty() ? null : models.get(0);
    }

    /** The second GGUF is treated as a projector when its name advertises mmproj/projector. */
    public ModelRef projectorFor(ModelRef active) {
        for (ModelRef ref : models) {
            if (ref != active && ref.projector) return ref;
        }
        return null;
    }

    private void persist() {
        LinkedHashSet<String> uris = new LinkedHashSet<>();
        for (ModelRef ref : models) uris.add(ref.uri);
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .edit().putStringSet(KEY_URIS, uris).apply();
    }

    private String queryDisplayName(Uri uri) {
        Cursor cursor = null;
        try {
            cursor = context.getContentResolver().query(uri,
                    new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null);
            if (cursor != null && cursor.moveToFirst()) return cursor.getString(0);
        } catch (Throwable ignored) { }
        finally {
            if (cursor != null) cursor.close();
        }
        return null;
    }

    public static ParcelFileDescriptor open(Context context, ModelRef ref) {
        if (ref == null) return null;
        try {
            return context.getContentResolver().openFileDescriptor(Uri.parse(ref.uri), "r");
        } catch (Throwable ignored) {
            return null;
        }
    }

    public static String field(String source, String name) {
        if (source == null) return null;
        String needle = "\"" + name + "\"";
        int start = source.indexOf(needle);
        if (start < 0) return null;
        int colon = source.indexOf(':', start + needle.length());
        if (colon < 0) return null;
        int quote = source.indexOf('"', colon + 1);
        if (quote < 0) return null;
        int end = source.indexOf('"', quote + 1);
        if (end < 0) return null;
        return source.substring(quote + 1, end);
    }

    private static boolean boolField(String source, String name) {
        if (source == null) return false;
        int at = source.indexOf("\"" + name + "\"");
        if (at < 0) return false;
        int colon = source.indexOf(':', at);
        return colon >= 0 && source.regionMatches(true, colon + 1, "true", 0, 4);
    }

    public static boolean looksVision(String name, String arch) {
        String value = ((name == null ? "" : name) + " " + (arch == null ? "" : arch))
                .toLowerCase(Locale.US);
        return value.contains("vision") || value.contains("qwen2-vl") || value.contains("qwen2vl")
                || value.contains("qwen3-vl") || value.contains("llava") || value.contains("gemma3")
                || value.contains("minicpm") || value.contains("pixtral") || value.contains("internvl")
                || value.contains("mllama") || value.contains("mmproj") || value.contains("projector");
    }

    public static boolean looksProjector(String name, String arch) {
        String value = ((name == null ? "" : name) + " " + (arch == null ? "" : arch))
                .toLowerCase(Locale.US);
        return value.contains("mmproj") || value.contains("projector") || value.contains("clip");
    }

    public static String humanSize(long size) {
        if (size <= 0) return "tamanho desconhecido";
        if (size < 1024L * 1024L) return (size / 1024L) + " KB";
        if (size < 1024L * 1024L * 1024L) return String.format(Locale.US, "%.1f MB", size / 1024.0 / 1024.0);
        return String.format(Locale.US, "%.2f GB", size / 1024.0 / 1024.0 / 1024.0);
    }

    public static final class ModelRef {
        public final String uri;
        public final String name;
        public final long size;
        public final String arch;
        public final boolean vision;
        public final boolean projector;
        public final String metadata;

        public ModelRef(String uri, String name, long size, String arch,
                        boolean vision, boolean projector, String metadata) {
            this.uri = uri;
            this.name = name == null ? "modelo.gguf" : name;
            this.size = size;
            this.arch = arch == null ? "" : arch;
            this.vision = vision;
            this.projector = projector;
            this.metadata = metadata == null ? "" : metadata;
        }

        public String shortName() {
            String value = name;
            if (value.length() > 28) value = value.substring(0, 25) + "…";
            return value;
        }
    }
}
