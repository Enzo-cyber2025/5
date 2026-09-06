package com.nova.local;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.view.MotionEvent;
import android.view.View;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/** A lightweight canvas UI so the APK has no UI framework dependency on top of Android. */
public final class NovaView extends View {
    public enum Screen { CHAT, MODELS, RESEARCH, SETTINGS }
    public enum Action { NEW_CHAT, IMPORT_MODELS, OPEN_IMAGE, SEND, CANCEL,
        SHOW_CHAT, SHOW_MODELS, SHOW_RESEARCH, SHOW_SETTINGS, TOGGLE_THINK,
        TOGGLE_RESEARCH, TOGGLE_VISION, SELECT_MODEL, REMOVE_MODEL }

    public interface Listener {
        void onAction(Action action, int index);
        void onEditorLayoutChanged();
    }

    public static final class Message {
        public final boolean user;
        public final String text;
        public final boolean thinking;
        public final boolean researched;
        public final String imageLabel;
        public final long timestamp;
        public boolean streaming;

        Message(boolean user, String text, boolean thinking, boolean researched, String imageLabel) {
            this.user = user;
            this.text = text == null ? "" : text;
            this.thinking = thinking;
            this.researched = researched;
            this.imageLabel = imageLabel;
            this.timestamp = System.currentTimeMillis();
        }
    }

    public static final class Chat {
        public String title;
        public final ArrayList<Message> messages = new ArrayList<>();
        public Chat(String title) { this.title = title; }
    }

    private static final int BG = Color.rgb(11, 16, 24);
    private static final int SIDEBAR = Color.rgb(16, 23, 36);
    private static final int SURFACE = Color.rgb(20, 30, 47);
    private static final int SURFACE_2 = Color.rgb(25, 36, 55);
    private static final int LINE = Color.rgb(38, 50, 72);
    private static final int TEXT = Color.rgb(241, 244, 252);
    private static final int MUTED = Color.rgb(135, 148, 171);
    private static final int DIM = Color.rgb(91, 105, 130);
    private static final int PURPLE = Color.rgb(137, 120, 255);
    private static final int TEAL = Color.rgb(83, 223, 189);
    private static final int ORANGE = Color.rgb(244, 176, 98);

    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint stroke = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF rect = new RectF();
    private final float density;
    private final Listener listener;
    private final ArrayList<Chat> chats = new ArrayList<>();
    private ArrayList<ModelStore.ModelRef> models = new ArrayList<>();
    private Screen screen = Screen.CHAT;
    private Chat currentChat;
    private int activeModel = 0;
    private boolean thinking = true;
    private boolean research;
    private boolean vision;
    private boolean generating;
    private String generationStatus = "Pronto para conversar";
    private String attachedImageName;
    private float scrollY;
    private float downX;
    private float downY;
    private boolean moved;

    public NovaView(Context context, Listener listener) {
        super(context);
        this.listener = listener;
        density = getResources().getDisplayMetrics().density;
        setFocusable(true);
        paint.setTypeface(Typeface.create("sans-serif", Typeface.NORMAL));
        stroke.setStyle(Paint.Style.STROKE);
        stroke.setStrokeWidth(dp(1));
        stroke.setStrokeCap(Paint.Cap.ROUND);
        currentChat = new Chat("Nova conversa");
        chats.add(currentChat);
    }

    public float dp(float value) { return value * density; }

    public Screen getScreen() { return screen; }
    public boolean isChatScreen() { return screen == Screen.CHAT; }
    public Chat getCurrentChat() { return currentChat; }
    public boolean isThinking() { return thinking; }
    public boolean isResearch() { return research; }
    public boolean isVisionEnabled() { return vision; }
    public String getAttachedImageName() { return attachedImageName; }
    public boolean isGenerating() { return generating; }
    public int getActiveModelIndex() { return activeModel; }

    public void setModels(ArrayList<ModelStore.ModelRef> refs) {
        models = refs == null ? new ArrayList<>() : refs;
        if (activeModel >= models.size()) activeModel = Math.max(0, models.size() - 1);
        invalidate();
    }

    public void setActiveModel(int index) {
        if (index >= 0 && index < models.size()) activeModel = index;
        invalidate();
    }

    public ModelStore.ModelRef getActiveModel() {
        return activeModel >= 0 && activeModel < models.size() ? models.get(activeModel) : null;
    }

    public void setGenerationState(boolean value, String status) {
        generating = value;
        if (status != null) generationStatus = status;
        invalidate();
    }

    public void setAttachedImage(String name) {
        attachedImageName = name;
        vision = true;
        invalidate();
    }

    public void clearAttachedImage() {
        attachedImageName = null;
        invalidate();
    }

