package com.ggufchat.testinput;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.inputmethodservice.InputMethodService;
import android.util.Base64;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputConnection;
import java.nio.charset.StandardCharsets;

/** Disposable emulator-only IME. Only writes the actual focused app EditText.
 * No model/response/metric injection, no networking or storage permission.
 * Never packaged in the production APK; installed only in the test emulator.
 */
public final class InputBridge extends InputMethodService {
    private final BroadcastReceiver receiver = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            EditorInfo editor = getCurrentInputEditorInfo();
            InputConnection connection = getCurrentInputConnection();
            if (editor == null || connection == null ||
                    !"com.ggufchat.app".equals(editor.packageName)) {
                setResultData("not-ready"); return;
            }
            if ("com.ggufchat.testinput.READY".equals(intent.getAction())) {
                setResultData("ready"); return;
            }
            if (!"com.ggufchat.testinput.TEXT".equals(intent.getAction())) return;
            try {
                String text = new String(Base64.decode(intent.getStringExtra("text_b64"), Base64.DEFAULT), StandardCharsets.UTF_8);
                connection.beginBatchEdit();
                try {
                    connection.performContextMenuAction(android.R.id.selectAll);
                    setResultData(connection.commitText(text, 1) ? "committed" : "failed");
                } finally { connection.endBatchEdit(); }
            } catch (RuntimeException error) { setResultData("failed"); }
        }
    };
    @Override public void onCreate() {
        super.onCreate();
        IntentFilter filter = new IntentFilter("com.ggufchat.testinput.READY");
        filter.addAction("com.ggufchat.testinput.TEXT");
        registerReceiver(receiver, filter, Context.RECEIVER_EXPORTED);
    }
    @Override public boolean onEvaluateInputViewShown() { return false; }
    @Override public void onDestroy() {
        unregisterReceiver(receiver); super.onDestroy();
    }
}
