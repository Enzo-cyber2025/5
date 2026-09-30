package com.enzo.ets2ai;

import android.annotation.SuppressLint;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothHidDevice;
import android.bluetooth.BluetoothHidDeviceAppSdpSettings;
import android.bluetooth.BluetoothProfile;
import android.content.Context;
import android.os.Build;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Turns the phone into a REAL Bluetooth keyboard (HID device role) for the
 * PC: the AI's commands are delivered as actual keystrokes — no .exe needed
 * on the PC for input. Uses the public android.bluetooth.BluetoothHidDevice
 * API (Android 9+; the A55 ships with Android 14).
 *
 * The PC must be PAIRED with the phone first (Android Settings -> Bluetooth).
 * Bang-bang thresholds mirror the Windows injector (steer 0.25, pedals 0.30).
 */
public final class BtKeyboard {

    /** Standard HID boot-keyboard report descriptor. */
    private static final byte[] KEYBOARD_DESCRIPTOR = {
        0x05, 0x01, 0x09, 0x06, (byte) 0xA1, 0x01,
        0x05, 0x07, (byte) 0x19, (byte) 0xE0, (byte) 0x29, (byte) 0xE7,
        0x15, 0x00, 0x25, 0x01, (byte) 0x75, 0x01, (byte) 0x95, 0x08,
        (byte) 0x81, 0x02, (byte) 0x95, 0x01, (byte) 0x75, 0x08,
        (byte) 0x81, 0x01, (byte) 0x95, 0x06, (byte) 0x75, 0x08,
        0x15, 0x00, 0x25, 0x65, 0x05, 0x07, 0x19, 0x00,
        (byte) 0x29, 0x65, (byte) 0x81, 0x00, (byte) 0xC0
    };

    // HID usage IDs (keyboard page)
    private static final byte USAGE_LEFT = 0x50, USAGE_RIGHT = 0x4F,
            USAGE_UP = 0x52, USAGE_DOWN = 0x51;

    public interface Listener {
        void onStatus(String status);
    }

    private final Listener listener;
    private BluetoothAdapter adapter;
    private BluetoothHidDevice hid;
    private BluetoothDevice host;
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private boolean appRegistered = false;
    private final java.util.HashSet<Byte> down = new java.util.HashSet<Byte>();
    private volatile boolean ready = false;

    public BtKeyboard(Listener listener) {
        this.listener = listener;
    }

    public static boolean supported() {
        return Build.VERSION.SDK_INT >= 29;
    }

    public boolean isReady() {
        return ready;
    }

    /** Must be called after BLUETOOTH_CONNECT is granted (API 31+). */
    @SuppressLint("MissingPermission")
    public void start(final Context ctx) {
        if (!supported()) {
            post("HID precisa de Android 9+ (este aparelho e anterior)");
            return;
        }
        adapter = BluetoothAdapter.getDefaultAdapter();
        if (adapter == null) {
            post("Este aparelho nao tem Bluetooth");
            return;
        }
        if (!adapter.isEnabled()) {
            post("Ligue o Bluetooth do celular");
            return;
        }
        adapter.getProfileProxy(ctx.getApplicationContext(), new BluetoothProfile.ServiceListener() {
            @Override
            public void onServiceConnected(int profile, BluetoothProfile proxy) {
                if (profile != BluetoothProfile.HID_DEVICE) return;
                hid = (BluetoothHidDevice) proxy;
                BluetoothHidDeviceAppSdpSettings sdp = new BluetoothHidDeviceAppSdpSettings(
                        "ETS2-AI", "ETS2-AI Keyboard", "Enzo", 0x0101,
                        (byte) 0xC1, KEYBOARD_DESCRIPTOR);
                hid.registerApp(sdp, null, null, executor, new BluetoothHidDevice.Callback() {
                    @Override
                    public void onAppStatusChanged(BluetoothDevice device, boolean registered) {
                        appRegistered = registered;
                        post(registered ? "teclado HID registrado" : "teclado HID removido");
                    }

                    @Override
                    public void onConnectionStateChanged(BluetoothDevice device, int state) {
                        if (state == BluetoothProfile.STATE_CONNECTED) {
                            host = device;
                            ready = true;
                            post("TECLADO CONECTADO a " + device.getName());
                        } else if (state == BluetoothProfile.STATE_DISCONNECTED) {
                            ready = false;
                            host = null;
                            post("teclado desconectado");
                        }
                    }
                });
            }

            @Override
            public void onServiceDisconnected(int profile) {
                ready = false;
                post("servico HID caiu");
            }
        }, BluetoothProfile.HID_DEVICE);
    }

    /** Connects to an already-bonded (paired) device. */
    @SuppressLint("MissingPermission")
    public void connect(BluetoothDevice device) {
        if (hid == null || !appRegistered) {
            post("aguardando registro HID... tente de novo em 2 s");
            return;
        }
        post("conectando a " + device.getName() + " ...");
        boolean ok = hid.connect(device);
        if (!ok) post("o PC recusou a conexao HID (pareie o celular com o PC antes)");
    }

    @SuppressLint("MissingPermission")
    public void stop() {
        ready = false;
        try {
            if (hid != null) {
                if (host != null) hid.disconnect(host);
                if (appRegistered) hid.unregisterApp();
                if (adapter != null) adapter.closeProfileProxy(BluetoothProfile.HID_DEVICE, hid);
            }
        } catch (Exception ignored) { }
    }

    /** Maps continuous commands to real keystrokes (hysteresis, like the PC injector). */
    public void update(float steer, float throttle, float brake) {
        if (!ready || hid == null || host == null) return;
        java.util.HashSet<Byte> want = new java.util.HashSet<Byte>();
        if (steer < -0.25f) want.add(USAGE_LEFT);
        if (steer > 0.25f) want.add(USAGE_RIGHT);
        if (throttle > 0.30f) want.add(USAGE_UP);
        if (brake > 0.30f) want.add(USAGE_DOWN);
        if (want.equals(down)) return;          // nothing changed
        down.clear();
        down.addAll(want);
        byte[] report = new byte[8];            // [mods, 0, k1..k6]
        int slot = 2;
        for (Byte k : want) {
            if (slot < 8) report[slot++] = k;
        }
        try {
            hid.sendReport(host, 0, report);
        } catch (Exception e) {
            ready = false;
            post("falha ao enviar tecla: " + e.getMessage());
        }
    }

    private void post(final String s) {
        Listener l = listener;
        if (l != null) l.onStatus(s);
    }
}
