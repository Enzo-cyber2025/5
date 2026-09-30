package com.enzo.ets2ai;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Random;

/**
 * Port of ets2ai/sim.py: road ribbon, kinematic truck, career rules.
 * Same constants, same integration, same rule thresholds as the trainer.
 */
public final class SimWorld {

    public static final float DT = 0.1f;
    public static final float WHEELBASE = 4.0f;
    public static final float MAX_STEER = 0.6f;
    public static final float MAX_ACCEL = 1.8f;
    public static final float MAX_BRAKE = 3.2f;
    public static final float DRAG = 0.030f;
    public static final float LANE_HALF = 2.0f;
    public static final float ROAD_HALF = 4.6f;

    public static final float REFUEL_BELOW = 0.14f;
    public static final float SLEEP_ABOVE = 0.82f;
    public static final float FUEL_BURN_IDLE = 0.000012f;
    public static final float FUEL_BURN_FULL = 0.000160f;
    public static final float FATIGUE_RATE = 1f / (11f * 3600f);
    public static final float FUEL_PRICE = 1.45f;
    public static final int TANK_LITERS = 600;
    public static final float SPEED_LIMIT = 25f;
    public static final float JOB_PAY_PER_KM = 12f;   // EUR (demo economy)
    public static final float SLEEP_HOTEL_EUR = 220f;

    public static final float[] LOOKAHEAD = { 8f, 18f, 40f, 90f, 170f };

    /** Road: piecewise constant curvature; integrated centreline samples. */
    public static final class Road {
        public final float[] sx, sy, ss;      // samples every 2 m
        final float[] segCum, segCurv;
        public final float length;

        Road(float[] segLen, float[] segCurv) {
            this.radars = new float[0];
            List<Float> cum = new ArrayList<Float>();
            cum.add(0f);
            for (float L : segLen) cum.add(cum.get(cum.size() - 1) + L);
            this.segCum = new float[cum.size()];
            for (int i = 0; i < cum.size(); i++) segCum[i] = cum.get(i);
            this.segCurv = segCurv;
            this.length = segCum[segCum.length - 1];

            List<Float> xs = new ArrayList<Float>(), ys = new ArrayList<Float>(), sList = new ArrayList<Float>();
            xs.add(0f); ys.add(0f); sList.add(0f);
            float hdg = 0f, s = 0f;
            while (s < length) {
                s = Math.min(s + 2f, length);
                hdg += curvatureAt(s) * 2f;
                float px = xs.get(xs.size() - 1), py = ys.get(ys.size() - 1);
                xs.add(px + 2f * (float) Math.cos(hdg));
                ys.add(py + 2f * (float) Math.sin(hdg));
                sList.add(s);
            }
            sx = toF(xs); sy = toF(ys); ss = toF(sList);
        }

        private static float[] toF(List<Float> l) {
            float[] a = new float[l.size()];
            for (int i = 0; i < a.length; i++) a[i] = l.get(i);
            return a;
        }

        public float[] radars;               // speed cameras (m along the route)

        public static Road random(long seed) {
            Random rng = new Random(seed);
            int n = 40;
            float[] len = new float[n], curv = new float[n];
            for (int i = 0; i < n; i++) {
                len[i] = 60f + rng.nextFloat() * 360f;
                if (rng.nextFloat() < 0.35f) curv[i] = 0f;
                else curv[i] = (rng.nextFloat() * 2f - 1f) * 0.012f;
            }
            Road road = new Road(len, curv);
            java.util.List<Float> rad = new java.util.ArrayList<Float>();
            Random rng2 = new Random(seed + 777L);
            float pos = 700f;
            while (pos < road.length - 150f) {
                rad.add(pos);
                pos += 1500f + rng2.nextFloat() * 1300f;
            }
            road.radars = new float[rad.size()];
            for (int i = 0; i < rad.size(); i++) road.radars[i] = rad.get(i);
            return road;
        }

        /** Metres to the next camera ahead of s (500 = none ahead). */
        public float radarDistAhead(float s) {
            float best = 500f;
            for (float r : radars) {
                float d = r - s;
                if (d > 0f && d < best) best = d;
            }
            return best;
        }

        public float curvatureAt(float s) {
            if (s < 0f) s = 0f;
            if (s > length - 0.0001f) s = length - 0.0001f;
            for (int i = 0; i < segCurv.length; i++)
                if (s <= segCum[i + 1] + 0.0001f) return segCurv[i];
            return 0f;
        }

