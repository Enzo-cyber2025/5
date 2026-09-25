package com.ggufchat.app;

import java.net.ConnectException;
import java.net.UnknownHostException;
import java.net.SocketTimeoutException;

/** Prova, no host, que o orçamento da busca limita o tempo total de verdade.
 *
 * Compila o MESMO arquivo que o APK usa (apk-fix/java/.../SearchBudget.java) com
 * javac e o executa no JVM: sem emulador, sem rede e sem esperar minutos.
 *
 * O relógio é sintético na maior parte dos casos, em nanossegundos — as duas
 * unidades do código. Isso já pegou um erro real: avançar o relógio em
 * milissegundos fazia "quatro tentativas caberem no orçamento" passar por engano
 * enquanto o teste deveria reprovar.
 */
public final class SearchBudgetSelfTest {
    private static int failures = 0;

    private static void check(String what, boolean ok, String detail) {
        System.out.println((ok ? "PASS " : "FAIL ") + what + (detail.isEmpty() ? "" : " (" + detail + ")"));
        if (!ok) failures++;
    }

    public static void main(String[] args) throws Exception {
        // 1. Uma fatia nunca passa do pedido nem do que resta; some quando o
        //    orçamento está gasto (zero significaria "sem limite" na rede).
        SearchBudget budget = new SearchBudget(1000, 0L);
        boolean bounded = true;
        boolean useful = true;
        for (long now = 0; now <= 1200L * 1000000L; now += 37L * 1000000L) {
            int remaining = budget.remainingMs(now);
            for (int configured : new int[]{1, 2, 250, 3000, 4000, 12000}) {
                int slice = budget.sliceMs(configured, now);
                if (slice > remaining || slice > configured) bounded = false;
                if (remaining < SearchBudget.MIN_SLICE_MS && slice != 0) bounded = false;
                if (slice != 0 && slice < SearchBudget.MIN_SLICE_MS) useful = false;
            }
        }
        check("fatia nunca excede o restante nem o pedido", bounded, "");
        check("abaixo do mínimo útil a fatia é zero", useful, "");

        // 2. Conexão + leitura de UMA requisição cabem no que resta do orçamento.
        boolean fits = true;
        for (long now = 0; now <= 1200L * 1000000L; now += 23L * 1000000L) {
            int remaining = budget.remainingMs(now);
            int[] slices = budget.slices(3000, 4000, now);
            if (slices.length != 2) fits = false;
            if (slices[0] < 0 || slices[1] < 0) fits = false;
            if (slices[0] > 3000 || slices[1] > 4000) fits = false;
            if (slices[0] + slices[1] > remaining) fits = false;
            boolean stopped = slices[0] == 0 && slices[1] == 0;
            if (stopped != (remaining < SearchBudget.MIN_SLICE_MS)) fits = false;
        }
        check("conexão+leitura cabem no restante", fits, "");

        // 3. Somando quatro tentativas no pior caso, o total não passa do orçamento.
        //    O relógio caminha em nanossegundos, como no aplicativo.
        SearchBudget worst = new SearchBudget(400, 0L);
        long now = 0;
        int spent = 0;
        for (int i = 0; i < 4; i++) {
            int[] slices = worst.slices(3000, 4000, now);
            int attempt = slices[0] + slices[1];
            if (attempt <= 0) break;
            now += (long) attempt * 1000000L;  // cada tentativa gasta a própria fatia
            spent += attempt;
            if (worst.remainingMs(now) < SearchBudget.MIN_SLICE_MS) break;
        }
        check("quatro tentativas cabem no orçamento", spent <= 400, "gastou " + spent + " ms");

        // 4. Orçamento esgotado: nenhuma fatia nova, nem por tempo pedido grande.
        SearchBudget over = new SearchBudget(300, 0L);
        long after = 300L * 1000000L + 1;
        int[] none = over.slices(3000, 4000, after);
        check("expirado não abre nova fatia",
              over.remainingMs(after) == 0 && over.sliceMs(4000, after) == 0
              && none[0] == 0 && none[1] == 0, "");

        // 5. Falha de rede interrompe a cadeia de provedores; erro de conteúdo não.
        check("DNS/conexão/sem rota interrompem a cadeia",
              SearchBudget.connectivityFailure(new UnknownHostException("x"))
              && SearchBudget.connectivityFailure(new ConnectException("recusada"))
              && !SearchBudget.connectivityFailure(new SocketTimeoutException("leitura lenta"))
              && !SearchBudget.connectivityFailure(new IllegalStateException("HTTP 403")), "");

        // 6. Cronometrado de verdade: quatro provedores que nunca respondem, com teto
        //    de 400 ms, devem terminar perto de 400 ms — não em minutos.
        long started = System.nanoTime();
        SearchBudget real = new SearchBudget(400, System.nanoTime());
        for (int i = 0; i < 4 && !real.expired(); i++) {
            int slice = real.sliceMs(5000);
            if (slice <= 0) break;
            Thread.sleep(slice);
        }
        long elapsedMs = (System.nanoTime() - started) / 1000000L;
        check("quatro timeouts terminam dentro do teto", elapsedMs <= 700, "levou " + elapsedMs + " ms");

        // 7. Aviso de busca indisponível: o modelo não pode ser instruído a citar
        //    fontes que não existem.
        String notice = SearchNotice.failure("orçamento de 12000 ms esgotado");
        check("aviso declara o motivo e a ausência de fontes",
              SearchNotice.declaresFailure(notice)
              && notice.indexOf("orçamento de 12000 ms esgotado") >= 0
              && notice.indexOf("não pesquisou") >= 0
              && !notice.toLowerCase().contains("abaixo"), notice);
        check("aviso sem motivo ainda é explícito",
              SearchNotice.declaresFailure(SearchNotice.failure(null))
              && SearchNotice.failure("  ").indexOf("motivo não informado") >= 0, "");
        check("texto de resultados não é confundido com aviso",
              !SearchNotice.declaresFailure("RESULTADOS DE BUSCA NA WEB"), "");

        System.out.println(failures == 0 ? "SEARCH_BUDGET_OK" : "SEARCH_BUDGET_FAILURES=" + failures);
        if (failures != 0) System.exit(1);
    }
}
