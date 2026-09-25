package com.ggufchat.app;

/** O que o modelo é informado quando a busca não trouxe nada.
 *
 * O prompt de sistema dizia "se houver resultados de busca fornecidos abaixo,
 * baseie sua resposta neles e cite a fonte" mesmo quando a busca havia falhado e
 * nenhum resultado existia. Com isso o modelo era instruído a citar fontes que não
 * tinha à mão. Aqui a instrução é explícita: não há fontes, responda com o próprio
 * conhecimento e diga que não pesquisou.
 *
 * Classe pura (apenas java.*): o teste de host a executa.
 */
public final class SearchNotice {
    public static final String PREFIX = "BUSCA NA WEB INDISPONÍVEL NESTA RESPOSTA";

    private SearchNotice() {}

    /** Aviso injetado no lugar dos resultados, com o motivo declarado. */
    public static String failure(String reason) {
        String detail = reason == null || reason.trim().length() == 0 ? "motivo não informado" : reason.trim();
        return PREFIX + " (" + detail + "). Não há resultados de busca para citar: "
            + "responda com seu próprio conhecimento e diga que não pesquisou na web.";
    }

    /** O modelo foi avisado da indisponibilidade? (usado pelos testes e pelo log) */
    public static boolean declaresFailure(String text) {
        return text != null && text.startsWith(PREFIX);
    }
}