        /** nearest sample index to (x, y), searching a window around hint. */
        int nearest(float x, float y, int hint) {
            int best = -1;
            float bestD2 = Float.MAX_VALUE;
            int lo = Math.max(0, hint - 40), hi = Math.min(sx.length, hint + 40);
            for (int i = lo; i < hi; i++) {
                float dx = sx[i] - x, dy = sy[i] - y;
                float d2 = dx * dx + dy * dy;
                if (d2 < bestD2) { bestD2 = d2; best = i; }
            }
            if (best >= 0 && bestD2 < 900f) return best;
            best = 0; bestD2 = Float.MAX_VALUE;
            for (int i = 0; i < sx.length; i++) {
                float dx = sx[i] - x, dy = sy[i] - y;
                float d2 = dx * dx + dy * dy;
                if (d2 < bestD2) { bestD2 = d2; best = i; }
            }
            return best;
        }

        /** returns {s, offset, tangentHeading} */
        public float[] project(float x, float y, int hint) {
            int i = nearest(x, y, hint);
            int i0 = Math.max(0, i - 2), i1 = Math.min(sx.length - 1, i + 2);
            float tx = sx[i1] - sx[i0], ty = sy[i1] - sy[i0];
            float tn = (float) Math.hypot(tx, ty);
            if (tn < 0.0001f) { tx = 1f; ty = 0f; tn = 1f; }
            tx /= tn; ty /= tn;
            float dx = x - sx[i], dy = y - sy[i];
            float offset = dx * -ty + dy * tx;
            return new float[] { ss[i], offset, (float) Math.atan2(ty, tx) };
        }
    }

    /** Truck state + physics step (mirrors sim.py Truck). */
    public static final class Truck {
        public float x, y, heading, speed, steerPos;
        public float fuel = 1f, fatigue = 0f, money = 0f, drivenKm = 0f;
        public float s = 0f, offset = 0f, tangent = 0f;
        public int hint = 0;

        public Truck(Road road, Random rng) {
            float off = (rng.nextFloat() * 2f - 1f) * 2f;
            // place at s = 5 m with jittered offset/speed/heading
            float[] p5 = projectAt(road, 5f);
            x = p5[0] - off * (float) Math.sin(p5[2]);
            y = p5[1] + off * (float) Math.cos(p5[2]);
            speed = 8f + rng.nextFloat() * 14f;
            float[] pr = road.project(x, y, 0);
            tangent = pr[2];
            heading = tangent + (rng.nextFloat() * 2f - 1f) * 0.25f;
            s = pr[0];
        }

        private static float[] projectAt(Road road, float s) {
            int i = 0; float best = Float.MAX_VALUE;
            for (int k = 0; k < road.ss.length; k++) {
                float d = Math.abs(road.ss[k] - s);
                if (d < best) { best = d; i = k; }
            }
            int i0 = Math.max(0, i - 1), i1 = Math.min(road.sx.length - 1, i + 1);
            float th = (float) Math.atan2(road.sy[i1] - road.sy[i0], road.sx[i1] - road.sx[i0]);
            return new float[] { road.sx[i], road.sy[i], th };
        }

        public void step(Road road, float steer, float throttle, float brake) {
            steer = Math.max(-1f, Math.min(1f, steer));
            throttle = Math.max(0f, Math.min(1f, throttle));
            brake = Math.max(0f, Math.min(1f, brake));
            float d = steer - steerPos;
            if (d > 0.15f) d = 0.15f;
            if (d < -0.15f) d = -0.15f;
            steerPos += d;
            float wheel = steerPos * MAX_STEER;
            heading += (speed / WHEELBASE) * (float) Math.tan(wheel) * DT;
            x += speed * (float) Math.cos(heading) * DT;
            y += speed * (float) Math.sin(heading) * DT;
            float acc = throttle * MAX_ACCEL - brake * MAX_BRAKE - DRAG * speed;
            speed = Math.max(0f, speed + acc * DT);
            drivenKm += speed * DT / 1000f;
            fuel = Math.max(0f, fuel - DT * (FUEL_BURN_IDLE + throttle * (FUEL_BURN_FULL - FUEL_BURN_IDLE)));
            fatigue = Math.min(1f, fatigue + DT * FATIGUE_RATE);
            float[] pr = road.project(x, y, hint);
            s = pr[0]; offset = pr[1]; tangent = pr[2];
            hint = road.nearest(x, y, hint);
        }
    }

    // ------------------------------------------------------------------
    // World: road + truck + rules + status for the UI.
    // ------------------------------------------------------------------
    public Road road;
    public Truck truck;
    public Random rng = new Random(1234567L);
    public boolean aiEnabled = true;
    public String event = "";          // "" | "refuel" | "sleep" | "delivered"
    public float eventTimer = 0f;      // seconds remaining of the event pause
    public String eventText = "";
    public int jobsDone = 0;
    public boolean crashed = false;
    public float inLanePct = 1f;
    public float jobPay = 0f;
    public String jobLabel = "";
    private int stepsTotal = 1, stepsInLane = 1;

    public SimWorld() {
        newRoute();
    }