    public void addUserMessage(String text) {
        if (text == null || text.trim().isEmpty()) return;
        if (currentChat.messages.isEmpty() || currentChat.title.equals("Nova conversa")) {
            currentChat.title = text.trim().length() > 28 ? text.trim().substring(0, 28) + "…" : text.trim();
        }
        currentChat.messages.add(new Message(true, text.trim(), thinking, research, attachedImageName));
        attachedImageName = null;
        scrollToBottom();
        invalidate();
    }

    public void addAssistantMessage(String text) {
        Message message = new Message(false, text, false, false, null);
        currentChat.messages.add(message);
        scrollToBottom();
        invalidate();
    }

    public void addSystemMessage(String text) {
        currentChat.messages.add(new Message(false, text, false, false, null));
        scrollToBottom();
        invalidate();
    }

    public void newChat() {
        currentChat = new Chat("Nova conversa");
        chats.add(0, currentChat);
        screen = Screen.CHAT;
        scrollY = 0;
        invalidate();
        if (listener != null) listener.onEditorLayoutChanged();
    }

    public void showScreen(Screen next) {
        screen = next;
        invalidate();
        if (listener != null) listener.onEditorLayoutChanged();
    }

    public void setResearch(boolean value) { research = value; invalidate(); }
    public void setThinking(boolean value) { thinking = value; invalidate(); }
    public void setVision(boolean value) { vision = value; invalidate(); }

    public int editorLeft() { return Math.round(mainLeft() + dp(86)); }
    public int editorTop() { return Math.round(getHeight() - dp(111)); }
    public int editorWidth() { return Math.max(80, Math.round(getWidth() - mainLeft() - dp(206))); }
    public int editorHeight() { return Math.round(dp(58)); }

    private float sideWidth() {
        return getWidth() / density < 760 ? dp(72) : dp(258);
    }

    private float mainLeft() { return sideWidth(); }

    @Override
    protected void onSizeChanged(int w, int h, int oldw, int oldh) {
        super.onSizeChanged(w, h, oldw, oldh);
        if (listener != null) listener.onEditorLayoutChanged();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        canvas.drawColor(BG);
        drawSidebar(canvas);
        if (screen == Screen.CHAT) drawChat(canvas);
        else if (screen == Screen.MODELS) drawModels(canvas);
        else if (screen == Screen.RESEARCH) drawResearch(canvas);
        else drawSettings(canvas);
    }

    private void drawSidebar(Canvas canvas) {
        float sw = sideWidth();
        paint.setColor(SIDEBAR);
        canvas.drawRect(0, 0, sw, getHeight(), paint);
        paint.setColor(LINE);
        canvas.drawRect(sw - dp(1), 0, sw, getHeight(), paint);

        // mark
        paint.setColor(PURPLE);
        canvas.drawCircle(dp(28), dp(31), dp(12), paint);
        paint.setColor(SIDEBAR);
        canvas.drawCircle(dp(28), dp(31), dp(7), paint);
        paint.setColor(TEAL);
        canvas.drawCircle(dp(34), dp(25), dp(3), paint);
        if (sw > dp(100)) {
            text(canvas, "NOVA", dp(52), dp(29), 16, TEXT, true);
            text(canvas, "LOCAL AI", dp(52), dp(46), 9, MUTED, true);
        }

        round(canvas, dp(14), dp(70), sw - dp(14), dp(116), dp(12), PURPLE);
        drawPlus(canvas, dp(31), dp(93), TEXT);
        if (sw > dp(100)) text(canvas, "Nova conversa", dp(52), dp(99), 13, TEXT, true);

        float navY = dp(150);
        navItem(canvas, navY, "Chats", 0, screen == Screen.CHAT);
        navItem(canvas, navY + dp(48), "Modelos", 1, screen == Screen.MODELS);
        navItem(canvas, navY + dp(96), "Pesquisa", 2, screen == Screen.RESEARCH);
        navItem(canvas, navY + dp(144), "Ajustes", 3, screen == Screen.SETTINGS);

        if (sw > dp(100) && screen == Screen.CHAT) {
            text(canvas, "CONVERSAS", dp(18), dp(350), 10, DIM, true);
            float y = dp(378);
            int shown = 0;
            for (int i = 0; i < chats.size() && shown < 5; i++) {
                Chat chat = chats.get(i);
                boolean selected = chat == currentChat;
                if (selected) round(canvas, dp(10), y - dp(22), sw - dp(10), y + dp(12), dp(9), SURFACE_2);
                drawChatBubbleIcon(canvas, dp(25), y - dp(5), selected ? PURPLE : DIM);
                text(canvas, chat.title, dp(43), y, 12, selected ? TEXT : MUTED, selected);
                y += dp(39);
                shown++;
            }
        }

        float bottom = getHeight() - dp(46);
        drawStatusDot(canvas, dp(24), bottom - dp(1), models.size() > 0 ? TEAL : ORANGE);
        if (sw > dp(100)) {
            text(canvas, models.size() > 0 ? "Modelos locais prontos" : "Nenhum modelo importado",
                    dp(41), bottom + dp(3), 10, MUTED, false);
        }
    }

