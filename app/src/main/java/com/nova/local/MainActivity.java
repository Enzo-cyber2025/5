package com.nova.local;

import android.Manifest;
import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.ClipData;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.inputmethod.EditorInfo;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity implements NovaView.Listener {
    private static final int PICK_MODELS = 2101;
    private static final int PICK_IMAGE = 2102;
    private static final String ACTION_PROGRESS = GenerationService.ACTION_PROGRESS;
    private static final String ACTION_RESULT = GenerationService.ACTION_RESULT;
    private static final String ACTION_ERROR = GenerationService.ACTION_ERROR;

    private FrameLayout root;
    private NovaView novaView;
    private EditText composer;
    private ModelStore modelStore;
    private ArrayList<ModelStore.ModelRef> models = new ArrayList<>();
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private String activeRequest;
    private String activeImageUri;
    private BroadcastReceiver receiver;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Window window = getWindow();
        window.setStatusBarColor(Color.rgb(11, 16, 24));
        window.setNavigationBarColor(Color.rgb(11, 16, 24));
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            window.getDecorView().setSystemUiVisibility(0);
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            WindowInsetsController controller = window.getInsetsController();
            if (controller != null) controller.setSystemBarsAppearance(0,
                    WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS
                            | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS);
        }

        modelStore = new ModelStore(this);
        root = new FrameLayout(this);
        novaView = new NovaView(this, this);
        root.addView(novaView, new FrameLayout.LayoutParams(-1, -1));
        composer = new EditText(this);
        composer.setTextColor(Color.rgb(241, 244, 252));
        composer.setHintTextColor(Color.rgb(116, 131, 155));
        composer.setHint("Escreva uma mensagem…");
        composer.setTextSize(14);
        composer.setGravity(Gravity.TOP | Gravity.START);
        composer.setSingleLine(false);
        composer.setMaxLines(3);
        composer.setInputType(android.text.InputType.TYPE_CLASS_TEXT
                | android.text.InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
                | android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE);
        composer.setImeOptions(EditorInfo.IME_ACTION_SEND);
        composer.setBackgroundColor(Color.TRANSPARENT);
        composer.setPadding(0, 0, 0, 0);
        composer.setOnEditorActionListener((v, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_SEND) {
                sendPrompt();
                return true;
            }
            return false;
        });
        root.addView(composer);
        setContentView(root);
        updateEditorLayout();

        receiver = new BroadcastReceiver() {
            @Override
            public void onReceive(Context context, Intent intent) {
                String requestId = intent.getStringExtra("request_id");
                if (activeRequest == null || !activeRequest.equals(requestId)) return;
                String action = intent.getAction();
                if (ACTION_PROGRESS.equals(action)) {
                    novaView.setGenerationState(true, intent.getStringExtra("message"));
                } else if (ACTION_RESULT.equals(action)) {
                    novaView.setGenerationState(false, "Pronto para conversar");
                    novaView.addAssistantMessage(intent.getStringExtra("answer"));
                    activeRequest = null;
                    composer.setEnabled(true);
                    composer.requestFocus();
                } else if (ACTION_ERROR.equals(action)) {
                    novaView.setGenerationState(false, "Geração interrompida");
                    novaView.addSystemMessage(intent.getStringExtra("message"));
                    activeRequest = null;
                    composer.setEnabled(true);
                }
            }
        };
        loadModels();
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 77);
        }
    }

    @Override
    protected void onStart() {
        super.onStart();
        IntentFilter filter = new IntentFilter();
        filter.addAction(ACTION_PROGRESS);
        filter.addAction(ACTION_RESULT);
        filter.addAction(ACTION_ERROR);
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(receiver, filter, RECEIVER_NOT_EXPORTED);
        else registerReceiver(receiver, filter);
    }

    @Override
    protected void onStop() {
        try { unregisterReceiver(receiver); } catch (Throwable ignored) { }
        super.onStop();
    }

    private void loadModels() {
        io.submit(() -> {
            ArrayList<ModelStore.ModelRef> loaded = modelStore.loadPersisted();
            runOnUiThread(() -> {
                models = loaded;
                novaView.setModels(models);
                updateEditorLayout();
            });
        });
    }

    @Override
    public void onAction(NovaView.Action action, int index) {
        switch (action) {
            case NEW_CHAT:
                novaView.newChat();
                composer.setText("");
                break;
            case IMPORT_MODELS:
                openModelPicker();
                break;
            case OPEN_IMAGE:
                openImagePicker();
                break;
            case SEND:
                sendPrompt();
                break;
            case CANCEL:
                GenerationService.cancel(this);
                novaView.setGenerationState(false, "Cancelando…");
                break;
            case SHOW_CHAT:
                novaView.showScreen(NovaView.Screen.CHAT);
                break;
            case SHOW_MODELS:
                novaView.showScreen(NovaView.Screen.MODELS);
                break;
            case SHOW_RESEARCH:
                novaView.showScreen(NovaView.Screen.RESEARCH);
                break;
            case SHOW_SETTINGS:
                novaView.showScreen(NovaView.Screen.SETTINGS);
                break;
            case TOGGLE_THINK:
                novaView.setThinking(!novaView.isThinking());
                break;
            case TOGGLE_RESEARCH:
                novaView.setResearch(!novaView.isResearch());
                break;
            case TOGGLE_VISION:
                if (activeModel() != null && !activeModel().vision) {
                    toast("Visão precisa de um GGUF multimodal + mmproj.");
                } else novaView.setVision(!novaView.isThinking());
                break;
            case SELECT_MODEL:
                if (index >= 0 && index < models.size()) {
                    novaView.setActiveModel(index);
                    novaView.showScreen(NovaView.Screen.CHAT);
                    toast("Modelo ativo: " + models.get(index).shortName());
                }
                break;
            case REMOVE_MODEL:
                break;
        }
        updateEditorLayout();
    }

    private void openModelPicker() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("*/*");
        intent.putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"application/octet-stream", "application/*", "*/*"});
        intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
        try { startActivityForResult(intent, PICK_MODELS); }
        catch (Throwable error) { toast("Não foi possível abrir o seletor de arquivos."); }
    }

    private void openImagePicker() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("image/*");
        try { startActivityForResult(intent, PICK_IMAGE); }
        catch (Throwable error) { toast("Não foi possível abrir o seletor de imagens."); }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (resultCode != RESULT_OK || data == null) return;
        if (requestCode == PICK_IMAGE) {
            Uri uri = data.getData();
            if (uri != null) {
                try {
                    getContentResolver().takePersistableUriPermission(uri,
                            Intent.FLAG_GRANT_READ_URI_PERMISSION);
                } catch (Throwable ignored) { }
                activeImageUri = uri.toString();
                String name = uri.getLastPathSegment();
                novaView.setAttachedImage(name == null ? "imagem" : name);
            }
            return;
        }
        if (requestCode == PICK_MODELS) {
            ArrayList<Uri> selected = new ArrayList<>();
            ClipData clipData = data.getClipData();
            if (clipData != null) {
                for (int i = 0; i < clipData.getItemCount(); i++) selected.add(clipData.getItemAt(i).getUri());
            } else if (data.getData() != null) selected.add(data.getData());
            if (selected.isEmpty()) return;
            io.submit(() -> {
                int accepted = 0;
                for (Uri uri : selected) {
                    if (models.size() + accepted >= 2) break;
                    try {
                        getContentResolver().takePersistableUriPermission(uri,
                                Intent.FLAG_GRANT_READ_URI_PERMISSION);
                    } catch (Throwable ignored) { }
                    ModelStore.ModelRef ref = modelStore.inspect(uri, "modelo.gguf");
                    if (ref != null && modelStore.add(ref)) accepted++;
                }
                ArrayList<ModelStore.ModelRef> refreshed = modelStore.all();
                runOnUiThread(() -> {
                    models = refreshed;
                    novaView.setModels(models);
                    novaView.showScreen(NovaView.Screen.MODELS);
                    toast(accepted == 0 ? "Nenhum GGUF novo foi importado." : accepted + " GGUF importado(s) por referência.");
                });
            });
        }
    }

    private void sendPrompt() {
        if (activeRequest != null) {
            toast("Uma geração já está em andamento.");
            return;
        }
        String text = composer.getText() == null ? "" : composer.getText().toString().trim();
        if (text.isEmpty() && activeImageUri == null) return;
        ModelStore.ModelRef active = activeModel();
        if (active == null) {
            toast("Importe um GGUF primeiro.");
            novaView.showScreen(NovaView.Screen.MODELS);
            return;
        }
        if (active.projector) {
            toast("Selecione o modelo de linguagem, não o mmproj.");
            return;
        }
        String imageForRequest = activeImageUri;
        String userText = text.isEmpty() ? "Descreva a imagem anexada com detalhes." : text;
        boolean think = novaView.isThinking();
        boolean useResearch = novaView.isResearch();
        novaView.addUserMessage(userText);
        composer.setText("");
        composer.setEnabled(false);

        String prompt = buildPrompt(userText, think, imageForRequest != null);
        ModelStore.ModelRef projector = modelStore.projectorFor(active);
        activeRequest = UUID.randomUUID().toString();
        novaView.setGenerationState(true, "Enfileirando geração local…");
        GenerationService.start(this, activeRequest, active.uri,
                projector == null ? null : projector.uri, prompt, userText,
                useResearch, imageForRequest);
        activeImageUri = null;
        novaView.clearAttachedImage();
    }

    private String buildPrompt(String current, boolean think, boolean image) {
        StringBuilder prompt = new StringBuilder();
        prompt.append("Você é Nova, uma assistente local útil, precisa e direta. Responda em português do Brasil. ");
        prompt.append("Não invente fontes nem diga que executou ações que não executou.\n");
        if (think) prompt.append("Analise o problema com cuidado em silêncio; entregue somente a resposta final bem organizada.\n");
        if (image) prompt.append("Há uma imagem anexada. Use a entrada visual quando o pipeline multimodal estiver disponível.\n");
        prompt.append("\nHISTÓRICO DA CONVERSA:\n");
        int end = Math.max(0, novaView.getCurrentChat().messages.size() - 1);
        int start = Math.max(0, end - 8);
        for (int i = start; i < end; i++) {
            NovaView.Message message = novaView.getCurrentChat().messages.get(i);
            prompt.append(message.user ? "Usuário: " : "Assistente: ").append(message.text).append("\n");
        }
        prompt.append("\nUsuário: ").append(current).append("\nAssistente:");
        return prompt.toString();
    }

    private ModelStore.ModelRef activeModel() {
        return novaView.getActiveModel();
    }

    @Override
    public void onEditorLayoutChanged() {
        if (root != null) root.post(this::updateEditorLayout);
    }

    private void updateEditorLayout() {
        if (root == null || composer == null || novaView == null) return;
        boolean visible = novaView.isChatScreen();
        composer.setVisibility(visible ? View.VISIBLE : View.GONE);
        if (!visible) return;
        FrameLayout.LayoutParams params = new FrameLayout.LayoutParams(
                novaView.editorWidth(), novaView.editorHeight());
        params.leftMargin = novaView.editorLeft();
        params.topMargin = novaView.editorTop();
        root.removeView(composer);
        root.addView(composer, params);
        composer.bringToFront();
    }

    private void toast(String message) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show();
    }

    @Override
    protected void onDestroy() {
        io.shutdownNow();
        super.onDestroy();
    }
}
