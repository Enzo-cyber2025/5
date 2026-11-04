package com.ggufchat.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
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
import android.widget.EditText;
import android.text.InputType;
import android.content.SharedPreferences;
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
    private static final String PREFS = "gguf-termux-access";
    private static final String MODE_KEY = "mode";
    private static final int MODE_OFF = 0;
    private static final int MODE_MODERATE = 1;
    private static final int MODE_COMPLETE = 2;
    private static final int MODE_COMPLETE_AUTH = 3;
    private static final String AUTH_PHRASE = "AUTORIZO";
    private static final String[] MODES = {"Sem Termux", "Moderado", "Completo", "Completo com autorização"};
    private static final Pattern MODERATE_COMMAND = Pattern.compile(
        "(?i)^(?:pwd|date|whoami|uname(?: -a)?|ls(?: -[alh]+)?(?: [A-Za-z0-9_./-]+)?|df(?: -h)?|free(?: -h)?|getprop(?: [A-Za-z0-9._-]+)?|termux-info|pkg list-installed)$");
    private static final WeakHashMap<Activity, String> PENDING = new WeakHashMap<>();

    private TermuxBridge() {}

    private static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private static int mode(Context context) {
        return Math.max(MODE_OFF, Math.min(MODE_COMPLETE_AUTH, prefs(context).getInt(MODE_KEY, MODE_OFF)));
    }

    public static Button settingsButton(Activity activity) {
        Button button = new Button(activity);
        button.setText("Modo Termux");
        button.setContentDescription("Configurar modo de acesso ao Termux");
        button.setOnClickListener(view -> showModes(activity));
        return button;
    }

    private static void showModes(Activity activity) {
        final String[] descriptions = {
            "Desativado: nenhum comando pode ser encaminhado.",
            "Moderado: somente comandos curtos de consulta da lista permitida; cada comando é exibido para revisão.",
            "Completo: aceita comandos arbitrários propostos pelo modelo, mas cada comando ainda exige revisão e toque de confirmação.",
            "Completo com autorização: comandos amplos; além da revisão, digite AUTORIZO em cada encaminhamento e conceda RUN_COMMAND ao Termux."
        };
        int selected = mode(activity);
        AlertDialog.Builder builder = new AlertDialog.Builder(activity).setTitle("Modo de acesso ao Termux");
        String[] choices = new String[MODES.length];
        for (int i = 0; i < MODES.length; i++) choices[i] = (i == selected ? "✓ " : "") + MODES[i] + "\n" + descriptions[i];
        builder.setItems(choices, (dialog, which) -> {
            prefs(activity).edit().putInt(MODE_KEY, which).apply();
            Toast.makeText(activity, "Modo Termux: " + MODES[which], Toast.LENGTH_SHORT).show();
        }).setNegativeButton("Cancelar", null).show();
    }

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
        int selectedMode = mode(activity);
        if (selectedMode == MODE_OFF) {
            Toast.makeText(activity, "Termux desativado. Selecione um modo para habilitar o encaminhamento.", Toast.LENGTH_LONG).show();
            return;
        }
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
            if (selectedMode == MODE_MODERATE && !isModerateCommand(command)) {
                Toast.makeText(activity, "Modo Moderado bloqueou o comando: use um comando curto de consulta da lista permitida ou escolha Completo.", Toast.LENGTH_LONG).show();
                return;
            }
            showReview(activity, command, selectedMode);
        } catch (Exception e) {
            Toast.makeText(activity, "Não foi possível ler o comando da resposta: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    private static boolean isModerateCommand(String command) {
        if (command == null || command.length() > 256 || command.indexOf('\n') >= 0 || command.indexOf('\r') >= 0) return false;
        return MODERATE_COMMAND.matcher(command.trim()).matches();
    }

    private static void showReview(Activity activity, String command, int selectedMode) {
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
            .setPositiveButton("Abrir no Termux", (d, which) -> {
                if (selectedMode == MODE_COMPLETE_AUTH) requireTypedAuthorization(activity, command);
                else confirmPermissionAndRun(activity, command);
            })
            .create();
        dialog.show();
    }

    private static void requireTypedAuthorization(Activity activity, String command) {
        EditText input = new EditText(activity);
        input.setSingleLine(true);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD);
        input.setHint(AUTH_PHRASE);
        input.setContentDescription("Digite AUTORIZO para confirmar este comando");
        new AlertDialog.Builder(activity).setTitle("Autorização explícita necessária")
            .setMessage("Revise o comando na tela anterior. Para cada encaminhamento neste modo, digite exatamente AUTORIZO. A permissão RUN_COMMAND do Android/Termux também será exigida.")
            .setView(input)
            .setNegativeButton("Cancelar", null)
            .setPositiveButton("Autorizar e abrir", (dialog, which) -> {
                if (AUTH_PHRASE.equals(input.getText().toString().trim())) confirmPermissionAndRun(activity, command);
                else Toast.makeText(activity, "Autorização não confirmada; comando não executado.", Toast.LENGTH_LONG).show();
            }).show();
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