    private void navItem(Canvas canvas, float y, String label, int icon, boolean selected) {
        float sw = sideWidth();
        if (selected) round(canvas, dp(10), y - dp(18), sw - dp(10), y + dp(17), dp(9), SURFACE_2);
        drawNavIcon(canvas, dp(30), y, icon, selected ? PURPLE : DIM);
        if (sw > dp(100)) text(canvas, label, dp(53), y + dp(4), 12, selected ? TEXT : MUTED, selected);
    }

    private void drawChat(Canvas canvas) {
        float left = mainLeft();
        drawTopBar(canvas, "Conversa local", "Privacidade por padrão");
        if (currentChat.messages.isEmpty()) drawEmptyState(canvas);
        else drawMessages(canvas);
        drawComposer(canvas);
    }

    private void drawTopBar(Canvas canvas, String title, String subtitle) {
        float left = mainLeft();
        paint.setColor(BG);
        canvas.drawRect(left, 0, getWidth(), dp(78), paint);
        paint.setColor(LINE);
        canvas.drawRect(left, dp(77), getWidth(), dp(78), paint);
        text(canvas, title, left + dp(28), dp(32), 17, TEXT, true);
        text(canvas, subtitle, left + dp(28), dp(53), 11, MUTED, false);

        ModelStore.ModelRef active = getActiveModel();
        float badgeLeft = getWidth() - dp(active == null ? 190 : 238);
        round(canvas, badgeLeft, dp(20), getWidth() - dp(22), dp(56), dp(18), SURFACE);
        drawStatusDot(canvas, badgeLeft + dp(17), dp(38), active == null ? ORANGE : TEAL);
        if (active == null) {
            text(canvas, "Importe um GGUF", badgeLeft + dp(31), dp(43), 11, MUTED, true);
        } else {
            text(canvas, active.shortName(), badgeLeft + dp(30), dp(38), 11, TEXT, true);
            text(canvas, active.vision ? "multimodal · mmap" : "GGUF · mmap", badgeLeft + dp(30), dp(51), 9, MUTED, false);
        }
    }

    private void drawEmptyState(Canvas canvas) {
        float left = mainLeft();
        float centerX = left + (getWidth() - left) / 2f;
        float centerY = getHeight() / 2f - dp(56);
        paint.setColor(Color.rgb(35, 36, 73));
        canvas.drawCircle(centerX, centerY, dp(50), paint);
        paint.setColor(Color.rgb(86, 73, 170));
        canvas.drawCircle(centerX, centerY, dp(37), paint);
        paint.setColor(TEAL);
        Path path = new Path();
        path.moveTo(centerX - dp(15), centerY - dp(18));
        path.lineTo(centerX - dp(4), centerY - dp(18));
        path.lineTo(centerX + dp(15), centerY + dp(7));
        path.lineTo(centerX + dp(15), centerY - dp(18));
        path.lineTo(centerX + dp(21), centerY - dp(18));
        path.lineTo(centerX + dp(21), centerY + dp(21));
        path.lineTo(centerX + dp(10), centerY + dp(21));
        path.lineTo(centerX - dp(9), centerY - dp(4));
        path.lineTo(centerX - dp(9), centerY + dp(21));
        path.lineTo(centerX - dp(15), centerY + dp(21));
        path.close();
        canvas.drawPath(path, paint);
        textCentered(canvas, "Conversa privada, no seu aparelho", centerX, centerY + dp(91), 19, TEXT, true);
        textCentered(canvas, models.isEmpty()
                ? "Importe um GGUF para começar. Os bytes ficam onde você escolheu."
                : "Pergunte qualquer coisa ao seu modelo local.", centerX,
                centerY + dp(120), 12, MUTED, false);
        if (models.isEmpty()) {
            round(canvas, centerX - dp(82), centerY + dp(145), centerX + dp(82), centerY + dp(184), dp(12), PURPLE);
            drawPlus(canvas, centerX - dp(57), centerY + dp(164), TEXT);
            textCentered(canvas, "Importar GGUF", centerX + dp(10), centerY + dp(169), 12, TEXT, true);
        }
    }

