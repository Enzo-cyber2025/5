package com.ggufchat.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import java.io.BufferedWriter;
import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;

/** User-controlled clarification and bounded, app-private context snapshots. */
public final class AssistantOptions {
    private static final String PREFS = "gguf-assistant-options";
    private static final String ASK = "ask_clarifying_questions";
    private static final String ARCHIVE = "archive_context";
    private static final String QUOTA_MB = "context_archive_quota_mb";
    private static final int DEFAULT_QUOTA_MB = 64;
    private static final long MAX_PER_CHAT_BYTES = 8L * 1024L * 1024L;
    private static final long FREE_SPACE_RESERVE = 32L * 1024L * 1024L;

    private AssistantOptions() {}

    private static android.content.SharedPreferences prefs(Context c) {
        return c.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private static Object field(Object object, String name) throws Exception {
        Field f = object.getClass().getDeclaredField(name);
        f.setAccessible(true);
        return f.get(object);
    }

    public static Button button(Activity activity) {
        Button b = new Button(activity);
        b.setText("Memória");
        b.setContentDescription("Perguntas de esclarecimento e arquivo local de contexto");
        b.setOnClickListener(v -> show(activity));
        return b;
    }

    /** Adds a visible system-role instruction; default is off. */
    public static void applyClarification(Context c, List<String[]> rows) {
        if (!prefs(c).getBoolean(ASK, false) || rows == null || rows.isEmpty()
                || !"system".equals(rows.get(0)[0])) return;
        rows.get(0)[1] += "\nQuando faltar informação essencial ou houver ambiguidade relevante, faça uma pergunta curta de esclarecimento antes de assumir. Não faça perguntas desnecessárias quando puder responder com segurança.";
    }

    /**
     * Saves the current prompt history in the app's private files directory.
     * This is opt-in, local-only and bounded. When the quota is reached, the
     * oldest chat snapshots are removed first. A single oversized snapshot is
     * reduced to its newest portion, with an explicit marker.
     */
    public static void captureContext(Context c, Object chat, List<String[]> rows) throws Exception {
        android.content.SharedPreferences p = prefs(c);
        if (!p.getBoolean(ARCHIVE, false) || rows == null) return;
        int quotaMb = Math.max(1, Math.min(2048, p.getInt(QUOTA_MB, DEFAULT_QUOTA_MB)));
        long quota = quotaMb * 1024L * 1024L;
        File root = new File(c.getFilesDir(), "context-archive");
        if (!root.exists() && !root.mkdirs()) throw new java.io.IOException("Não foi possível criar o arquivo privado de contexto");
        String chatId = String.valueOf(field(chat, "id"));
        String safeName = hex(chatId.getBytes(StandardCharsets.UTF_8));
        File current = new File(root, safeName + ".txt");
        File temp = new File(root, safeName + ".tmp");
        long perChatLimit = Math.min(MAX_PER_CHAT_BYTES, quota);
        int maxChars = (int)Math.max(256, Math.min(Integer.MAX_VALUE, perChatLimit / 3));
        StringBuilder text = new StringBuilder(Math.min(maxChars, 64 * 1024));
        for (String[] row : rows) {
            if (row == null || row.length < 2 || "system".equals(row[0])) continue;
            appendBounded(text, "[" + safe(row[0]) + "]\n", maxChars);
            appendBounded(text, safe(row[1]), maxChars);
            appendBounded(text, "\n\n", maxChars);
        }
        String snapshot = text.toString();
        String omitted = "[Parte mais antiga omitida pelo limite de armazenamento]\n";
        if (snapshot.length() >= maxChars) {
            int tailChars = Math.max(0, maxChars - omitted.length());
            snapshot = omitted + snapshot.substring(Math.max(0, snapshot.length() - tailChars));
        }
        try (FileOutputStream stream = new FileOutputStream(temp);
             BufferedWriter w = new BufferedWriter(new OutputStreamWriter(stream, StandardCharsets.UTF_8))) {
            w.write(snapshot);
            w.flush();
            stream.getFD().sync();
        }
        long free = root.getUsableSpace();
        long effectiveQuota = Math.min(quota, Math.max(0, free - FREE_SPACE_RESERVE));
        if (temp.length() > effectiveQuota) {
            temp.delete();
            android.util.Log.w("GGUFAssistantOptions", "Insufficient free space for context archive; keeping previous snapshot");
            return;
        }
        File[] files = root.listFiles((dir, name) -> name.endsWith(".txt"));
        List<File> old = new ArrayList<>();
        if (files != null) Collections.addAll(old, files);
        Collections.sort(old, Comparator.comparingLong(File::lastModified));
        long used = 0;
        for (File f : old) if (!f.equals(current)) used += f.length();
        for (File f : old) {
            if (used + temp.length() <= effectiveQuota) break;
            if (f.equals(current)) continue;
            long size = f.length();
            if (f.delete()) used -= size;
        }
        if (used + temp.length() > effectiveQuota) {
            temp.delete();
            android.util.Log.w("GGUFAssistantOptions", "Unable to free context archive quota; keeping previous snapshot");
            return;
        }
        File backup = new File(root, safeName + ".bak");
        if (backup.exists()) backup.delete();
        boolean hadCurrent = current.exists();
        if (hadCurrent && !current.renameTo(backup)) {
            temp.delete();
            throw new java.io.IOException("Não foi possível preparar a atualização do arquivo de contexto");
        }
        if (!temp.renameTo(current)) {
            temp.delete();
            if (hadCurrent) backup.renameTo(current);
            throw new java.io.IOException("Não foi possível atualizar o arquivo de contexto");
        }
        if (backup.exists()) backup.delete();
        current.setLastModified(System.currentTimeMillis());
    }

    private static void appendBounded(StringBuilder target, String value, int maxChars) {
        if (value == null || value.isEmpty()) return;
        if (value.length() >= maxChars) {
            target.setLength(0);
            target.append(value, value.length() - maxChars, value.length());
            return;
        }
        target.append(value);
        if (target.length() > maxChars) target.delete(0, target.length() - maxChars);
    }

    private static String safe(String s) {
        if (s == null) return "";
        return s.replace("\u0000", " ");
    }

    private static String hex(byte[] input) throws Exception {
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(input);
        StringBuilder out = new StringBuilder(digest.length * 2);
        for (byte b : digest) out.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
        return out.toString();
    }

    private static long archiveBytes(Context c) {
        File root = new File(c.getFilesDir(), "context-archive");
        File[] files = root.listFiles((dir, name) -> name.endsWith(".txt"));
        long total = 0;
        if (files != null) for (File f : files) total += f.length();
        return total;
    }

    private static void show(Activity a) {
        android.content.SharedPreferences p = prefs(a);
        LinearLayout form = new LinearLayout(a);
        form.setOrientation(LinearLayout.VERTICAL);
        int pad = Math.round(20 * a.getResources().getDisplayMetrics().density);
        form.setPadding(pad, pad / 2, pad, 0);
        TextView info = new TextView(a);
        info.setText("Perguntas: quando ativadas, o modelo pode pedir esclarecimentos. O arquivo guarda uma cópia local do histórico recente por conversa, somente após ativação. Ele fica no armazenamento privado do app; os arquivos mais antigos são removidos ao atingir a cota. Isso não aumenta o limite de contexto do modelo.");
        form.addView(info);
        CheckBox questions = new CheckBox(a);
        questions.setText("Permitir perguntas de esclarecimento");
        questions.setChecked(p.getBoolean(ASK, false));
        form.addView(questions);
        CheckBox archive = new CheckBox(a);
        archive.setText("Salvar contexto automaticamente a cada mensagem enviada");
        archive.setChecked(p.getBoolean(ARCHIVE, false));
        form.addView(archive);
        TextView quotaLabel = new TextView(a);
        quotaLabel.setText("Limite total do arquivo (MB; de 1 a 2048)");
        form.addView(quotaLabel);
        EditText quota = new EditText(a);
        quota.setInputType(InputType.TYPE_CLASS_NUMBER);
        quota.setSingleLine(true);
        quota.setText(String.valueOf(p.getInt(QUOTA_MB, DEFAULT_QUOTA_MB)));
        quota.setContentDescription("Limite de armazenamento de contexto em megabytes");
        form.addView(quota);
        TextView used = new TextView(a);
        used.setText("Usado: " + (archiveBytes(a) / (1024 * 1024)) + " MB. O arquivo não é enviado à rede.");
        form.addView(used);
        AlertDialog dialog = new AlertDialog.Builder(a).setTitle("Perguntas e memória local").setView(form)
                .setPositiveButton("Salvar", null).setNegativeButton("Cancelar", null)
                .setNeutralButton("Apagar arquivo", null).create();
        dialog.setOnShowListener(v -> {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(button -> {
                try {
                    String raw = quota.getText().toString().trim();
                    int mb = Integer.parseInt(raw);
                    if (mb < 1 || mb > 2048) throw new IllegalArgumentException("A cota deve estar entre 1 e 2048 MB.");
                    boolean ok = p.edit().putBoolean(ASK, questions.isChecked()).putBoolean(ARCHIVE, archive.isChecked()).putInt(QUOTA_MB, mb).commit();
                    if (!ok) throw new java.io.IOException("Falha ao salvar as preferências");
                    Toast.makeText(a, "Preferências salvas", Toast.LENGTH_SHORT).show();
                    dialog.dismiss();
                } catch (Exception e) {
                    Toast.makeText(a, "Não foi possível salvar: " + e.getMessage(), Toast.LENGTH_LONG).show();
                }
            });
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener(button -> {
                File root = new File(a.getFilesDir(), "context-archive");
                File[] files = root.listFiles();
                if (files != null) for (File f : files) f.delete();
                Toast.makeText(a, "Arquivo local apagado", Toast.LENGTH_SHORT).show();
                dialog.dismiss();
            });
        });
        dialog.show();
    }
}