    public void newRoute() {
        Dispatcher.Offer best = Dispatcher.pickBest(rng, 3);
        road = Road.random(best.roadSeed);
        truck = new Truck(road, rng);
        jobPay = best.payEur;
        jobLabel = "JOB: " + best.label() + " [melhor de 3]";
        crashed = false;
        truck.speed = 0f;                      // engine off at the job start
        event = "engine";
        eventTimer = 1.5f;
        eventText = "Ligando o motor... (tecla E)";
        stepsTotal = 1;
        stepsInLane = 1;
    }

    public float jobLeftKm() {
        return Math.max(0f, (road.length - truck.s) / 1000f);
    }

    /** ESC-like rollover governor (mirrors sim.governor): full brake when the
     *  current speed cannot be shed before the START of a curve ahead. */
    public static float[] governor(Road road, Truck t, float[] cmd) {
        float worst = Float.MAX_VALUE;
        for (int i = 0; i < road.segCurv.length; i++) {
            float segStart = road.segCum[i], segEnd = road.segCum[i + 1];
            if (segEnd <= t.s) continue;
            float d = Math.max(0f, segStart - t.s);
            if (d > 260f) break;
            float k = Math.abs(road.segCurv[i]);
            if (k < 0.000001f) continue;
            float vCurve = (float) Math.sqrt(0.92f * 3.6f / k);
            float vAllow = (float) Math.sqrt(vCurve * vCurve
                    + 2f * MAX_BRAKE * Math.max(0f, d - 8f));
            if (vAllow < worst) worst = vAllow;
        }
        if (worst != Float.MAX_VALUE && t.speed > worst)
            return new float[] { cmd[0], 0f, 1f };
        // dock governor: never carry speed into the loading dock (full distance)
        float dDock = (road.length - 6f) - t.s;
        if (dDock > 0f && dDock < 600f) {
            float vAllow = (float) Math.sqrt(2f * MAX_BRAKE * Math.max(0f, dDock - 2f));
            if (t.speed > vAllow + 0.3f) return new float[] { cmd[0], 0f, 1f };
            if (dDock <= 1.5f) return new float[] { cmd[0], 0f, 1f };   // hold
            if (dDock < 30f && t.speed < 0.8f)
                return new float[] { cmd[0], 0.30f, 0f };               // creep
        }
        return cmd;
    }

    public float radarDist() {
        return road.radarDistAhead(truck.s);
    }

    public float[] curvAhead() {
        float[] c = new float[5];
        for (int i = 0; i < 5; i++) c[i] = road.curvatureAt(truck.s + LOOKAHEAD[i]);
        return c;
    }

    public float headingError() {
        float a = truck.heading - truck.tangent;
        while (a > Math.PI) a -= 2f * (float) Math.PI;
        while (a < -Math.PI) a += 2f * (float) Math.PI;
        return a;
    }

    /** One physics step; `cmd` = {steer, throttle, brake} (already clamped). */
    public void step(float[] cmd) {
        if (crashed) return;
        if (eventTimer > 0f) {          // parked: refuelling / sleeping
            eventTimer -= DT;
            if (eventTimer <= 0f) {
                if ("refuel".equals(event)) {
                    truck.fuel = 1f;
                    truck.money -= FUEL_PRICE * TANK_LITERS * (1f - REFUEL_BELOW);
                } else if ("sleep".equals(event)) {
                    truck.fatigue = 0f;
                    truck.money -= SLEEP_HOTEL_EUR;
                } else if ("unload".equals(event)) {
                    jobsDone++;                 // cargo delivered + loaded
                    newRoute();                 // dispatcher picks, engine starts
                    return;
                } else if ("engine".equals(event)) {
                    eventText = "";
                }
                event = "";
            }
            return;
        }
        truck.step(road, cmd[0], cmd[1], cmd[2]);
        stepsTotal++;
        if (Math.abs(truck.offset) < LANE_HALF) stepsInLane++;
        inLanePct = stepsInLane / (float) stepsTotal;
        if (Math.abs(truck.offset) > ROAD_HALF) {
            crashed = true;
            eventText = "BATER! Fora da pista";
            return;
        }
        if (truck.fuel < REFUEL_BELOW) {
            event = "refuel";
            eventTimer = 2.0f;
            eventText = "Abastecendo 600 L (-" + String.format("%.0f", FUEL_PRICE * TANK_LITERS * (1f - REFUEL_BELOW)) + " EUR)";
            return;
        }
        if (truck.fatigue > SLEEP_ABOVE) {
            event = "sleep";
            eventTimer = 2.5f;
            eventText = "Dormindo 9 h no hotel (-220 EUR)";
            return;
        }
        if (truck.s >= road.length - 10f && truck.speed < 0.8f) {
            float pay = jobPay > 0f ? jobPay : truck.drivenKm * JOB_PAY_PER_KM;
            truck.money += pay;
            event = "unload";
            eventTimer = 3.0f;
            eventText = String.format(Locale.US,
                    "No dock: descarrega e carrega (T)… +%d EUR", (int) pay);
        }
    }
}