    private void drawMessages(Canvas canvas) {
        float left = mainLeft();
        float top = dp(95);
        float bottom = getHeight() - dp(180);
        canvas.save();
        canvas.clipRect(left, dp(80), getWidth(), bottom);
        canvas.translate(0, -scrollY);
        float y = top;
        for (Message message : currentChat.messages) {
            y = drawMessage(canvas, message, y);
            y += dp(24);
        }
        if (generating) {
            float x = left + dp(34);
            drawStatusDot(canvas, x, y + dp(3), TEAL);
            text(canvas, generationStatus, x + dp(16), y + dp(7), 12, MUTED, false);
            drawLoader(canvas, x + dp(16), y + dp(27));
        }
        canvas.restore();
    }

    private float drawMessage(Canvas canvas, Message message, float y) {
        float left = mainLeft();
        float maxWidth = Math.min(dp(650), getWidth() - left - dp(70));
        if (message.user) {
            float right = getWidth() - dp(28);
            ArrayList<String> lines = wrap(message.text, 13, maxWidth - dp(30));
            float height = dp(25) + lines.size() * dp(19);
            if (message.imageLabel != null) height += dp(28);
            round(canvas, right - maxWidth, y, right, y + height, dp(16), SURFACE_2);
            float textY = y + dp(25);
            if (message.imageLabel != null) {
                drawImageIcon(canvas, right - maxWidth + dp(18), y + dp(18), TEAL);
                text(canvas, "imagem anexada", right - maxWidth + dp(35), y + dp(22), 10, TEAL, true);
                textY += dp(24);
            }
            for (String line : lines) {
                text(canvas, line, right - maxWidth + dp(16), textY, 13, TEXT, false);
                textY += dp(19);
            }
            return y + height;
        }

        drawAssistantMark(canvas, left + dp(28), y + dp(14));
        float textX = left + dp(57);
        ArrayList<String> lines = wrap(message.text, 13, Math.min(dp(680), getWidth() - textX - dp(32)));
        float textY = y + dp(17);
        for (String line : lines) {
            text(canvas, line, textX, textY, 13, TEXT, false);
            textY += dp(20);
        }
        float metaY = textY + dp(3);
        if (message.thinking || message.researched) {
            if (message.thinking) {
                chip(canvas, textX, metaY, "ANÁLISE PRIVADA", PURPLE);
                textX += dp(109);
            }
            if (message.researched) chip(canvas, textX, metaY, "FONTES AO VIVO", TEAL);
            metaY += dp(23);
        }
        return Math.max(y + dp(38), metaY);
    }

    private void drawComposer(Canvas canvas) {
        float left = mainLeft();
        float top = getHeight() - dp(151);
        paint.setColor(BG);
        canvas.drawRect(left, top - dp(14), getWidth(), getHeight(), paint);
        paint.setColor(LINE);
        canvas.drawRect(left, top - dp(14), getWidth(), top - dp(13), paint);

        round(canvas, left + dp(18), top, getWidth() - dp(18), getHeight() - dp(19), dp(17), SURFACE);
        stroke.setColor(LINE);
        stroke.setStrokeWidth(dp(1));
        canvas.drawRoundRect(left + dp(18), top, getWidth() - dp(18), getHeight() - dp(19), dp(17), dp(17), stroke);
        drawPlus(canvas, left + dp(43), top + dp(30), MUTED);
        drawToolChip(canvas, left + dp(65), top + dp(12), "Pensar", thinking, PURPLE, 69);
        drawToolChip(canvas, left + dp(140), top + dp(12), "Pesquisar", research, TEAL, 84);
        drawToolChip(canvas, left + dp(230), top + dp(12), "Visão", vision, ORANGE, 64);
        if (attachedImageName != null) {
            text(canvas, "• " + (attachedImageName.length() > 25 ? attachedImageName.substring(0, 22) + "…" : attachedImageName),
                    left + dp(310), top + dp(28), 10, TEAL, false);
        }
        float sendX = getWidth() - dp(54);
        paint.setColor(generating ? DIM : PURPLE);
        canvas.drawCircle(sendX, getHeight() - dp(48), dp(18), paint);
        if (generating) drawStop(canvas, sendX, getHeight() - dp(48), TEXT);
        else drawArrow(canvas, sendX, getHeight() - dp(48), TEXT);
    }

