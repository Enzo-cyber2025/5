package com.enzo.ets2ai;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Random;

/**
 * Job dispatcher / company management (port of ets2ai/dispatch.py).
 *
 * Picks the best of N job offers by net EUR/km after fuel and mandatory
 * rests, penalised by route curviness. Same constants as the Python side.
 */
public final class Dispatcher {

    public static final float FUEL_STOP_EUR = 745f;
    public static final float FUEL_RANGE_KM = 1500f;
    public static final float REST_EVERY_KM = 900f;
    public static final float HOTEL_EUR = 220f;
    public static final float EUR_PER_KM_MIN = 9f;
    public static final float EUR_PER_KM_MAX = 14f;
    public static final float CURVE_PENALTY = 8f;

    public static final class Offer {
        public final long roadSeed;
        public final float km;
        public final float payEur;
        public final int fuelStops;
        public final int sleepStops;
        public final float meanAbsCurv;
        public final float score;

        Offer(long roadSeed, float km, float payEur, int fuelStops,
              int sleepStops, float meanAbsCurv, float score) {
            this.roadSeed = roadSeed;
            this.km = km;
            this.payEur = payEur;
            this.fuelStops = fuelStops;
            this.sleepStops = sleepStops;
            this.meanAbsCurv = meanAbsCurv;
            this.score = score;
        }

        public float netEur() {
            return payEur - fuelStops * FUEL_STOP_EUR - sleepStops * HOTEL_EUR;
        }

        public String label() {
            return String.format(Locale.US, "%.1f km, %.0f EUR (%.1f EUR/km liq.)",
                    km, payEur, netEur() / Math.max(km, 0.1f));
        }
    }

    public static Offer offer(Random rng, SimWorld.Road road) {
        float km = road.length / 1000f;
        float pay = (EUR_PER_KM_MIN + rng.nextFloat() * (EUR_PER_KM_MAX - EUR_PER_KM_MIN)) * km;
        int fuelStops = (int) Math.ceil(km / FUEL_RANGE_KM);
        int sleepStops = (int) Math.ceil(km / REST_EVERY_KM);
        float curv = 0f;
        // reuse the road's curvature samples via curvatureAt sweep (2 m steps)
        int n = (int) (road.length / 40f) + 1;
        for (int i = 0; i < n; i++) curv += Math.abs(road.curvatureAt(i * 40f));
        curv /= Math.max(1, n);
        float score = scoreOffer(pay, km, fuelStops, sleepStops, curv);
        return new Offer(0L, km, pay, fuelStops, sleepStops, curv, score);
    }

    public static float scoreOffer(float pay, float km, int fuelStops,
                                   int sleepStops, float meanAbsCurv) {
        float net = pay - fuelStops * FUEL_STOP_EUR - sleepStops * HOTEL_EUR;
        return net / (Math.max(km, 0.1f) * (1f + CURVE_PENALTY * meanAbsCurv));
    }

    /** Generates n candidate roads and picks the best-scoring job. */
    public static Offer pickBest(Random rng, int n) {
        Offer best = null;
        for (int i = 0; i < n; i++) {
            long seed = (long) (rng.nextDouble() * 2.0e9) + 1L;
            SimWorld.Road road = SimWorld.Road.random(seed);
            Offer o = offer(rng, road);
            Offer full = new Offer(seed, o.km, o.payEur, o.fuelStops,
                    o.sleepStops, o.meanAbsCurv, o.score);
            if (best == null || full.score > best.score) best = full;
        }
        return best;
    }

    private Dispatcher() { }
}
