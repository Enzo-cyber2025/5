package com.ggufchat.app;

import android.app.Activity;
import android.content.res.ColorStateList;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.util.Log;
import android.util.TypedValue;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;

import java.lang.reflect.Field;

/** Linguagem visual do aplicativo inteiro, inspirada no Off Grid AI.
 *
 * Referência de estilo: minimalista, terminal, denso, tipografia monoespaçada,
 * um único acento esmeralda usado com parcimônia sobre superfícies neutras,
 * bordas de fio de cabelo, cantos de 8 dp e hierarquia por tamanho/peso/opacidade
 * em vez de cor. Nada aqui é código, marca ou arte daquele aplicativo: são
 * decisões próprias aplicadas às telas deste projeto.
 *
 * Regras de segurança desta classe:
 *  - nunca altera o texto de nenhum controle, porque os testes de interface
 *    procuram os rótulos reais no aparelho;
 *  - nunca lança exceção para o chamador: se um componente desconhecido aparecer,
 *    ele é simplesmente ignorado e um log curto registra o que ficou de fora.
 */
public final class OffgridUi {
    private static final String TAG = "GGUFOffgridUi";

    // Tokens próprios (inspiração, não cópia literal).
    private static final int BASE = 0xFF0A0A0A;
    private static final int SURFACE = 0xFF121212;
    private static final int SURFACE_PLUS = 0xFF1C1C1C;
    private static final int BORDER = 0xFF2A2A2A;
    private static final int EMERALD = 0xFF34D399;
    private static final int ON_EMERALD = 0xFF07130E;
    private static final int TEXT = 0xFFFAFAFA;
    private static final int TEXT_2 = 0xFFD4D4D4;
    private static final int TEXT_3 = 0xFFA1A1A1;
    private static final int TEXT_4 = 0xFF6E6E6E;

    private static final String[] PRIMARY_LABELS = {
        "Enviar", "Salvar", "Criar", "Aplicar", "Baixar", "Importar", "Continuar", "Concluir"};

    private static Typeface mono;

    private OffgridUi() {}

    private static Typeface mono() {
        if (mono == null) mono = Typeface.create(Typeface.MONOSPACE, Typeface.NORMAL);
        return mono;
    }

    private static float density(View view) {
        return view.getResources().getDisplayMetrics().density;
    }

    private static int dp(View view, float value) {
        return Math.round(value * density(view));
    }

    /** Aplica a linguagem visual a uma tela inteira, depois de montada. */
    public static void screen(Activity activity) {
        if (activity == null) return;
        try {
            View content = activity.getWindow() == null ? null : activity.getWindow().getDecorView();
            if (content == null) return;
            content.setBackgroundColor(BASE);
            int[] seen = new int[]{0};
            walk(activity, content, 0, seen);
            Log.i(TAG, "GGUF_OFFGRID_UI screen=" + activity.getClass().getSimpleName()
                + " views=" + seen[0] + " mono=1 radius_dp=8 accent=emerald");
        } catch (Throwable error) {
            Log.i(TAG, "GGUF_OFFGRID_UI_SKIPPED " + error.getClass().getSimpleName()
                + " (interface original preservada)");
        }
    }

    /** A tela da conversa: mesma linguagem, entrando depois do conteúdo real. */
    public static void chat(Activity activity) {
        screen(activity);
    }