    private void drawModels(Canvas canvas) {
        float left = mainLeft();
        drawTopBar(canvas, "Modelos locais", "GGUF · mmap · escolha até dois arquivos");
        round(canvas, getWidth() - dp(190), dp(92), getWidth() - dp(25), dp(130), dp(10), PURPLE);
        drawPlus(canvas, getWidth() - dp(169), dp(111), TEXT);
        text(canvas, "Importar GGUF", getWidth() - dp(151), dp(116), 11, TEXT, true);
        text(canvas, "Biblioteca", left + dp(28), dp(118), 13, MUTED, true);

        if (models.isEmpty()) {
            round(canvas, left + dp(28), dp(151), getWidth() - dp(28), dp(278), dp(16), SURFACE);
            drawDatabase(canvas, left + dp(62), dp(207), DIM);
            text(canvas, "Nenhum modelo importado", left + dp(105), dp(202), 15, TEXT, true);
            text(canvas, "Selecione um ou dois .gguf pelo armazenamento.", left + dp(105), dp(226), 11, MUTED, false);
            text(canvas, "A referência é persistida; o arquivo não é copiado.", left + dp(105), dp(246), 11, MUTED, false);
        } else {
            float y = dp(151);
            for (int i = 0; i < models.size(); i++) {
                ModelStore.ModelRef model = models.get(i);
                boolean active = i == activeModel;
                round(canvas, left + dp(28), y, getWidth() - dp(28), y + dp(112), dp(16), active ? SURFACE_2 : SURFACE);
                if (active) {
                    paint.setColor(PURPLE);
                    canvas.drawRoundRect(left + dp(28), y, left + dp(32), y + dp(112), dp(2), dp(2), paint);
                }
                drawModelGlyph(canvas, left + dp(66), y + dp(38), model.vision ? TEAL : PURPLE);
                text(canvas, model.shortName(), left + dp(103), y + dp(34), 14, TEXT, true);
                text(canvas, model.arch.isEmpty() ? "arquitetura detectada ao carregar" : model.arch,
                        left + dp(103), y + dp(56), 10, MUTED, false);
                chip(canvas, left + dp(103), y + dp(69), model.projector ? "MMProj" : (model.vision ? "Multimodal" : "Texto"),
                        model.vision ? TEAL : PURPLE);
                text(canvas, ModelStore.humanSize(model.size) + "  ·  " + (active ? "ATIVO" : "toque para usar"),
                        getWidth() - dp(205), y + dp(87), 10, active ? TEAL : MUTED, active);
                y += dp(128);
            }
            if (models.size() < 2) {
                text(canvas, "Você pode adicionar um segundo GGUF multimodal / mmproj.", left + dp(32), y + dp(8), 11, MUTED, false);
            }
        }

        round(canvas, left + dp(28), getHeight() - dp(130), getWidth() - dp(28), getHeight() - dp(37), dp(14), Color.rgb(22, 31, 49));
        drawStatusDot(canvas, left + dp(52), getHeight() - dp(96), TEAL);
        text(canvas, "Backend", left + dp(72), getHeight() - dp(99), 11, MUTED, false);
        text(canvas, vulkanLabel(), left + dp(72), getHeight() - dp(77), 13, TEXT, true);
        text(canvas, "O acelerador é selecionado automaticamente quando disponível.", left + dp(240), getHeight() - dp(87), 10, MUTED, false);
    }

    private String vulkanLabel() {
        String status = NativeRuntime.vulkanStatus();
        return status.contains("\"available\":true") ? "Vulkan pronto" : "CPU seguro · Vulkan opcional";
    }

    private void drawResearch(Canvas canvas) {
        float left = mainLeft();
        drawTopBar(canvas, "Pesquisa", "Uma ferramenta opcional para contexto atual");
        text(canvas, "Pesquisa ao vivo", left + dp(32), dp(132), 22, TEXT, true);
        text(canvas, "Quando ativada no composer, Nova consulta fontes abertas antes de gerar.", left + dp(32), dp(160), 12, MUTED, false);
        round(canvas, left + dp(32), dp(190), getWidth() - dp(32), dp(318), dp(16), SURFACE);
        drawGlobe(canvas, left + dp(76), dp(238), TEAL);
        text(canvas, "Controle local", left + dp(120), dp(235), 14, TEXT, true);
        text(canvas, "A resposta final continua sendo gerada pelo GGUF", left + dp(120), dp(259), 11, MUTED, false);
        text(canvas, "importado. A ferramenta adiciona um resumo + fonte ao prompt.", left + dp(120), dp(278), 11, MUTED, false);
        chip(canvas, left + dp(32), dp(342), "DUCKDUCKGO INSTANT ANSWER", TEAL);
        text(canvas, "Sem histórico de pesquisa salvo pelo app.", left + dp(32), dp(383), 11, MUTED, false);
        text(canvas, "Dica", left + dp(32), dp(458), 11, ORANGE, true);
        text(canvas, "Use Pesquisa para fatos recentes; desligue-a para um chat 100% offline.", left + dp(32), dp(482), 12, TEXT, false);
    }

