package com.ggufchat.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.pm.PackageManager;
import android.os.Build;
import java.util.WeakHashMap;
import android.content.ComponentName;
import android.content.Intent;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Optional hand-off of an assistant-proposed shell block to the separately installed Termux app.
 * Nothing executes until the user reviews the exact command and confirms the hand-off.
 */
public final class TermuxBridge {
    private static final int MAX_COMMAND_CHARS = 6000;
    private static final Pattern FENCE = Pattern.compile("(?s)```([^\\r\\n`]*)\\r?\\n(.*?)```");
    // Small local models sometimes omit Markdown fences. Accept a single-line
    // command only for familiar Termux utilities; the existing review dialog and
    // explicit confirmation still apply before anything reaches the shell.
    private static final Pattern BARE_COMMAND = Pattern.compile(
        "(?i)^(?:bash|sh|echo|printf|pwd|ls|cat|grep|find|mkdir|touch|date|whoami|uname|python3?|pip3?|pkg|apt|git|curl|wget|termux-[A-Za-z0-9_-]+)(?:\\s+[^\\r\\n]*)?$");
    private static final String PERMISSION = "com.termux.permission.RUN_COMMAND";
    private static final int PERMISSION_REQUEST = 7431;
    private static final String ACTION = "com.termux.RUN_COMMAND";
    private static final String SERVICE = "com.termux.app.RunCommandService";
    private static final WeakHashMap<Activity, String> PENDING = new WeakHashMap<>();

    private TermuxBridge() {}

    public static Button chatButton(Activity activity) {
        Button button = new Button(activity);
        button.setText("Termux");
        button.setContentDescription("Revisar um comando e abri-lo no Termux");
        button.setOnClickListener(view -> offer(activity));
        return button;
    }

    private static Object field(Object object, String name) throws Exception {
        Field f = object.getClass().getDeclaredField(name);
        f.setAccessible(true);
        return f.get(object);
    }

    private static String assistantCommand(Activity activity) throws Exception {
        Object chat = field(activity, "chat");
        if (chat == null) return null;
        Object value = field(chat, "messages");
        if (!(value instanceof ArrayList<?>)) return null;
        ArrayList<?> messages = (ArrayList<?>) value;
        for (int i = messages.size() - 1; i >= 0; i--) {
            Object message = messages.get(i);
            if (!"assistant".equals(field(message, "role"))) continue;
            Object content = field(message, "content");
            if (!(content instanceof String)) return null;
            Matcher matcher = FENCE.matcher((String) content);
            String selected = null;
            while (matcher.find()) {
                String language = matcher.group(1).trim().toLowerCase(java.util.Locale.ROOT);
                if (language.isEmpty() || "bash".equals(language) || "sh".equals(language)
                        || "shell".equals(language) || "termux".equals(language)) {
                    selected = matcher.group(2).trim();
                }
            }
            if (selected != null) return selected;
            String bare = ((String) content).trim();
            return bare.indexOf('`') < 0 && BARE_COMMAND.matcher(bare).matches() ? bare : null;
        }
        return null;
    }

    private static void offer(Activity activity) {
        try {
            String command = assistantCommand(activity);
            if (command == null || command.trim().isEmpty()) {
                Toast.makeText(activity, "A última resposta não contém um bloco bash/sh ou comando simples reconhecido.", Toast.LENGTH_LONG).show();
                return;
            }
            if (command.length() > MAX_COMMAND_CHARS) {
                Toast.makeText(activity, "O comando excede 6.000 caracteres; revise e divida-o antes de executar.", Toast.LENGTH_LONG).show();
                return;
            }
            showReview(activity, command);
        } catch (Exception e) {
            Toast.makeText(activity, "Não foi possível ler o comando da resposta: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    private static void showReview(Activity activity, String command) {
        TextView code = new TextView(activity);
        code.setText(command);
        code.setTextIsSelectable(true);
        code.setTextSize(13);
        code.setTypeface(android.graphics.Typeface.MONOSPACE);
        code.setPadding(24, 16, 24, 16);
        ScrollView scroll = new ScrollView(activity);
        scroll.addView(code, new ScrollView.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        AlertDialog dialog = new AlertDialog.Builder(activity)
            .setTitle("Revisar comando do Termux")
            .setMessage("Nada será executado sem sua confirmação. O comando roda no Termux, com as permissões concedidas a ele. Revise todo o conteúdo antes de continuar.")
            .setView(scroll)
            .setNegativeButton("Cancelar", null)
            .setPositiveButton("Abrir no Termux", (d, which) -> confirmPermissionAndRun(activity, command))
            .create();
        dialog.show();
    }

    private static void confirmPermissionAndRun(Activity activity, String command) {
        if (Build.VERSION.SDK_INT >= 23 && activity.checkSelfPermission(PERMISSION) != PackageManager.PERMISSION_GRANTED) {
            synchronized (PENDING) { PENDING.put(activity, command); }
            activity.requestPermissions(new String[]{PERMISSION}, PERMISSION_REQUEST);
            return;
        }
        run(activity, command);
    }

    public static void permissionResult(Activity activity, int requestCode, String[] permissions, int[] grantResults) {
        if (requestCode != PERMISSION_REQUEST) return;
        String command;
        synchronized (PENDING) { command = PENDING.remove(activity); }
        if (command == null) return;
        if (grantResults != null && grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            run(activity, command);
        } else {
            Toast.makeText(activity, "Permissão RUN_COMMAND negada; comando não executado.", Toast.LENGTH_LONG).show();
        }
    }

    private static void run(Activity activity, String command) {
        Intent intent = new Intent(ACTION);
        intent.setComponent(new ComponentName("com.termux", SERVICE));
        intent.putExtra("com.termux.RUN_COMMAND_PATH", "/data/data/com.termux/files/usr/bin/bash");
        intent.putExtra("com.termux.RUN_COMMAND_ARGUMENTS", new String[]{"-lc", command});
        intent.putExtra("com.termux.RUN_COMMAND_WORKDIR", "/data/data/com.termux/files/home");
        intent.putExtra("com.termux.RUN_COMMAND_BACKGROUND", false);
        intent.putExtra("com.termux.RUN_COMMAND_SESSION_ACTION", "0");
        try {
            activity.startService(intent);
            Toast.makeText(activity, "Comando enviado ao Termux. O resultado permanece no Termux; confira-o lá.", Toast.LENGTH_LONG).show();
        } catch (SecurityException e) {
            Toast.makeText(activity, "Permissão negada. No Termux, habilite 'Allow external apps' e conceda RUN_COMMAND ao GGUF Chat.", Toast.LENGTH_LONG).show();
            android.util.Log.w("GGUFTermux", "Termux RUN_COMMAND permission denied", e);
        } catch (Exception e) {
            Toast.makeText(activity, "Termux ausente ou RUN_COMMAND indisponível. Instale/configure Termux e tente novamente.", Toast.LENGTH_LONG).show();
            android.util.Log.w("GGUFTermux", "Could not hand command to Termux", e);
        }
    }
}