    /** Barra inferior com três destinos, um acento esmeralda no destino ativo. */
    public static void tabs(Activity activity, int active) {
        if (activity == null) return;
        try {
            Button[] tabs = {field(activity, "navChat"), field(activity, "navImport"), field(activity, "navModels")};
            for (int index = 0; index < tabs.length; index++) {
                Button tab = tabs[index];
                if (tab == null) continue;
                boolean selected = index == active;
                tab.setAllCaps(false);
                tab.setTypeface(mono());
                tab.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11.5f);
                tab.setLetterSpacing(0.06f);
                tab.setIncludeFontPadding(false);
                tab.setTextColor(selected ? EMERALD : TEXT_3);
                tab.setBackground(pill(tab, selected ? SURFACE_PLUS : SURFACE, selected ? 0 : BORDER));
                tab.setContentDescription((selected ? "Seção atual: " : "Seção: ") + tab.getText());
            }
            Button first = tabs[0];
            View row = first == null || first.getParent() == null ? null : (View) first.getParent();
            if (row != null) {
                row.setBackgroundColor(SURFACE);
                if (row instanceof ViewGroup) {
                    ViewGroup holder = (ViewGroup) row.getParent();
                    // A barra de destinos fica no fim da tela; reposiciona apenas
                    // quando o aplicativo a colocou em outro lugar.
                    if (holder != null && holder.indexOfChild(row) != holder.getChildCount() - 1) {
                        holder.removeView(row);
                        holder.addView(row);
                    }
                }
            }
            Log.i(TAG, "GGUF_OFFGRID_UI tabs=" + tabs.length + " active=" + active + " bottom_bar=1");
        } catch (Throwable error) {
            Log.i(TAG, "GGUF_OFFGRID_UI_TABS_SKIPPED " + error.getClass().getSimpleName());
        }
    }

    /** Uma mensagem recém-adicionada recebe os mesmos tokens das já existentes. */
    public static void bubble(View message) {
        if (message == null) return;
        try {
            walk(null, message, 0, new int[]{0});
        } catch (Throwable error) {
            Log.i(TAG, "GGUF_OFFGRID_UI_BUBBLE_SKIPPED " + error.getClass().getSimpleName());
        }
    }

    private static void walk(Activity activity, View view, int depth, int[] seen) {
        if (view == null || depth > 24) return;
        seen[0]++;
        if (view instanceof ViewGroup) {
            ViewGroup group = (ViewGroup) view;
            for (int index = 0; index < group.getChildCount(); index++)
                walk(activity, group.getChildAt(index), depth + 1, seen);
        }
        if (view instanceof TextView) {
            styleText(view, (TextView) view);
            return;
        }
        surface(view, view instanceof EditText || view.isClickable());
    }

    private static void styleText(View holder, TextView text) {
        text.setTypeface(mono());
        if (text instanceof Button) {
            styleButton(holder, (Button) text);
            return;
        }
        if (text instanceof EditText) {
            EditText input = (EditText) text;
            input.setTextColor(TEXT);
            input.setHintTextColor(TEXT_4);
            input.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f);
            input.setBackground(box(input, SURFACE, BORDER));
            return;
        }
        int color = text.getCurrentTextColor();
        if (isAccent(color)) {
            text.setTextColor(EMERALD);
        } else {
            text.setTextColor(tier(color));
        }
        float size = text.getTextSize() / density(text);
        // Rótulos pequenos e discretos ("sussurros"): espaçamento e opacidade,
        // nunca alteração do texto nem caixa alta, para não quebrar nenhum teste.
        if (size <= 12.5f && isMuted(color)) {
            text.setLetterSpacing(0.08f);
            text.setIncludeFontPadding(false);
        }
        surface(text, false);
    }

    private static void styleButton(View holder, Button button) {
        String label = button.getText() == null ? "" : button.getText().toString();
        boolean primary = false;
        for (String candidate : PRIMARY_LABELS)
            if (label.contains(candidate)) primary = true;
        button.setAllCaps(false);
        button.setTypeface(mono());
        button.setIncludeFontPadding(false);
        button.setLetterSpacing(0.02f);
        if (primary) {
            button.setTextColor(ON_EMERALD);
            button.setBackground(box(button, EMERALD, 0));
        } else {
            button.setTextColor(TEXT_2);
            button.setBackground(box(button, SURFACE_PLUS, BORDER));
        }
    }

    /** Superfícies: cantos de 8 dp, neutros alinhados aos tokens, borda de fio. */
    private static void surface(View view, boolean bordered) {
        Drawable background = view.getBackground();
        if (!(background instanceof GradientDrawable)) return;
        GradientDrawable shape = (GradientDrawable) background.mutate();
        try {
            shape.setCornerRadius(dp(view, 8));
            ColorStateList solid = shape.getColor();
            int color = solid == null ? 0 : solid.getDefaultColor();
            if (isAccent(color)) {
                shape.setColor(EMERALD);
            } else if (isNeutralDark(color)) {
                shape.setColor(luminance(color) > 0.055f ? SURFACE_PLUS : SURFACE);
            }
            if (bordered && shape.getStrokeWidth() <= 0) {
                shape.setStroke(Math.max(1, dp(view, 1) / 2), BORDER);
            }
        } catch (Throwable ignored) {
            // Um drawable exótico não deve interromper a tela.
        }
    }

    private static GradientDrawable box(View view, int fill, int stroke) {
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(fill);
        shape.setCornerRadius(dp(view, 8));
        if (stroke != 0) shape.setStroke(Math.max(1, dp(view, 1) / 2), stroke);
        return shape;
    }

    private static GradientDrawable pill(View view, int fill, int stroke) {
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(fill);
        shape.setCornerRadius(dp(view, 8));
        if (stroke != 0) shape.setStroke(Math.max(1, dp(view, 1) / 2), stroke);
        return shape;
    }

    private static int tier(int color) {
        float value = luminance(color);
        if (value >= 0.72f) return TEXT;
        if (value >= 0.45f) return TEXT_2;
        if (value >= 0.22f) return TEXT_3;
        return TEXT_4;
    }

    private static boolean isMuted(int color) {
        float value = luminance(color);
        return value < 0.55f;
    }

    private static boolean isNeutralDark(int color) {
        if (color == 0) return false;
        int r = (color >> 16) & 0xFF, g = (color >> 8) & 0xFF, b = color & 0xFF;
        int high = Math.max(r, Math.max(g, b)), low = Math.min(r, Math.min(g, b));
        return high - low <= 18 && luminance(color) < 0.16f;
    }

    private static boolean isAccent(int color) {
        int r = (color >> 16) & 0xFF, g = (color >> 8) & 0xFF, b = color & 0xFF;
        int high = Math.max(r, Math.max(g, b)), low = Math.min(r, Math.min(g, b));
        return high - low > 28 && g >= r && g >= b && g > 90;
    }

    private static float luminance(int color) {
        return (((color >> 16) & 0xFF) * 0.2126f + ((color >> 8) & 0xFF) * 0.7152f + (color & 0xFF) * 0.0722f) / 255f;
    }

    private static Button field(Activity activity, String name) {
        try {
            Field field = activity.getClass().getDeclaredField(name);
            field.setAccessible(true);
            Object value = field.get(activity);
            return value instanceof Button ? (Button) value : null;
        } catch (Exception error) {
            return null;
        }
    }
}
