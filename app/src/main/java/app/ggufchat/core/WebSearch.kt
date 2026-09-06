package app.ggufchat.core

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit
import java.util.regex.Pattern

/**
 * Ferramenta de pesquisa: busca resultados e os injeta como contexto no prompt
 * (funciona com qualquer modelo instruct — sem depender de tool-calling).
 */
object WebSearch {

    private val client = OkHttpClient.Builder()
        .connectTimeout(12, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .followRedirects(true)
        .build()

    data class Result(val title: String, val snippet: String, val url: String)

    /** Busca via DuckDuckGo HTML (sem chave de API). */
    suspend fun search(query: String, max: Int = 5): List<Result> = withContext(Dispatchers.IO) {
        runCatching {
            val req = Request.Builder()
                .url("https://lite.duckduckgo.com/lite/?q=" + java.net.URLEncoder.encode(query, "UTF-8"))
                .header("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 GGUF-Chat/1.0")
                .build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) return@withContext emptyList()
                val html = resp.body?.string() ?: return@withContext emptyList()
                parseLite(html, max)
            }
        }.getOrDefault(emptyList())
    }

    private fun parseLite(html: String, max: Int): List<Result> {
        val out = ArrayList<Result>()
        // no lite.duckduckgo.com os resultados vêm em <a rel="nofollow" href="...">TITLE</a>
        // seguidos por um snippet na mesma linha de tabela
        val linkRe = Pattern.compile(
            """<a[^>]+rel="nofollow"[^>]+href="([^"]+)"[^>]*>(.*?)</a>""",
            Pattern.CASE_INSENSITIVE or Pattern.DOTALL
        )
        val snippetRe = Pattern.compile(
            """<td[^>]*class='result-snippet'[^>]*>(.*?)</td>""",
            Pattern.CASE_INSENSITIVE or Pattern.DOTALL
        )
        val snippets = ArrayList<String>()
        val sm = snippetRe.matcher(html)
        while (sm.find() && snippets.size < max) {
            snippets.add(htmlToText(sm.group(1)))
        }
        val lm = linkRe.matcher(html)
        var si = 0
        while (lm.find() && out.size < max) {
            var url = lm.group(1).trim()
            val title = htmlToText(lm.group(2)).trim()
            if (url.startsWith("//")) url = "https:$url"
            if (!url.startsWith("http") || title.isEmpty()) continue
            out.add(Result(title, snippets.getOrNull(si).orEmpty(), url))
            si++
        }
        return out
    }

    private fun htmlToText(html: String): String {
        var s = html.replace(Regex("<[^>]+>"), "")
        s = s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", "\"").replace("&#x27;", "'").replace("&nbsp;", " ")
            .replace(Regex("\\s+"), " ").trim()
        return s
    }

    /** Monta o texto final injetado na mensagem do usuário. */
    fun buildPrompt(query: String, results: List<Result>): String {
        val sb = StringBuilder()
        sb.append(
            "Você tem acesso aos seguintes resultados de pesquisa da web (em português, a menos que a pergunta " +
                    "seja em outro idioma). Responda à pergunta do usuário usando essas informações quando relevantes. " +
                    "Se os resultados não responderem, diga isso honestamente.\n\n"
        )
        sb.append("PESQUISA: ").append(query).append("\n\n")
        if (results.isEmpty()) {
            sb.append("(nenhum resultado encontrado)\n")
        } else {
            for ((i, r) in results.withIndex()) {
                sb.append("[").append(i + 1).append("] ").append(r.title).append("\n")
                sb.append("    ").append(r.snippet).append("\n")
                sb.append("    ").append(r.url).append("\n\n")
            }
        }
        sb.append("PERGUNTA DO USUÁRIO:\n").append(query)
        return sb.toString()
    }
}