    private void drawSettings(Canvas canvas) {
        float left = mainLeft();
        drawTopBar(canvas, "Ajustes", "Desempenho e privacidade");
        text(canvas, "Nova Local", left + dp(32), dp(132), 22, TEXT, true);
        text(canvas, "Construído para deixar o modelo sob seu controle.", left + dp(32), dp(160), 12, MUTED, false);
        settingRow(canvas, left + dp(32), dp(205), "Execução em segundo plano", "Foreground service + tela bloqueada", true, TEAL);
        settingRow(canvas, left + dp(32), dp(275), "Mapeamento direto", "SAF descriptor · sem cópia temporária", true, PURPLE);
        settingRow(canvas, left + dp(32), dp(345), "Vulkan", "Usar quando o driver do aparelho suportar", true, ORANGE);
        settingRow(canvas, left + dp(32), dp(415), "Dados externos", "Pesquisa é opt-in e nunca é necessária", false, MUTED);
        text(canvas, "Nova Local 1.0.0  ·  GGUF / llama.cpp", left + dp(32), getHeight() - dp(52), 10, DIM, false);
    }

    private void settingRow(Canvas canvas, float x, float y, String title, String subtitle,
                            boolean enabled, int color) {
        text(canvas, title, x, y, 13, TEXT, true);
        text(canvas, subtitle, x, y + dp(21), 11, MUTED, false);
        paint.setColor(enabled ? color : DIM);
        canvas.drawCircle(getWidth() - dp(57), y - dp(4), dp(8), paint);
        stroke.setColor(enabled ? color : LINE);
        stroke.setStrokeWidth(dp(1));
        canvas.drawCircle(getWidth() - dp(57), y - dp(4), dp(13), stroke);
    }

    private void drawToolChip(Canvas canvas, float x, float y, String label, boolean on, int color, int width) {
        int bg = on ? blend(color, 0.20f) : SURFACE_2;
        round(canvas, x, y, x + dp(width), y + dp(28), dp(9), bg);
        if (on) drawStatusDot(canvas, x + dp(11), y + dp(14), color);
        text(canvas, label, x + dp(on ? 20 : 10), y + dp(18), 10, on ? TEXT : MUTED, on);
    }

    private void chip(Canvas canvas, float x, float y, String label, int color) {
        float width = Math.max(dp(61), paint.measureText(label) + dp(20));
        round(canvas, x, y - dp(13), x + width, y + dp(7), dp(7), blend(color, 0.20f));
        text(canvas, label, x + dp(9), y + dp(1), 8, color, true);
    }

    private void drawStatusDot(Canvas canvas, float x, float y, int color) {
        paint.setColor(color);
        canvas.drawCircle(x, y, dp(4), paint);
    }

    private void drawAssistantMark(Canvas canvas, float x, float y) {
        paint.setColor(PURPLE);
        canvas.drawCircle(x, y, dp(14), paint);
        paint.setColor(TEAL);
        canvas.drawCircle(x + dp(5), y - dp(6), dp(3), paint);
        stroke.setColor(BG);
        stroke.setStrokeWidth(dp(2));
        canvas.drawLine(x - dp(6), y - dp(6), x + dp(2), y + dp(5), stroke);
        canvas.drawLine(x + dp(2), y + dp(5), x + dp(8), y - dp(4), stroke);
    }

    private void drawChatBubbleIcon(Canvas canvas, float x, float y, int color) {
        stroke.setColor(color);
        stroke.setStrokeWidth(dp(1.5f));
        rect.set(x - dp(7), y - dp(6), x + dp(7), y + dp(5));
        canvas.drawRoundRect(rect, dp(3), dp(3), stroke);
        canvas.drawLine(x - dp(3), y + dp(5), x - dp(5), y + dp(8), stroke);
    }

    private void drawNavIcon(Canvas canvas, float x, float y, int icon, int color) {
        stroke.setColor(color);
        stroke.setStrokeWidth(dp(1.6f));
        if (icon == 0) drawChatBubbleIcon(canvas, x, y, color);
        else if (icon == 1) drawDatabase(canvas, x, y, color);
        else if (icon == 2) drawGlobe(canvas, x, y, color);
        else {
            canvas.drawCircle(x, y, dp(7), stroke);
            canvas.drawCircle(x, y, dp(2), stroke);
            for (int i = 0; i < 8; i++) {
                double angle = i * Math.PI / 4;
                canvas.drawLine(x + (float) Math.cos(angle) * dp(9), y + (float) Math.sin(angle) * dp(9),
                        x + (float) Math.cos(angle) * dp(11), y + (float) Math.sin(angle) * dp(11), stroke);
            }
        }
    }

