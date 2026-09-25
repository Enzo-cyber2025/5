package com.ggufchat.app;

import java.net.ConnectException;
import java.net.NoRouteToHostException;
import java.net.UnknownHostException;

/** Teto de tempo e política de rede da busca na web.
 *
 * Sem teto, o aplicativo tentava quatro provedores em sequência, cada um com oito
 * segundos de conexão e doze de leitura: quando nenhum respondia (sem rede, rede
 * cativa, provedor bloqueando), a mensagem ficava minutos em "Pesquisando na web"
 * — antes de o modelo sequer carregar — e o usuário concluía que a resposta não
 * vinha. O orçamento aqui é único para a busca inteira: cada requisição usa, no
 * máximo, o que ainda resta do teto, então a soma não passa dele. Esgotado o
 * orçamento (ou comprovada uma falha de rede), a resposta é gerada sem fontes e o
 * painel diz exatamente por quê.
 *
 * Classe pura (apenas java.*): o mesmo código é compilado e executado pelo teste
 * de host, sem emulador, com relógio sintético.
 */
public final class SearchBudget {
    public static final int DEFAULT_MS = 12000;
    public static final int MIN_MS = 250;
    /** Abaixo disto o orçamento está gasto: nenhuma requisição nova é aberta.
     *  Importa porque zero, num timeout de HttpURLConnection, quer dizer "sem
     *  limite" — tentar com zero traria a espera infinita de volta. */
    public static final int MIN_SLICE_MS = 50;
    public static final String PROPERTY = "debug.gguf.search_budget_ms";

    private final int totalMs;
    private final long startNanos;

    public SearchBudget() {
        this(configuredMs(), System.nanoTime());
    }

    SearchBudget(int totalMs, long startNanos) {
        this.totalMs = totalMs >= MIN_MS ? totalMs : DEFAULT_MS;
        this.startNanos = startNanos;
    }

    public int totalMs() {
        return totalMs;
    }

    public int remainingMs() {
        return remainingMs(System.nanoTime());
    }

    int remainingMs(long nowNanos) {
        long leftNanos = startNanos + (long) totalMs * 1000000L - nowNanos;
        if (leftNanos <= 0) return 0;
        long millis = leftNanos / 1000000L;
        return millis > Integer.MAX_VALUE ? Integer.MAX_VALUE : (int) millis;
    }

    public boolean expired() {
        return remainingMs() <= 0;
    }

    /** Fatia de tempo de uma requisição: nunca maior que o resto do orçamento. */
    public int sliceMs(int configured) {
        return sliceMs(configured, System.nanoTime());
    }

    int sliceMs(int configured, long nowNanos) {
        int remaining = remainingMs(nowNanos);
        if (remaining < MIN_SLICE_MS) return 0;
        return Math.min(configured, remaining);
    }

    /** Fatias de conexão e leitura de UMA requisição.
     *
     * Cada fase recebe, no máximo, metade do que resta do orçamento, então a soma
     * das duas nunca passa do restante — e o total da busca nunca passa do teto,
     * tentativa após tentativa. Com o orçamento quase esgotado devolve {0,0}: a
     * requisição não é aberta.
     */
    public int slices(int connectConfigured, int readConfigured) {
        return slices(connectConfigured, readConfigured, System.nanoTime());
    }

    int[] slices(int connectConfigured, int readConfigured, long nowNanos) {
        int remaining = remainingMs(nowNanos);
        if (remaining < MIN_SLICE_MS) return new int[]{0, 0};
        int share = remaining / 2;
        return new int[]{Math.min(connectConfigured, share), Math.min(readConfigured, share)};
    }

    /** Falha de rede (DNS, conexão recusada, sem rota) invalida os demais provedores. */
    public static boolean connectivityFailure(Throwable error) {
        Throwable current = error;
        while (current != null) {
            if (current instanceof UnknownHostException
                || current instanceof ConnectException
                || current instanceof NoRouteToHostException) return true;
            current = current == current.getCause() ? null : current.getCause();
        }
        return false;
    }

    public static int configuredMs() {
        try {
            String value = (String) Class.forName("android.os.SystemProperties")
                .getMethod("get", String.class, String.class)
                .invoke(null, PROPERTY, "");
            if (value != null && value.length() > 0) {
                return Math.max(MIN_MS, Integer.parseInt(value.trim()));
            }
        } catch (Throwable ignored) {
            // Sem a propriedade (ou sem Android): teto padrão.
        }
        return DEFAULT_MS;
    }
}
