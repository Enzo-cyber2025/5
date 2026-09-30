"""Convert the trained policy weights to TensorFlow Lite (run in CI).

Produces:
  - ets2ai-float32.tflite   (float32, mirrors the Java/numpy net exactly)
  - ets2ai-int8.tflite      (dynamic-range int8, candidate for HW delegates)
and cross-checks the float32 graph against the numpy forward pass.

Requires tensorflow (CI installs tensorflow-cpu). Import is deferred so the
rest of the package stays numpy-only.
"""
import argparse
from pathlib import Path
import numpy as np

from .contract import load_weights, N_IN, N_OUT, HIDDEN, LOSS_TARGET
from .model import forward


def build_keras(layers):
    import tensorflow as tf
    model = tf.keras.Sequential()
    model.add(tf.keras.Input(shape=(int(layers[0][0].shape[0]),)))
    for i, (w, b) in enumerate(layers):
        act = "linear" if i == len(layers) - 1 else "tanh"
        model.add(tf.keras.layers.Dense(int(w.shape[1]), activation=act))
    for i, (w, b) in enumerate(layers):
        model.layers[i].set_weights([w, b])
    return model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default="artifacts/model-weights.json")
    ap.add_argument("--out", default="artifacts")
    args = ap.parse_args()
    import tensorflow as tf

    layers, meta = load_weights(args.weights)
    model = build_keras(layers)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # float32 graph
    f32 = out / "ets2ai-float32.tflite"
    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    f32.write_bytes(conv.convert())

    # dynamic-range int8
    i8 = out / "ets2ai-int8.tflite"
    conv8 = tf.lite.TFLiteConverter.from_keras_model(model)
    conv8.optimizations = [tf.lite.Optimize.DEFAULT]
    i8.write_bytes(conv8.convert())

    # cross-check float32 tflite vs numpy on random inputs
    rng = np.random.default_rng(7)
    x = rng.uniform(-1.5, 1.5, (64, N_IN)).astype(np.float32)
    ref = forward(x, layers)
    interp = tf.lite.Interpreter(model_path=str(f32))
    interp.allocate_tensors()
    inp = interp.get_input_details()[0]
    outp = interp.get_output_details()[0]
    preds = np.zeros((len(x), N_OUT), dtype=np.float32)
    for i in range(len(x)):
        interp.set_tensor(inp["index"], x[i:i + 1])
        interp.invoke()
        preds[i] = interp.get_tensor(outp["index"])[0]
    err = float(np.max(np.abs(preds - ref)))
    rel = float(np.max(np.abs(preds - ref) / (np.abs(ref) + 1e-6)))
    print(f"tflite float32 vs numpy: max abs err {err:.2e} | max rel err {rel:.2e}")
    assert err < 1e-4, "TFLite graph diverges from numpy reference"
    print(f"OK -> {f32} ({f32.stat().st_size} B), {i8} ({i8.stat().st_size} B), "
          f"val_loss {meta['final_loss']:.5f} (target <= {LOSS_TARGET})")


if __name__ == "__main__":
    main()