    private void drawDatabase(Canvas canvas, float x, float y, int color) {
        stroke.setColor(color);
        stroke.setStrokeWidth(dp(1.6f));
        rect.set(x - dp(10), y - dp(8), x + dp(10), y + dp(8));
        canvas.drawOval(new RectF(x - dp(10), y - dp(10), x + dp(10), y - dp(2)), stroke);
        canvas.drawLine(x - dp(10), y - dp(6), x - dp(10), y + dp(7), stroke);
        canvas.drawLine(x + dp(10), y - dp(6), x + dp(10), y + dp(7), stroke);
        canvas.drawOval(new RectF(x - dp(10), y + dp(2), x + dp(10), y + dp(10)), stroke);
    }

    private void drawGlobe(Canvas canvas, float x, float y, int color) {
        stroke.setColor(color);
        stroke.setStrokeWidth(dp(1.5f));
        canvas.drawCircle(x, y, dp(10), stroke);
        canvas.drawOval(new RectF(x - dp(5), y - dp(10), x + dp(5), y + dp(10)), stroke);
        canvas.drawLine(x - dp(9), y, x + dp(9), y, stroke);
    }

    private void drawModelGlyph(Canvas canvas, float x, float y, int color) {
        paint.setColor(blend(color, 0.22f));
        canvas.drawCircle(x, y, dp(22), paint);
        stroke.setColor(color);
        stroke.setStrokeWidth(dp(1.5f));
        canvas.drawRect(x - dp(9), y - dp(9), x + dp(9), y + dp(9), stroke);
        canvas.drawLine(x - dp(9), y - dp(3), x + dp(9), y - dp(3), stroke);
        canvas.drawLine(x - dp(4), y - dp(9), x - dp(4), y + dp(9), stroke);
    }

    private void drawImageIcon(Canvas canvas, float x, float y, int color) {
        stroke.setColor(color);
        stroke.setStrokeWidth(dp(1.3f));
        canvas.drawRect(x - dp(7), y - dp(6), x + dp(7), y + dp(6), stroke);
        canvas.drawCircle(x + dp(3), y - dp(2), dp(2), stroke);
        Path path = new Path();
        path.moveTo(x - dp(5), y + dp(4));
        path.lineTo(x - dp(1), y);
        path.lineTo(x + dp(2), y + dp(3));
        path.lineTo(x + dp(5), y);
        canvas.drawPath(path, stroke);
    }

    private void drawPlus(Canvas canvas, float x, float y, int color) {
        stroke.setColor(color);
        stroke.setStrokeWidth(dp(1.8f));
        canvas.drawLine(x - dp(6), y, x + dp(6), y, stroke);
        canvas.drawLine(x, y - dp(6), x, y + dp(6), stroke);
    }

    private void drawArrow(Canvas canvas, float x, float y, int color) {
        stroke.setColor(color);
        stroke.setStrokeWidth(dp(1.8f));
        canvas.drawLine(x - dp(7), y, x + dp(6), y, stroke);
        canvas.drawLine(x + dp(1), y - dp(5), x + dp(6), y, stroke);
        canvas.drawLine(x + dp(1), y + dp(5), x + dp(6), y, stroke);
    }

    private void drawStop(Canvas canvas, float x, float y, int color) {
        paint.setColor(color);
        canvas.drawRoundRect(x - dp(5), y - dp(5), x + dp(5), y + dp(5), dp(2), dp(2), paint);
    }

    private void drawLoader(Canvas canvas, float x, float y) {
        stroke.setColor(TEAL);
        stroke.setStrokeWidth(dp(1.5f));
        rect.set(x, y, x + dp(20), y + dp(20));
        canvas.drawArc(rect, -70, 220, false, stroke);
    }

    private ArrayList<String> wrap(String value, float size, float maxWidth) {
        ArrayList<String> result = new ArrayList<>();
        if (value == null || value.isEmpty()) { result.add(""); return result; }
        paint.setTextSize(dp(size));
        String[] paragraphs = value.split("\\n", -1);
        for (String paragraph : paragraphs) {
            if (paragraph.isEmpty()) { result.add(""); continue; }
            String remaining = paragraph;
            while (!remaining.isEmpty()) {
                int count = paint.breakText(remaining, true, maxWidth, null);
                if (count <= 0) count = 1;
                int split = count;
                if (count < remaining.length()) {
                    int space = remaining.lastIndexOf(' ', count - 1);
                    if (space > 0) split = space;
                }
                result.add(remaining.substring(0, split).trim());
                remaining = remaining.substring(split).trim();
            }
        }
        return result;
    }

