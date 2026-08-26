package com.xclipse64.launcher;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.res.AssetManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.widget.CheckBox;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Space;
import android.widget.TextView;
import android.widget.Toast;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Enumeration;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.HashMap;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import java.util.zip.ZipInputStream;

/**
 * Xclipse64 is deliberately a platform-only launcher.  The emulation layer and
 * graphics bundles are user supplied so the APK does not redistribute third
 * party binaries or Windows games.
 */
public final class MainActivity extends Activity {
    private static final String PREFS = "xclipse64_preferences";
    private static final String PROFILE_X64 = "x64";
    private static final String PROFILE_X86 = "x86";
    private static final String TRANSLATOR_DXVK = "dxvk";
    private static final String TRANSLATOR_VKD3D = "vkd3d";
    private static final String TRANSLATOR_WINED3D = "wined3d";

    private static final int REQUEST_GAME = 41;
    private static final int REQUEST_RUNTIME = 42;
    private static final int REQUEST_DRIVER = 43;

    private static final int BG = Color.rgb(10, 13, 18);
    private static final int SURFACE = Color.rgb(18, 23, 32);
    private static final int ELEVATED = Color.rgb(24, 33, 45);
    private static final int STROKE = Color.rgb(38, 50, 66);
    private static final int TEXT = Color.rgb(245, 247, 250);
    private static final int MUTED = Color.rgb(155, 168, 184);
    private static final int ACCENT = Color.rgb(124, 255, 107);
    private static final int BLUE = Color.rgb(119, 183, 255);
    private static final int WARNING = Color.rgb(255, 200, 87);

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private SharedPreferences preferences;
    private LinearLayout body;
    private LinearLayout profiles;
    private LinearLayout translators;
    private TextView gameValue;
    private TextView runtimeValue;
    private TextView driverValue;
    private TextView gpuTitle;
    private TextView gpuDetail;
    private TextView gpuDot;
    private TextView launchButton;
    private TextView outputValue;
    private Process currentProcess;
    private boolean bundledCoreReady;
    private String bundledCoreError = "";

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        preferences = getSharedPreferences(PREFS, MODE_PRIVATE);
        bootstrapBundledComponents();
        configureWindow();
        buildUi();
    }

    private void configureWindow() {
        Window window = getWindow();
        window.setStatusBarColor(BG);
        window.setNavigationBarColor(BG);
        if (Build.VERSION.SDK_INT >= 28) {
            window.setNavigationBarDividerColor(BG);
        }
        if (Build.VERSION.SDK_INT >= 30) {
            WindowInsetsController controller = window.getInsetsController();
            if (controller != null) {
                controller.setSystemBarsAppearance(0, WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS);
            }
        } else {
            window.getDecorView().setSystemUiVisibility(0);
        }
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(BG);

        LinearLayout topBar = new LinearLayout(this);
        topBar.setGravity(Gravity.CENTER_VERTICAL);
        topBar.setPadding(dp(20), dp(18), dp(20), dp(10));
        root.addView(topBar, new LinearLayout.LayoutParams(-1, dp(76)));

        TextView mark = text("X", 25, ACCENT, Typeface.BOLD);
        mark.setGravity(Gravity.CENTER);
        GradientDrawable markBg = rounded(ACCENT, 14);
        markBg.setColor(Color.rgb(22, 50, 27));
        mark.setBackground(markBg);
        topBar.addView(mark, new LinearLayout.LayoutParams(dp(44), dp(44)));

        LinearLayout brand = vertical(0);
        brand.setPadding(dp(12), 0, 0, 0);
        TextView brandName = text("XCLIPSE64", 19, TEXT, Typeface.BOLD);
        brandName.setLetterSpacing(.12f);
        brand.addView(brandName, wrap());
        TextView brandSub = text("ANDROID WINDOWS RUNTIME", 10, MUTED, Typeface.NORMAL);
        brandSub.setLetterSpacing(.08f);
        brand.addView(brandSub, wrap());
        topBar.addView(brand, new LinearLayout.LayoutParams(0, -2, 1));

        TextView version = pill("v0.2.0", MUTED, Color.TRANSPARENT);
        topBar.addView(version, wrap());

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setClipToPadding(false);
        body = vertical(0);
        body.setPadding(dp(20), dp(4), dp(20), dp(28));
        scroll.addView(body, new ScrollView.LayoutParams(-1, -2));
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(root);

        addIntro();
        addStatusCard();
        addQuickActions();
        addProfileSection();
        addTranslatorSection();
        addDriverSection();
        addRuntimeSection();
        addFooter();
    }

    private void addIntro() {
        TextView eyebrow = text("DESKTOP COMPATIBILITY LAYER", 11, ACCENT, Typeface.BOLD);
        eyebrow.setLetterSpacing(.09f);
        body.addView(eyebrow, withBottom(wrap(), 8));
        TextView headline = text("Seu Windows.\nNo seu Android.", 31, TEXT, Typeface.BOLD);
        headline.setLineSpacing(0, 1.02f);
        body.addView(headline, withBottom(wrap(), 10));
        TextView copy = text("Um runtime ARM64 para Windows x86, com Box64 embutido, DXVK / VKD3D e uma camada Vulkan de compatibilidade para GPUs Xclipse.", 14, MUTED, Typeface.NORMAL);
        copy.setLineSpacing(0, 1.2f);
        body.addView(copy, withBottom(wrap(), 22));
    }

    private void addStatusCard() {
        LinearLayout card = card();
        LinearLayout row = new LinearLayout(this);
        row.setGravity(Gravity.CENTER_VERTICAL);
        gpuDot = text("●", 18, ACCENT, Typeface.BOLD);
        gpuDot.setGravity(Gravity.CENTER);
        row.addView(gpuDot, new LinearLayout.LayoutParams(dp(30), dp(34)));
        LinearLayout copy = vertical(0);
        gpuTitle = text("Verificando GPU…", 16, TEXT, Typeface.BOLD);
        copy.addView(gpuTitle, wrap());
        gpuDetail = text("Consultando o Vulkan do sistema", 12, MUTED, Typeface.NORMAL);
        copy.addView(gpuDetail, withTop(wrap(), 3));
        row.addView(copy, new LinearLayout.LayoutParams(0, -2, 1));
        TextView ready = pill("ONLINE", ACCENT, Color.rgb(25, 63, 30));
        row.addView(ready, wrap());
        card.addView(row, wrap());
        body.addView(card, withBottom(wrap(), 22));
        refreshGpuStatus();
    }

    private void addQuickActions() {
        body.addView(sectionLabel("COMEÇAR"), withBottom(wrap(), 10));
        LinearLayout actions = horizontal();
        TextView game = actionButton("＋  Importar jogo", true, v -> chooseGame());
        actions.addView(game, new LinearLayout.LayoutParams(0, dp(52), 1));
        TextView runtime = actionButton("＋  Instalar runtime", false, v -> chooseRuntime());
        LinearLayout.LayoutParams runtimeParams = new LinearLayout.LayoutParams(0, dp(52), 1);
        runtimeParams.setMargins(dp(10), 0, 0, 0);
        actions.addView(runtime, runtimeParams);
        body.addView(actions, withBottom(wrap(), 24));
    }

    private void addProfileSection() {
        body.addView(sectionLabel("ARQUITETURA DO WINDOWS"), withBottom(wrap(), 10));
        profiles = horizontal();
        body.addView(profiles, withBottom(wrap(), 22));
        renderProfiles();
    }

    private void renderProfiles() {
        if (profiles == null) return;
        profiles.removeAllViews();
        String selected = preferences.getString("profile", PROFILE_X64);
        profiles.addView(profileCard(
                "x64", "Box64\n64-bit", PROFILE_X64.equals(selected),
                v -> selectProfile(PROFILE_X64)), new LinearLayout.LayoutParams(0, dp(94), 1));
        LinearLayout.LayoutParams second = new LinearLayout.LayoutParams(0, dp(94), 1);
        second.setMargins(dp(10), 0, 0, 0);
        profiles.addView(profileCard(
                "x86", "Box32 / Box86\n32-bit", PROFILE_X86.equals(selected),
                v -> selectProfile(PROFILE_X86)), second);
    }

    private View profileCard(String title, String subtitle, boolean active, View.OnClickListener listener) {
        LinearLayout card = card();
        card.setPadding(dp(15), dp(13), dp(15), dp(12));
        card.setOnClickListener(listener);
        card.setBackground(active ? rounded(Color.rgb(23, 57, 29), 14) : rounded(SURFACE, 14));
        if (!active) stroke(card, STROKE, 1);
        LinearLayout top = horizontal();
        TextView name = text(title, 16, active ? ACCENT : TEXT, Typeface.BOLD);
        top.addView(name, new LinearLayout.LayoutParams(0, -2, 1));
        TextView state = text(active ? "✓" : "○", 16, active ? ACCENT : MUTED, Typeface.BOLD);
        top.addView(state, wrap());
        card.addView(top, wrap());
        TextView sub = text(subtitle, 11, active ? Color.rgb(176, 222, 168) : MUTED, Typeface.NORMAL);
        sub.setLineSpacing(0, 1.15f);
        card.addView(sub, withTop(wrap(), 6));
        return card;
    }

    private void selectProfile(String profile) {
        preferences.edit().putString("profile", profile).apply();
        renderProfiles();
        appendOutput("Perfil selecionado: " + (PROFILE_X64.equals(profile) ? "Windows x64 / Box64" : "Windows x86 / Box86"));
    }

    private void addTranslatorSection() {
        body.addView(sectionLabel("TRADUÇÃO GRÁFICA"), withBottom(wrap(), 10));
        translators = vertical(0);
        body.addView(translators, withBottom(wrap(), 22));
        renderTranslators();
    }

    private void renderTranslators() {
        if (translators == null) return;
        translators.removeAllViews();
        String selected = preferences.getString("translator", TRANSLATOR_DXVK);
        addTranslator("DXVK", "DirectX 9 / 10 / 11  →  Vulkan", TRANSLATOR_DXVK, selected);
        addTranslator("VKD3D-Proton", "DirectX 12  →  Vulkan", TRANSLATOR_VKD3D, selected);
        addTranslator("WineD3D", "Compatibilidade ampla  →  OpenGL/Vulkan", TRANSLATOR_WINED3D, selected);
    }

    private void addTranslator(String name, String description, String id, String selected) {
        boolean active = id.equals(selected);
        LinearLayout item = card();
        item.setPadding(dp(15), dp(13), dp(15), dp(13));
        item.setOnClickListener(v -> {
            preferences.edit().putString("translator", id).apply();
            renderTranslators();
            appendOutput("Tradutor selecionado: " + name);
        });
        if (active) {
            item.setBackground(rounded(Color.rgb(22, 39, 59), 13));
            stroke(item, BLUE, 1);
        }
        LinearLayout line = horizontal();
        TextView radio = text(active ? "●" : "○", 16, active ? BLUE : MUTED, Typeface.BOLD);
        line.addView(radio, new LinearLayout.LayoutParams(dp(28), -2));
        LinearLayout labels = vertical(0);
        labels.addView(text(name, 14, active ? TEXT : Color.rgb(215, 222, 231), Typeface.BOLD), wrap());
        labels.addView(text(description, 11, MUTED, Typeface.NORMAL), withTop(wrap(), 3));
        line.addView(labels, new LinearLayout.LayoutParams(0, -2, 1));
        TextView tag = pill(active ? "ATIVO" : "", active ? BLUE : MUTED, Color.TRANSPARENT);
        if (!active) tag.setVisibility(View.GONE);
        line.addView(tag, wrap());
        item.addView(line, wrap());
        LinearLayout.LayoutParams params = withBottom(wrap(), 8);
        translators.addView(item, params);
    }

    private void addDriverSection() {
        body.addView(sectionLabel("CAMADA VULKAN / XCLIPSE"), withBottom(wrap(), 10));
        LinearLayout card = card();
        LinearLayout row = horizontal();
        TextView icon = text("⌁", 24, ACCENT, Typeface.BOLD);
        icon.setGravity(Gravity.CENTER);
        row.addView(icon, new LinearLayout.LayoutParams(dp(34), dp(40)));
        LinearLayout labels = vertical(0);
        driverValue = text("Driver Vulkan do sistema", 14, TEXT, Typeface.BOLD);
        labels.addView(driverValue, wrap());
        TextView hint = text("BCn embutida • pass-through com o driver do sistema", 11, MUTED, Typeface.NORMAL);
        labels.addView(hint, withTop(wrap(), 3));
        row.addView(labels, new LinearLayout.LayoutParams(0, -2, 1));
        card.addView(row, wrap());

        TextView explanation = text("O APK inclui uma camada BCn de compatibilidade e um perfil para Exynos 1480 / Xclipse 530. O Android mantém o driver Samsung como backend; a camada não substitui driver de kernel ou firmware.", 11, MUTED, Typeface.NORMAL);
        explanation.setLineSpacing(0, 1.2f);
        card.addView(explanation, withTop(wrap(), 12));
        LinearLayout actions = horizontal();
        TextView importDriver = actionButton("Importar camada Xclipse", false, v -> chooseDriver());
        actions.addView(importDriver, new LinearLayout.LayoutParams(0, dp(44), 1));
        TextView check = actionButton("Verificar", false, v -> refreshGpuStatus());
        LinearLayout.LayoutParams checkParams = new LinearLayout.LayoutParams(dp(104), dp(44));
        checkParams.setMargins(dp(10), 0, 0, 0);
        actions.addView(check, checkParams);
        card.addView(actions, withTop(wrap(), 14));
        body.addView(card, withBottom(wrap(), 22));
        refreshDriverLabel();
    }

    private void addRuntimeSection() {
        body.addView(sectionLabel("AMBIENTE"), withBottom(wrap(), 10));
        LinearLayout card = card();
        LinearLayout gameRow = horizontal();
        gameRow.addView(text("EXECUTÁVEL", 10, MUTED, Typeface.BOLD), new LinearLayout.LayoutParams(0, -2, 1));
        TextView changeGame = linkButton("Alterar", v -> chooseGame());
        gameRow.addView(changeGame, wrap());
        card.addView(gameRow, wrap());
        gameValue = text("Nenhum .EXE selecionado", 14, MUTED, Typeface.NORMAL);
        card.addView(gameValue, withTop(wrap(), 7));

        LinearLayout runtimeRow = horizontal();
        runtimeRow.setPadding(0, dp(18), 0, 0);
        runtimeRow.addView(text("RUNTIME BOX", 10, MUTED, Typeface.BOLD), new LinearLayout.LayoutParams(0, -2, 1));
        TextView install = linkButton("Instalar ZIP", v -> chooseRuntime());
        runtimeRow.addView(install, wrap());
        card.addView(runtimeRow, wrap());
        runtimeValue = text("Núcleo Box64 + tradutores embutidos", 14, ACCENT, Typeface.NORMAL);
        card.addView(runtimeValue, withTop(wrap(), 7));
        TextView included = text("EMBUTIDO NO APK  •  Box64 0.4.2 Bionic  •  DXVK 2.3.1  •  VKD3D 2.14.1  •  D8VK 1.0  •  camada BCn para Vulkan/Xclipse 530\n\nWine/Proton e jogos continuam sendo importados separadamente por serem runtimes independentes.", 10, MUTED, Typeface.NORMAL);
        included.setLineSpacing(0, 1.2f);
        card.addView(included, withTop(wrap(), 9));

        outputValue = text("Pronto para configurar", 11, MUTED, Typeface.NORMAL);
        outputValue.setMaxLines(3);
        card.addView(outputValue, withTop(wrap(), 16));

        launchButton = actionButton("INICIAR WINDOWS", true, v -> launchGame());
        launchButton.setEnabled(true);
        card.addView(launchButton, withTop(wrap(), 16));
        body.addView(card, withBottom(wrap(), 22));
        refreshSelections();
        if (!bundledCoreError.isEmpty()) {
            appendOutput("Núcleo embutido: " + bundledCoreError);
        } else if (bundledCoreReady) {
            appendOutput("Núcleo Box64 + tradutores + camada BCn carregado do APK.");
        }
    }

    private void addFooter() {
        LinearLayout footer = vertical(0);
        TextView note = text("ARM64 + Vulkan  •  Box64 Bionic embutido  •  Box32/WOWBox64 e Box86 podem ser adicionados pelo runtime", 11, MUTED, Typeface.NORMAL);
        note.setGravity(Gravity.CENTER);
        footer.addView(note, wrap());
        TextView settings = linkButton("Opções avançadas e diagnóstico", v -> showSettings());
        settings.setGravity(Gravity.CENTER);
        footer.addView(settings, withTop(wrap(), 10));
        body.addView(footer, wrap());
    }

    private void refreshSelections() {
        if (gameValue != null) {
            String name = preferences.getString("gameName", "");
            gameValue.setText(name.isEmpty() ? "Nenhum .EXE selecionado" : name);
            gameValue.setTextColor(name.isEmpty() ? MUTED : TEXT);
        }
        if (runtimeValue != null) {
            boolean coreReady = isRuntimeReady();
            boolean wineReady = isWineReady();
            if (coreReady && wineReady) {
                runtimeValue.setText("Box64 + Wine/Proton prontos para executar");
                runtimeValue.setTextColor(ACCENT);
            } else if (coreReady) {
                runtimeValue.setText("Box64 + tradutores embutidos • Wine/Proton pendente");
                runtimeValue.setTextColor(WARNING);
            } else {
                runtimeValue.setText("Núcleo Box64 não encontrado");
                runtimeValue.setTextColor(MUTED);
            }
        }
        if (launchButton != null) {
            boolean canLaunch = !preferences.getString("gameUri", "").isEmpty()
                    && isRuntimeReady() && isWineReady();
            launchButton.setAlpha(canLaunch ? 1f : .65f);
        }
    }

    private void refreshDriverLabel() {
        if (driverValue == null) return;
        boolean imported = preferences.getBoolean("driverReady", false);
        driverValue.setText(imported ? "Camada Xclipse adicional importada" : "BCn embutida • driver Vulkan do sistema");
        driverValue.setTextColor(imported || bundledCoreReady ? ACCENT : TEXT);
    }

    private void refreshGpuStatus() {
        boolean vulkan = getPackageManager().hasSystemFeature(PackageManager.FEATURE_VULKAN_HARDWARE_LEVEL)
                || getPackageManager().hasSystemFeature(PackageManager.FEATURE_VULKAN_HARDWARE_VERSION);
        String socManufacturer = Build.VERSION.SDK_INT >= 31 ? Build.SOC_MANUFACTURER : "";
        String socModel = Build.VERSION.SDK_INT >= 31 ? Build.SOC_MODEL : "";
        String fingerprint = (Build.MANUFACTURER + " " + Build.BRAND + " " + Build.HARDWARE + " "
                + Build.BOARD + " " + socManufacturer + " " + socModel).toLowerCase(Locale.US);
        boolean xclipse = fingerprint.contains("xclipse") || fingerprint.contains("exynos")
                || (fingerprint.contains("samsung") && fingerprint.contains("s5e"));
        if (xclipse && vulkan) {
            gpuTitle.setText("Xclipse • Vulkan detectado");
            gpuDetail.setText(Build.MODEL + "  ·  driver do sistema ativo");
            gpuDot.setTextColor(ACCENT);
        } else if (vulkan) {
            gpuTitle.setText("Vulkan do sistema detectado");
            gpuDetail.setText(Build.MODEL + "  ·  Xclipse não confirmada");
            gpuDot.setTextColor(BLUE);
        } else {
            gpuTitle.setText("Vulkan não detectado");
            gpuDetail.setText("Confira o driver do fabricante do dispositivo");
            gpuDot.setTextColor(WARNING);
        }
    }

    private void chooseGame() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("*/*");
        intent.putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"application/octet-stream", "application/x-msdownload", "*/*"});
        startActivityForResult(intent, REQUEST_GAME);
    }

    private void chooseRuntime() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("*/*");
        intent.putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"application/zip", "application/gzip", "application/octet-stream", "*/*"});
        startActivityForResult(intent, REQUEST_RUNTIME);
    }

    private void chooseDriver() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("application/zip");
        startActivityForResult(intent, REQUEST_DRIVER);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (resultCode != RESULT_OK || data == null || data.getData() == null) return;
        Uri uri = data.getData();
        try {
            getContentResolver().takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION);
        } catch (Exception ignored) {
            // Some document providers do not expose persistable permissions.
        }
        if (requestCode == REQUEST_GAME) {
            String name = fileName(uri);
            preferences.edit().putString("gameUri", uri.toString()).putString("gameName", name).apply();
            refreshSelections();
            appendOutput("Executável selecionado: " + name);
        } else if (requestCode == REQUEST_RUNTIME) {
            installRuntime(uri);
        } else if (requestCode == REQUEST_DRIVER) {
            installDriver(uri);
        }
    }

    /**
     * Copies the redistributable ARM64 core from APK assets into the app's
     * private executable directory.  Keeping the copy private lets Android
     * execute the Bionic ELF and keeps the document picker isolated from the
     * compatibility layer.
     */
    private void bootstrapBundledComponents() {
        File runtimeRoot = new File(getFilesDir(), "runtime");
        File bundled = new File(runtimeRoot, "bundled");
        File marker = new File(bundled, ".xclipse64-bundled-0.4.2-full-graphics");
        try {
            if (marker.isFile() && findFile(bundled, "box64", 12) != null) {
                bundledCoreReady = true;
                return;
            }
            if (!runtimeRoot.exists() && !runtimeRoot.mkdirs()) {
                throw new IOException("não foi possível criar o diretório privado");
            }
            File staging = new File(runtimeRoot, ".bundled-staging");
            deleteRecursive(staging);
            if (!staging.mkdirs() && !staging.isDirectory()) {
                throw new IOException("não foi possível criar o staging");
            }
            copyAssetTree("bundled", staging);
            File box64 = findFile(staging, "box64", 12);
            File bcnLayer = findFileContaining(staging, "libbcn_layer.so", 12);
            if (box64 == null || bcnLayer == null) {
                throw new IOException("o APK não contém o núcleo ou a camada Vulkan");
            }
            box64.setExecutable(true, false);
            bcnLayer.setExecutable(true, false);
            deleteRecursive(bundled);
            if (!staging.renameTo(bundled)) {
                throw new IOException("não foi possível ativar o núcleo embutido");
            }
            if (!marker.createNewFile() && !marker.isFile()) {
                throw new IOException("não foi possível gravar o marcador");
            }
            bundledCoreReady = true;
        } catch (Exception error) {
            bundledCoreReady = false;
            bundledCoreError = safeMessage(error);
            deleteRecursive(new File(runtimeRoot, ".bundled-staging"));
        }
    }

    private void copyAssetTree(String assetPath, File destination) throws IOException {
        AssetManager assets = getAssets();
        String[] children = assets.list(assetPath);
        if (children != null && children.length > 0) {
            if (!destination.exists() && !destination.mkdirs()) {
                throw new IOException("não foi possível criar " + destination.getName());
            }
            for (String child : children) {
                copyAssetTree(assetPath + "/" + child, new File(destination, child));
            }
            return;
        }
        File parent = destination.getParentFile();
        if (parent != null && !parent.exists() && !parent.mkdirs()) {
            throw new IOException("não foi possível criar a pasta do componente");
        }
        try (InputStream input = assets.open(assetPath);
             OutputStream output = new BufferedOutputStream(new FileOutputStream(destination))) {
            byte[] buffer = new byte[64 * 1024];
            int count;
            while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
        }
        if (destination.getName().equalsIgnoreCase("box64")
                || destination.getName().toLowerCase(Locale.US).endsWith(".so")) {
            destination.setExecutable(true, false);
        }
    }

    private void installRuntime(final Uri uri) {
        appendOutput("Instalando runtime Wine/Proton…");
        new Thread(() -> {
            try {
                File staging = new File(getFilesDir(), "runtime_staging");
                deleteRecursive(staging);
                if (!staging.mkdirs() && !staging.isDirectory()) throw new IOException("Não foi possível criar a área de instalação");
                unzipSafely(uri, staging, 512L * 1024L * 1024L);
                File box64 = findFile(staging, "box64", 10);
                File box86 = findFile(staging, "box86", 10);
                File wine = findPreferredWine(staging, false);
                if (box64 == null && box86 == null && wine == null) {
                    throw new IOException("ZIP sem box64, box86 ou wine/wine64");
                }
                if (box64 != null) box64.setExecutable(true, false);
                if (box86 != null) box86.setExecutable(true, false);
                if (wine != null) wine.setExecutable(true, false);
                File runtime = new File(getFilesDir(), "runtime");
                if (!runtime.exists() && !runtime.mkdirs()) throw new IOException("Não foi possível criar o runtime");
                File userRuntime = new File(runtime, "user");
                deleteRecursive(userRuntime);
                if (!staging.renameTo(userRuntime)) throw new IOException("Não foi possível finalizar a instalação");
                preferences.edit().putBoolean("runtimeReady", true).putString("runtimeName", fileName(uri)).apply();
                mainHandler.post(() -> {
                    refreshSelections();
                    appendOutput("Runtime instalado com sucesso.");
                    toast("Runtime pronto");
                });
            } catch (Exception error) {
                deleteRecursive(new File(getFilesDir(), "runtime_staging"));
                mainHandler.post(() -> appendOutput("Falha no runtime: " + safeMessage(error)));
            }
        }, "runtime-install").start();
    }

    private void installDriver(final Uri uri) {
        appendOutput("Importando camada Xclipse…");
        new Thread(() -> {
            try {
                File staging = new File(getFilesDir(), "driver_staging");
                deleteRecursive(staging);
                if (!staging.mkdirs() && !staging.isDirectory()) throw new IOException("Não foi possível criar a área do driver");
                unzipSafely(uri, staging, 256L * 1024L * 1024L);
                File layer = findFileContaining(staging, ".so", 10);
                if (layer == null) throw new IOException("ZIP sem biblioteca Vulkan (.so)");
                File driver = new File(getFilesDir(), "xclipse-driver");
                deleteRecursive(driver);
                if (!staging.renameTo(driver)) throw new IOException("Não foi possível finalizar o driver");
                preferences.edit().putBoolean("driverReady", true).putString("driverName", fileName(uri)).apply();
                mainHandler.post(() -> {
                    refreshDriverLabel();
                    appendOutput("Camada Xclipse importada. O Android continuará usando o driver Samsung como backend.");
                    toast("Camada Xclipse pronta");
                });
            } catch (Exception error) {
                deleteRecursive(new File(getFilesDir(), "driver_staging"));
                mainHandler.post(() -> appendOutput("Falha na camada Xclipse: " + safeMessage(error)));
            }
        }, "driver-install").start();
    }

    private void launchGame() {
        if (currentProcess != null) {
            toast("Já existe um processo em execução");
            return;
        }
        String gameUri = preferences.getString("gameUri", "");
        if (gameUri.isEmpty()) {
            toast("Escolha um executável primeiro");
            chooseGame();
            return;
        }
        if (!isRuntimeReady()) {
            toast("O núcleo Box64 embutido não está disponível");
            chooseRuntime();
            return;
        }
        if (!isWineReady()) {
            toast("Importe um runtime Wine/Proton para abrir o .EXE");
            chooseRuntime();
            return;
        }

        new Thread(() -> {
            try {
                File runtime = new File(getFilesDir(), "runtime");
                String profile = preferences.getString("profile", PROFILE_X64);
                File box64 = findFile(runtime, "box64", 10);
                File box86 = findFile(runtime, "box86", 10);
                File emulator = PROFILE_X86.equals(profile) && box86 != null ? box86 : box64 != null ? box64 : box86;
                if (emulator == null) throw new IOException("Nenhum tradutor compatível encontrado");
                File executable = copyGameIntoSandbox(Uri.parse(gameUri));
                File wine = findPreferredWine(runtime, PROFILE_X86.equals(profile));
                List<String> command = new ArrayList<>();
                command.add(emulator.getAbsolutePath());
                if (wine != null) {
                    command.add(wine.getAbsolutePath());
                }
                command.add(executable.getAbsolutePath());

                Map<String, String> environment = buildEnvironment(runtime, profile);
                ProcessBuilder builder = new ProcessBuilder(command);
                builder.environment().putAll(environment);
                builder.redirectErrorStream(true);
                currentProcess = builder.start();
                appendOutput("Iniciando " + preferences.getString("gameName", "executável") + "…");
                readProcessOutput(currentProcess);
                int exitCode = currentProcess.waitFor();
                currentProcess = null;
                mainHandler.post(() -> appendOutput("Processo finalizado (código " + exitCode + ")."));
            } catch (Exception error) {
                currentProcess = null;
                mainHandler.post(() -> appendOutput("Falha ao iniciar: " + safeMessage(error)));
            }
        }, "windows-launch").start();
    }

    private Map<String, String> buildEnvironment(File runtime, String profile) {
        Map<String, String> env = new HashMap<>();
        String existingPath = System.getenv("PATH");
        env.put("PATH", runtime.getAbsolutePath() + "/bin:" + runtime.getAbsolutePath() + ":" + (existingPath == null ? "" : existingPath));
        env.put("HOME", new File(getFilesDir(), "home").getAbsolutePath());
        env.put("TMPDIR", new File(getCacheDir(), "runtime-tmp").getAbsolutePath());
        env.put("WINEPREFIX", new File(getFilesDir(), "wineprefix").getAbsolutePath());
        env.put("BOX64_DYNAREC", "1");
        env.put("BOX64_LOG", preferences.getBoolean("debugLogs", false) ? "1" : "0");
        env.put("BOX86_DYNAREC", "1");
        File bundledGraphics = new File(runtime, "bundled/graphics");
        File userGraphics = new File(runtime, "user/graphics");
        String dllPath = pathList(
                new File(bundledGraphics, "dxvk/system32"),
                new File(bundledGraphics, "vkd3d/system32"),
                new File(bundledGraphics, "d8vk/system32"),
                new File(userGraphics, "dxvk/system32"),
                new File(userGraphics, "vkd3d/system32"));
        if (!dllPath.isEmpty()) {
            env.put("WINEDLLPATH", dllPath);
            env.put("DXVK_PATH", new File(bundledGraphics, "dxvk").getAbsolutePath());
            env.put("VKD3D_PATH", new File(bundledGraphics, "vkd3d").getAbsolutePath());
        }
        File bundledXclipse = new File(runtime, "bundled/xclipse");
        String layerPath = pathList(bundledXclipse,
                preferences.getBoolean("driverReady", false) ? new File(getFilesDir(), "xclipse-driver") : null);
        if (!layerPath.isEmpty()) {
            env.put("VK_LAYER_PATH", layerPath);
            env.put("VK_INSTANCE_LAYERS", "VK_LAYER_BCN_BCnLayer");
            env.put("ENABLE_BCN_COMPUTE", "1");
        }
        String translator = preferences.getString("translator", TRANSLATOR_DXVK);
        if (TRANSLATOR_DXVK.equals(translator)) {
            env.put("WINEDLLOVERRIDES", "d3d9,d3d10core,d3d11,dxgi=n,b");
            env.put("DXVK_LOG_LEVEL", "none");
        } else if (TRANSLATOR_VKD3D.equals(translator)) {
            env.put("WINEDLLOVERRIDES", "d3d12=n,b;dxgi=n,b");
            env.put("VKD3D_DEBUG", "none");
        } else {
            env.put("WINEDLLOVERRIDES", "");
        }
        new File(env.get("HOME")).mkdirs();
        new File(env.get("TMPDIR")).mkdirs();
        new File(env.get("WINEPREFIX")).mkdirs();
        return env;
    }

    private void readProcessOutput(Process process) {
        new Thread(() -> {
            try (InputStream input = new BufferedInputStream(process.getInputStream())) {
                byte[] buffer = new byte[1024];
                int count;
                StringBuilder line = new StringBuilder();
                while ((count = input.read(buffer)) != -1) {
                    for (int i = 0; i < count; i++) {
                        char character = (char) buffer[i];
                        if (character == '\n' || line.length() > 300) {
                            appendOutput(line.toString());
                            line.setLength(0);
                        } else if (character != '\r') {
                            line.append(character);
                        }
                    }
                }
                if (line.length() > 0) appendOutput(line.toString());
            } catch (IOException error) {
                appendOutput("Log interrompido: " + safeMessage(error));
            }
        }, "windows-output").start();
    }

    private File copyGameIntoSandbox(Uri uri) throws IOException {
        File games = new File(getFilesDir(), "games");
        if (!games.exists() && !games.mkdirs()) throw new IOException("Não foi possível criar a pasta do jogo");
        String name = sanitizeFileName(preferences.getString("gameName", "game.exe"));
        File target = new File(games, name);
        try (InputStream input = getContentResolver().openInputStream(uri);
             OutputStream output = new BufferedOutputStream(new FileOutputStream(target))) {
            if (input == null) throw new IOException("O provedor não abriu o arquivo");
            byte[] buffer = new byte[64 * 1024];
            int count;
            while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
        }
        target.setExecutable(true, false);
        return target;
    }

    private String pathList(File... paths) {
        StringBuilder result = new StringBuilder();
        if (paths == null) return "";
        for (File path : paths) {
            if (path == null || !path.exists()) continue;
            if (result.length() > 0) result.append(File.pathSeparator);
            result.append(path.getAbsolutePath());
        }
        return result.toString();
    }

    private void showSettings() {
        LinearLayout settings = vertical(0);
        settings.setPadding(dp(6), dp(6), dp(6), 0);
        CheckBox debug = new CheckBox(this);
        debug.setText("Mostrar log detalhado do Box64 / Box86");
        debug.setTextColor(TEXT);
        debug.setTextSize(14);
        debug.setChecked(preferences.getBoolean("debugLogs", false));
        debug.setButtonTintList(android.content.res.ColorStateList.valueOf(ACCENT));
        settings.addView(debug, wrap());
        TextView about = text("Este APK já inclui o núcleo Box64 Bionic, DXVK, VKD3D, D8VK e a camada BCn. Wine/Proton e componentes x86 de 32 bits podem ser importados como conteúdo separado. O Android mantém o driver Vulkan Samsung/Xclipse do aparelho; a camada incluída não substitui firmware ou kernel.", 12, MUTED, Typeface.NORMAL);
        about.setLineSpacing(0, 1.2f);
        settings.addView(about, withTop(wrap(), 12));
        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle("Diagnóstico")
                .setView(settings)
                .setPositiveButton("Salvar", (d, which) -> {
                    preferences.edit().putBoolean("debugLogs", debug.isChecked()).apply();
                    appendOutput("Preferências salvas.");
                })
                .setNegativeButton("Fechar", null)
                .create();
        dialog.setOnShowListener(d -> {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setTextColor(ACCENT);
            dialog.getButton(AlertDialog.BUTTON_NEGATIVE).setTextColor(MUTED);
        });
        dialog.show();
    }

    private void appendOutput(String message) {
        if (outputValue == null) return;
        Runnable update = () -> {
            String previous = outputValue.getText().toString();
            if (previous.equals("Pronto para configurar")) previous = "";
            String combined = previous.isEmpty() ? message : previous + "\n" + message;
            if (combined.length() > 450) combined = combined.substring(combined.length() - 450);
            outputValue.setText(combined);
        };
        if (Looper.myLooper() == Looper.getMainLooper()) update.run(); else mainHandler.post(update);
    }

    private boolean isRuntimeReady() {
        File runtime = new File(getFilesDir(), "runtime");
        boolean translatorFound = findFile(runtime, "box64", 12) != null
                || findFile(runtime, "box86", 12) != null;
        return translatorFound && (bundledCoreReady || preferences.getBoolean("runtimeReady", false));
    }

    private boolean isWineReady() {
        File runtime = new File(getFilesDir(), "runtime");
        return findPreferredWine(runtime, false) != null;
    }

    private File findPreferredWine(File root, boolean x86) {
        String[] names = x86 ? new String[]{"wine", "wine64"} : new String[]{"wine64", "wine"};
        for (String name : names) {
            File result = findFile(root, name, 10);
            if (result != null) return result;
        }
        return null;
    }

    private File findFile(File root, String wantedName, int maxDepth) {
        if (root == null || !root.exists() || maxDepth < 0) return null;
        if (root.isFile() && root.getName().equalsIgnoreCase(wantedName)) return root;
        File[] children = root.listFiles();
        if (children == null) return null;
        for (File child : children) {
            File result = findFile(child, wantedName, maxDepth - 1);
            if (result != null) return result;
        }
        return null;
    }

    private File findFileContaining(File root, String fragment, int maxDepth) {
        if (root == null || !root.exists() || maxDepth < 0) return null;
        if (root.isFile() && root.getName().toLowerCase(Locale.US).contains(fragment.toLowerCase(Locale.US))) return root;
        File[] children = root.listFiles();
        if (children == null) return null;
        for (File child : children) {
            File result = findFileContaining(child, fragment, maxDepth - 1);
            if (result != null) return result;
        }
        return null;
    }

    private void unzipSafely(Uri source, File destination, long maxBytes) throws IOException {
        long extracted = 0;
        int entries = 0;
        try (InputStream raw = getContentResolver().openInputStream(source);
             ZipInputStream zip = new ZipInputStream(new BufferedInputStream(raw))) {
            if (raw == null) throw new IOException("Arquivo não disponível");
            ZipEntry entry;
            byte[] buffer = new byte[64 * 1024];
            while ((entry = zip.getNextEntry()) != null) {
                if (++entries > 50000) throw new IOException("ZIP com entradas demais");
                File target = safeZipTarget(destination, entry.getName());
                if (entry.isDirectory()) {
                    if (!target.exists() && !target.mkdirs()) throw new IOException("Falha ao criar pasta");
                    continue;
                }
                File parent = target.getParentFile();
                if (parent != null && !parent.exists() && !parent.mkdirs()) throw new IOException("Falha ao criar pasta");
                try (OutputStream output = new BufferedOutputStream(new FileOutputStream(target))) {
                    int count;
                    while ((count = zip.read(buffer)) != -1) {
                        extracted += count;
                        if (extracted > maxBytes) throw new IOException("ZIP excede o limite de tamanho");
                        output.write(buffer, 0, count);
                    }
                }
                zip.closeEntry();
            }
        }
    }

    private File safeZipTarget(File destination, String entryName) throws IOException {
        File target = new File(destination, entryName);
        String root = destination.getCanonicalPath() + File.separator;
        String path = target.getCanonicalPath();
        if (!path.startsWith(root)) throw new IOException("ZIP inválido");
        return target;
    }

    private void deleteRecursive(File file) {
        if (file == null || !file.exists()) return;
        if (file.isDirectory()) {
            File[] children = file.listFiles();
            if (children != null) for (File child : children) deleteRecursive(child);
        }
        //noinspection ResultOfMethodCallIgnored
        file.delete();
    }

    private String fileName(Uri uri) {
        String last = uri.getLastPathSegment();
        if (last == null || last.trim().isEmpty()) return "arquivo selecionado";
        int slash = last.lastIndexOf('/');
        return sanitizeFileName(slash >= 0 ? last.substring(slash + 1) : last);
    }

    private String sanitizeFileName(String name) {
        if (name == null || name.trim().isEmpty()) return "game.exe";
        String cleaned = name.replaceAll("[^a-zA-Z0-9._ -]", "_");
        return cleaned.length() > 120 ? cleaned.substring(cleaned.length() - 120) : cleaned;
    }

    private String safeMessage(Exception error) {
        String message = error.getMessage();
        return message == null || message.isEmpty() ? error.getClass().getSimpleName() : message;
    }

    private void toast(String message) {
        mainHandler.post(() -> Toast.makeText(this, message, Toast.LENGTH_SHORT).show());
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private LinearLayout vertical(int padding) {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        if (padding != 0) layout.setPadding(padding, padding, padding, padding);
        return layout;
    }

    private LinearLayout horizontal() {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.HORIZONTAL);
        layout.setGravity(Gravity.CENTER_VERTICAL);
        return layout;
    }

    private LinearLayout card() {
        LinearLayout layout = vertical(0);
        layout.setPadding(dp(16), dp(16), dp(16), dp(16));
        layout.setBackground(rounded(SURFACE, 15));
        return layout;
    }

    private TextView text(String value, float size, int color, int style) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        view.setTypeface(Typeface.create("sans-serif", style));
        view.setIncludeFontPadding(true);
        return view;
    }

    private TextView pill(String value, int color, int background) {
        TextView view = text(value, 10, color, Typeface.BOLD);
        view.setGravity(Gravity.CENTER);
        view.setPadding(dp(9), dp(5), dp(9), dp(5));
        view.setLetterSpacing(.08f);
        if (background != Color.TRANSPARENT) view.setBackground(rounded(background, 20));
        return view;
    }

    private TextView actionButton(String value, boolean primary, View.OnClickListener listener) {
        TextView view = text(value, 12, primary ? BG : TEXT, Typeface.BOLD);
        view.setGravity(Gravity.CENTER);
        view.setTextAlignment(View.TEXT_ALIGNMENT_CENTER);
        view.setPadding(dp(10), 0, dp(10), 0);
        view.setOnClickListener(listener);
        view.setBackground(rounded(primary ? ACCENT : ELEVATED, 12));
        if (!primary) stroke(view, STROKE, 1);
        return view;
    }

    private TextView linkButton(String value, View.OnClickListener listener) {
        TextView view = text(value, 12, ACCENT, Typeface.BOLD);
        view.setGravity(Gravity.CENTER);
        view.setPadding(dp(4), dp(4), dp(4), dp(4));
        view.setOnClickListener(listener);
        return view;
    }

    private TextView sectionLabel(String value) {
        TextView view = text(value, 10, MUTED, Typeface.BOLD);
        view.setLetterSpacing(.13f);
        return view;
    }

    private GradientDrawable rounded(int color, int radiusDp) {
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(color);
        shape.setCornerRadius(dp(radiusDp));
        return shape;
    }

    private void stroke(View view, int color, int widthDp) {
        if (view.getBackground() instanceof GradientDrawable) {
            ((GradientDrawable) view.getBackground()).setStroke(dp(widthDp), color);
        }
    }

    private LinearLayout.LayoutParams wrap() {
        return new LinearLayout.LayoutParams(-1, -2);
    }

    private LinearLayout.LayoutParams withTop(LinearLayout.LayoutParams params, int marginDp) {
        params.topMargin = dp(marginDp);
        return params;
    }

    private LinearLayout.LayoutParams withBottom(LinearLayout.LayoutParams params, int marginDp) {
        params.bottomMargin = dp(marginDp);
        return params;
    }

    @Override
    protected void onDestroy() {
        if (currentProcess != null) {
            currentProcess.destroy();
            currentProcess = null;
        }
        super.onDestroy();
    }
}
