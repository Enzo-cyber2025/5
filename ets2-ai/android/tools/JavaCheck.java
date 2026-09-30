import com.enzo.ets2ai.NeuralNet;
import com.enzo.ets2ai.SimWorld;

import java.io.FileInputStream;
import java.util.Locale;

/**
 * Host-side verification harness (NOT packaged in the APK).
 *
 * 1) Evaluates the Java forward() on fixed inputs; the CI compares the
 *    printed values against the numpy reference (max |delta| < 1e-4).
 * 2) Runs a short closed-loop drive with the Java world port to confirm
 *    the truck stays in lane.
 *
 * Usage: java -cp classes com.enzo.ets2ai.JavaCheckFalseRoot model-weights.txt
 * (kept in android/tools; compiled separately by ci/check_java.sh)
 */
public class JavaCheck {

    public static void main(String[] args) throws Exception {
        final NeuralNet net = NeuralNet.fromStream(new FileInputStream(args[0]));

        // ---- 1. numeric parity with numpy ----
        float[][] probes = {
            { 0.60f, -0.5714f, 0.0833f, 0.0f, 0.02f, 0.04f, 0.05f, 0.0f, 1.0f, 0.80f, 0.10f, 0.05f, 0.92f },
            { 0.85f, 0.2857f, -0.1667f, 0.03f, -0.03f, 0.0f, 0.0f, 0.0f, 1.0f, 0.55f, 0.40f, 0.30f, 0.10f },
            { 1.30f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.95f, 0.75f, 0.80f, 0.50f },
            { 0.95f, 0.8571f, 0.2500f, -0.04f, -0.06f, -0.08f, -0.02f, 0.0f, 1.0f, 0.30f, 0.05f, 0.02f, 0.05f },
            { 0.10f, -0.2857f, 0.4167f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.50f, 0.20f, 0.60f, 0.80f },
        };
        System.out.println("JAVA_FORWARD_BEGIN");
        for (float[] p : probes) {
            float[] out = net.forward(p);
            float[] clamped = NeuralNet.clampAction(out[0], out[1], out[2]);
            System.out.println(String.format(Locale.US,
                    "%.6f,%.6f,%.6f,%.6f,%.6f,%.6f",
                    out[0], out[1], out[2], clamped[0], clamped[1], clamped[2]));
        }
        System.out.println("JAVA_FORWARD_END");

        // ---- 2. full mission loop in the Java port ----
        // (engine -> drive -> dock -> unload -> next job via dispatcher)
        SimWorld world = new SimWorld();
        int steps = 0;
        while (world.jobsDone < 1 && steps < 30000) {
            float[] f = NeuralNet.features(
                    world.truck.speed, world.truck.offset, world.headingError(),
                    world.curvAhead(), SimWorld.SPEED_LIMIT,
                    world.truck.fuel, world.truck.fatigue, world.jobLeftKm(),
                    world.radarDist());
            float[] raw = net.forward(f);
            float[] cmd = NeuralNet.clampAction(raw[0], raw[1], raw[2]);
            world.step(SimWorld.governor(world.road, world.truck, cmd));
            steps++;
        }
        System.out.println(String.format(Locale.US,
                "JAVA_MISSION steps=%d jobsDone=%d in_lane=%.3f km=%.2f money=%.0f",
                steps, world.jobsDone, world.inLanePct,
                world.truck.drivenKm, world.truck.money));
        if (world.inLanePct < 0.90f) {
            System.out.println("JAVA_LOOP_FAIL: fora da faixa");
            System.exit(2);
        }
        if (world.jobsDone < 1) {
            System.out.println("JAVA_MISSION_FAIL: nao entregou nenhum job");
            System.exit(3);
        }
        System.out.println("JAVA_MISSION_OK");
    }
}
