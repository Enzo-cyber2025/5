package ai.arena.ggufchat;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.graphics.Color;
import android.net.Uri;
import android.os.*;
import android.provider.OpenableColumns;
import android.text.*;
import android.view.*;
import android.view.inputmethod.InputMethodManager;
import android.widget.*;
import java.io.*;
import java.util.*;

public class MainActivity extends Activity {
    private static final int PICK_MODEL_A = 101;
    private static final int PICK_MODEL_B = 102;
    private final ArrayList<String> messages = new ArrayList<>();
    private LinearLayout transcript;
    private TextView modelAView, modelBView, statusView, chatTitle;
    private EditText prompt;
    private CheckBox thinkingBox, searchBox, lockBox;
    private SharedPreferences prefs;
    private String chatId = "Chat 1";
    private final BroadcastReceiver receiver = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            if (GenerationService.ACTION_DONE.equals(intent.getAction())) {
                append("Assistente", intent.getStringExtra(GenerationService.EXTRA_RESULT));
                saveChat();
            }
        }
    };

    @Override public void onCreate(Bundle b) {
        super.onCreate(b);
        prefs = getSharedPreferences("ggufchat", MODE_PRIVATE);
        chatId = prefs.getString("activeChat", "Chat 1");
        buildUi();
        loadChat();
        refreshModels();
        refreshStatus();
        if (Build.VERSION.SDK_INT >= 33) requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 9);
    }

    @Override protected void onResume() {
        super.onResume();
        IntentFilter f = new IntentFilter(GenerationService.ACTION_DONE);
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(receiver, f, RECEIVER_NOT_EXPORTED); else registerReceiver(receiver, f);
    }
    @Override protected void onPause() { try { unregisterReceiver(receiver); } catch (Throwable ignored) {} super.onPause(); }

    private void buildUi() {
        int bg = Color.rgb(13, 20, 33), panel = Color.rgb(25, 35, 55), text = Color.WHITE, accent = Color.rgb(105, 155, 255);
        LinearLayout root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL); root.setBackgroundColor(bg);
        setContentView(root);

        LinearLayout top = new LinearLayout(this); top.setOrientation(LinearLayout.HORIZONTAL); top.setPadding(dp(14), dp(10), dp(14), dp(8)); top.setGravity(Gravity.CENTER_VERTICAL); top.setBackgroundColor(Color.rgb(16, 24, 39));
        chatTitle = label(chatId, 20, true); LinearLayout.LayoutParams titleLp = new LinearLayout.LayoutParams(0, -2, 1); top.addView(chatTitle, titleLp);
        Button newChat = button("+ Chat"); newChat.setOnClickListener(v -> createChat()); top.addView(newChat);
        Button switchChat = button("Trocar"); switchChat.setOnClickListener(v -> switchChat()); top.addView(switchChat);
        root.addView(top);

        HorizontalScrollView hs = new HorizontalScrollView(this); LinearLayout chips = new LinearLayout(this); chips.setPadding(dp(10), dp(8), dp(10), dp(8)); chips.setOrientation(LinearLayout.HORIZONTAL); hs.addView(chips);
        Button importA = button("Importar GGUF 1"); importA.setOnClickListener(v -> pick(PICK_MODEL_A)); chips.addView(importA);
        Button importB = button("Importar GGUF 2 multimodal"); importB.setOnClickListener(v -> pick(PICK_MODEL_B)); chips.addView(importB);
        Button inspect = button("Inspecionar memória/Vulkan"); inspect.setOnClickListener(v -> inspectModels()); chips.addView(inspect);
        Button web = button("Pesquisa web"); web.setOnClickListener(v -> openSearch()); chips.addView(web);
        root.addView(hs);

        LinearLayout modelPanel = card(panel); modelPanel.setOrientation(LinearLayout.VERTICAL);
        modelAView = small("Modelo 1: nenhum"); modelBView = small("Modelo 2: nenhum"); statusView = small("Inicializando…");
        modelPanel.addView(modelAView); modelPanel.addView(modelBView); modelPanel.addView(statusView); root.addView(modelPanel);

        ScrollView scroll = new ScrollView(this); transcript = new LinearLayout(this); transcript.setPadding(dp(12), dp(12), dp(12), dp(12)); transcript.setOrientation(LinearLayout.VERTICAL); scroll.addView(transcript); root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));

        LinearLayout toggles = new LinearLayout(this); toggles.setOrientation(LinearLayout.HORIZONTAL); toggles.setPadding(dp(10), 0, dp(10), 0);
        thinkingBox = check("Thinking", true); searchBox = check("Pesquisa", false); lockBox = check("Tela bloqueada", true);
        toggles.addView(thinkingBox); toggles.addView(searchBox); toggles.addView(lockBox); root.addView(toggles);

        LinearLayout bottom = new LinearLayout(this); bottom.setPadding(dp(10), dp(8), dp(10), dp(10)); bottom.setGravity(Gravity.BOTTOM); bottom.setOrientation(LinearLayout.HORIZONTAL);
        prompt = new EditText(this); prompt.setHint("Digite sua mensagem…"); prompt.setHintTextColor(Color.rgb(160, 170, 190)); prompt.setTextColor(text); prompt.setMinLines(1); prompt.setMaxLines(5); prompt.setBackgroundColor(Color.rgb(20, 30, 48)); prompt.setPadding(dp(12), 0, dp(12), 0);
        bottom.addView(prompt, new LinearLayout.LayoutParams(0, dp(52), 1)); Button send = button("Enviar"); send.setTextColor(Color.WHITE); send.setOnClickListener(v -> send()); bottom.addView(send, new LinearLayout.LayoutParams(dp(104), dp(52))); root.addView(bottom);
    }

    private void pick(int code) {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT); i.addCategory(Intent.CATEGORY_OPENABLE); i.setType("*/*"); i.putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"application/octet-stream", "application/x-gguf", "*/*"}); startActivityForResult(i, code);
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (result == RESULT_OK && data != null && data.getData() != null) {
            Uri u = data.getData(); final int flags = data.getFlags() & (Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
            try { getContentResolver().takePersistableUriPermission(u, flags); } catch (Throwable ignored) {}
            String key = request == PICK_MODEL_A ? "modelA" : "modelB";
            String nameKey = request == PICK_MODEL_A ? "modelAName" : "modelBName";
            prefs.edit().putString(key, u.toString()).putString(nameKey, displayName(u)).apply();
            refreshModels(); inspectModels();
        }
    }

    private void send() {
        String p = prompt.getText().toString().trim(); if (p.isEmpty()) return;
        append("Você", p); prompt.setText(""); saveChat(); hideKeyboard();
        String a = prefs.getString("modelAName", "GGUF 1 não selecionado"); String b = prefs.getString("modelBName", "GGUF 2 não selecionado");
        if (lockBox.isChecked()) {
            Intent svc = new Intent(this, GenerationService.class).setAction(GenerationService.ACTION_GENERATE)
                    .putExtra(GenerationService.EXTRA_PROMPT, p).putExtra(GenerationService.EXTRA_MODEL_A, a).putExtra(GenerationService.EXTRA_MODEL_B, b)
                    .putExtra(GenerationService.EXTRA_THINKING, thinkingBox.isChecked()).putExtra(GenerationService.EXTRA_SEARCH, searchBox.isChecked());
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(svc); else startService(svc);
            Toast.makeText(this, "Gerando em foreground service; pode bloquear a tela.", Toast.LENGTH_LONG).show();
        } else {
            append("Assistente", NativeBridge.draftAnswer(p, a, b, thinkingBox.isChecked(), searchBox.isChecked())); saveChat();
        }
    }

    private void inspectModels() {
        StringBuilder sb = new StringBuilder(); sb.append(NativeBridge.nativeInfo()).append('\n');
        inspectOne("modelA", "modelAName", sb); inspectOne("modelB", "modelBName", sb); statusView.setText(sb.toString());
    }
    private void inspectOne(String key, String nameKey, StringBuilder sb) {
        String s = prefs.getString(key, null); if (s == null) return;
        try (android.os.ParcelFileDescriptor pfd = getContentResolver().openFileDescriptor(Uri.parse(s), "r")) {
            long size = pfd.getStatSize(); sb.append(NativeBridge.inspectFd(pfd.getFd(), size, prefs.getString(nameKey, key))).append('\n');
        } catch (Throwable t) { sb.append(prefs.getString(nameKey, key)).append(": erro ").append(t.getMessage()).append('\n'); }
    }
    private void openSearch() {
        String q = prompt.getText().toString().trim(); if (q.isEmpty()) q = "GGUF Vulkan Android multimodal";
        startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse("https://www.google.com/search?q=" + Uri.encode(q))));
    }
    private void createChat() {
        saveChat(); int n = prefs.getInt("chatCount", 1) + 1; prefs.edit().putInt("chatCount", n).putString("activeChat", "Chat " + n).apply(); chatId = "Chat " + n; messages.clear(); transcript.removeAllViews(); chatTitle.setText(chatId);
    }
    private void switchChat() {
        int count = prefs.getInt("chatCount", 1); final String[] items = new String[count]; for (int i=0;i<count;i++) items[i] = "Chat " + (i+1);
        new AlertDialog.Builder(this).setTitle("Escolha o chat").setItems(items, (d, which) -> { saveChat(); chatId = items[which]; prefs.edit().putString("activeChat", chatId).apply(); chatTitle.setText(chatId); loadChat(); }).show();
    }
    private void append(String who, String body) { messages.add(who + "\n" + body); TextView v = label(who + "\n" + body, 15, false); v.setPadding(dp(12), dp(10), dp(12), dp(10)); v.setBackgroundColor(who.equals("Você") ? Color.rgb(31, 55, 93) : Color.rgb(32, 43, 65)); LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2); lp.setMargins(0, 0, 0, dp(10)); transcript.addView(v, lp); }
    private void saveChat() { prefs.edit().putString("chat:" + chatId, TextUtils.join("\u001e", messages)).apply(); }
    private void loadChat() { if (transcript == null) return; transcript.removeAllViews(); messages.clear(); String raw = prefs.getString("chat:" + chatId, ""); if (!raw.isEmpty()) for (String m: raw.split("\u001e", -1)) { int i=m.indexOf('\n'); if (i>0) append(m.substring(0,i), m.substring(i+1)); } }
    private void refreshModels() { modelAView.setText("Modelo 1: " + prefs.getString("modelAName", "nenhum")); modelBView.setText("Modelo 2 multimodal: " + prefs.getString("modelBName", "nenhum")); }
    private void refreshStatus() { statusView.setText(NativeBridge.nativeInfo()); }
    private String displayName(Uri uri) { try (Cursor c = getContentResolver().query(uri, null, null, null, null)) { if (c != null && c.moveToFirst()) { int ix = c.getColumnIndex(OpenableColumns.DISPLAY_NAME); if (ix >= 0) return c.getString(ix); } } catch (Throwable ignored) {} return uri.getLastPathSegment(); }
    private TextView label(String s, int sp, boolean bold) { TextView v = new TextView(this); v.setText(s); v.setTextColor(Color.WHITE); v.setTextSize(sp); if (bold) v.setTypeface(android.graphics.Typeface.DEFAULT_BOLD); return v; }
    private TextView small(String s) { TextView v = label(s, 13, false); v.setTextColor(Color.rgb(205, 215, 235)); v.setPadding(0, dp(2),0,dp(2)); return v; }
    private Button button(String s) { Button b = new Button(this); b.setText(s); b.setAllCaps(false); return b; }
    private CheckBox check(String s, boolean checked) { CheckBox c = new CheckBox(this); c.setText(s); c.setTextColor(Color.WHITE); c.setChecked(checked); return c; }
    private LinearLayout card(int color) { LinearLayout l = new LinearLayout(this); l.setPadding(dp(12), dp(8), dp(12), dp(8)); l.setBackgroundColor(color); return l; }
    private int dp(int v) { return (int)(v * getResources().getDisplayMetrics().density + 0.5f); }
    private void hideKeyboard() { try { ((InputMethodManager)getSystemService(INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(prompt.getWindowToken(), 0); } catch (Throwable ignored) {} }
}
