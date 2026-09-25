package com.ggufchat.app;

import java.net.ConnectException;
import java.net.UnknownHostException;
import java.net.SocketTimeoutException;

/** Prova, no host, que o orçamento da busca limita o tempo total de verdade.
 *
 * Compila o MESMO arquivo que o APK usa (apk-fix/java/.../SearchBudget.java) com
 * javac e o executa no JVM: sem emulador, sem rede e sem esperar minutos.
 */
public final class SearchBudgetSelfTest {
    private static int failures = 0;

    private static void check(String what, boolean ok, String detail) {
        System.out.println((ok ? "PASS " : "FAIL ") + what + (detail.isEmpty() ? "" : " (" + detail + ")"));
        if (!ok) failures++;
    }

    public static void main(String[] args) throws Exception {
        // 1. A fatia nunca passa do que resta, com relógio sintético.
        SearchBudget budget = new SearchBudget(1000, 0L);
        boolean bounded = true;
        for (long now = 0; now <= 1200; now += 37) {
            int remaining = budget.remainingMs(now);
            for (int configured : new int[]{1, 2, 250, 3000, 4000, 12000}) {
                int slice = budget.sliceMs(configured, now);
                if (slice > remaining) bounded = false;
                if (remaining == 0 && slice != 0) bounded = false;
                if (remaining > 0 && slice <= 0) bounded = false;
            }
        }
        check("fatia nunca excede o restante", bounded, "");

        // 2. Somando 4 tentativas no pior caso, o total não passa do orçamento.
        SearchBudget worst = new SearchBudget(400, 0L);
        long now = 0;
        int spent = 0;
        for (int i = 0; i < 4; i++) {
            int attempt = Math.min(worst.sliceMs(3000, now), worst.sliceMs(4000, now));
            now += attempt;
            spent += attempt;
            if (worst.remainingMs(now) <= 0) break;
        }
        check("quatro tentativas cabem no orçamento", spent <= 401, "gastou " + spent + " ms");

        // 3. Orçamento esgotado: nenhuma fatia nova.
        SearchBudget over = new SearchBudget(300, 0L);
        long after = 300L * 1000000L + 1;
        check("expirado não abre nova fatia",
              over.remainingMs(after) == 0 && over.sliceMs(4000, after) == 0, "");

        // 4. Falha de rede interrompe a cadeia de provedores; erro de conteúdo não.
        check("DNS/conexão/sem rota interrompem a cadeia",
              SearchBudget.connectivityFailure(new UnknownHostException("x"))
              && SearchBudget.connectivityFailure(new ConnectException("recusada"))
              && !SearchBudget.connectivityFailure(new SocketTimeoutException("leitura lenta"))
              && !SearchBudget.connectivityFailure(new IllegalStateException("HTTP 403")), "");

        // 5. Cronometrado de verdade: quatro provedores que nunca respondem, com teto
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

        // 6. Aviso de busca indisponível: o modelo não pode ser instruído a citar
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