    private void text(Canvas canvas, String value, float x, float baseline, float size, int color, boolean bold) {
        paint.setStyle(Paint.Style.FILL);
        paint.setTextSize(dp(size));
        paint.setColor(color);
        paint.setTypeface(Typeface.create("sans-serif", bold ? Typeface.BOLD : Typeface.NORMAL));
        canvas.drawText(value == null ? "" : value, x, baseline, paint);
    }

    private void textCentered(Canvas canvas, String value, float x, float baseline, float size, int color, boolean bold) {
        paint.setTextSize(dp(size));
        paint.setTypeface(Typeface.create("sans-serif", bold ? Typeface.BOLD : Typeface.NORMAL));
        text(canvas, value, x - paint.measureText(value) / 2f, baseline, size, color, bold);
    }

    private void round(Canvas canvas, float l, float t, float r, float b, float radius, int color) {
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(color);
        canvas.drawRoundRect(l, t, r, b, radius, radius, paint);
    }

    private int blend(int color, float alpha) {
        int r = Color.red(color), g = Color.green(color), b = Color.blue(color);
        return Color.rgb((int) (r * alpha + 11 * (1 - alpha)),
                (int) (g * alpha + 16 * (1 - alpha)),
                (int) (b * alpha + 24 * (1 - alpha)));
    }

    private void scrollToBottom() {
        postDelayed(() -> {
            float content = dp(118);
            for (Message message : currentChat.messages) {
                content += dp(62) + wrap(message.text, 13, Math.min(dp(650), getWidth() - mainLeft() - dp(120))).size() * dp(20);
            }
            float viewport = getHeight() - dp(260);
            scrollY = Math.max(0, content - viewport);
            invalidate();
        }, 30);
    }

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        float x = event.getX();
        float y = event.getY();
        if (event.getAction() == MotionEvent.ACTION_DOWN) {
            downX = x; downY = y; moved = false;
            return true;
        }
        if (event.getAction() == MotionEvent.ACTION_MOVE) {
            if (screen == Screen.CHAT && x > mainLeft() && downY < getHeight() - dp(165)) {
                float delta = downY - y;
                if (Math.abs(delta) > dp(3)) moved = true;
                scrollY = Math.max(0, scrollY + delta);
                downY = y;
                invalidate();
            }
            return true;
        }
        if (event.getAction() != MotionEvent.ACTION_UP || moved) return true;

        float sw = sideWidth();
        if (x < sw) {
            if (y >= dp(68) && y <= dp(125)) action(Action.NEW_CHAT, -1);
            else if (y >= dp(132) && y < dp(198)) action(Action.SHOW_CHAT, -1);
            else if (y < dp(246)) action(Action.SHOW_MODELS, -1);
            else if (y < dp(302)) action(Action.SHOW_RESEARCH, -1);
            else if (y < dp(365)) action(Action.SHOW_SETTINGS, -1);
            else if (screen == Screen.CHAT && sw > dp(100) && y > dp(365)) {
                int index = Math.max(0, Math.min(chats.size() - 1, (int) ((y - dp(362)) / dp(39))));
                if (index >= 0 && index < chats.size()) { currentChat = chats.get(index); invalidate(); }
            }
            return true;
        }

        if (screen == Screen.CHAT) {
            if (y >= getHeight() - dp(150)) {
                float top = getHeight() - dp(151);
                if (x >= sw + dp(20) && x < sw + dp(58) && y > top) action(Action.OPEN_IMAGE, -1);
                else if (x >= sw + dp(62) && x < sw + dp(134) && y > top) action(Action.TOGGLE_THINK, -1);
                else if (x >= sw + dp(137) && x < sw + dp(227) && y > top) action(Action.TOGGLE_RESEARCH, -1);
                else if (x >= sw + dp(227) && x < sw + dp(300) && y > top) action(Action.TOGGLE_VISION, -1);
                else if (x > getWidth() - dp(83) && y > getHeight() - dp(83)) action(generating ? Action.CANCEL : Action.SEND, -1);
            } else if (models.isEmpty() && y > getHeight() / 2f + dp(60)) {
                action(Action.IMPORT_MODELS, -1);
            }
        } else if (screen == Screen.MODELS) {
            if (x > getWidth() - dp(210) && y > dp(80) && y < dp(150)) action(Action.IMPORT_MODELS, -1);
            else {
                float cardY = dp(151);
                for (int i = 0; i < models.size(); i++) {
                    if (y >= cardY && y <= cardY + dp(112)) action(Action.SELECT_MODEL, i);
                    cardY += dp(128);
                }
            }
        }
        return true;
    }

    private void action(Action action, int index) {
        if (listener != null) listener.onAction(action, index);
    }
}
