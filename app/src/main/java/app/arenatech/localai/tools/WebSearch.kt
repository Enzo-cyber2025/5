package app.arenatech.localai.tools

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/**
 * Lightweight no-API-key web search used by the "pesquisa" tool.
 * Uses DuckDuckGo's Instant Answer API; only on the caller's IO dispatcher.
 */
object WebSearch {

    private const val TIMEOUT_MS = 12_000
    private const val MAX_RESULTS = 6

    suspend fun search(query: String): String = try {
        val encoded = URLEncoder.encode(query.trim(), "UTF-8")
        val url = "https://api.duckduckgo.com/?q=$encoded&format=json&no_html=1&skip_disambig=1&t=localai"
        val body = fetch(url) ?: return "Sem resultado da pesquisa para \"$query\"."
        val root = JSONObject(body)
        val sb = StringBuilder()

        val heading = root.optString("Heading")
        val abstractText = root.optString("AbstractText")
        if (abstractText.isNotBlank()) {
            sb.append("RESUMO: ").append(abstractText).append('\n')
            root.optString("AbstractURL").takeIf { it.isNotBlank() }?.let { sb.append("Fonte: ").append(it).append('\n') }
        } else if (heading.isNotBlank()) {
            sb.append(heading).append('\n')
        }

        val topics = root.optJSONArray("RelatedTopics") ?: root.optJSONArray("Topics")
        var count = 0
        if (topics != null) {
            for (i in 0 until topics.length()) {
                if (count >= MAX_RESULTS) break
                val t = topics.optJSONObject(i) ?: continue
                val text = t.optString("Text")
                val urlv = t.optString("FirstURL")
                if (text.isNotBlank()) {
                    sb.append("• ").append(text)
                    if (urlv.isNotBlank()) sb.append("\n  $urlv")
                    sb.append('\n')
                    count++
                }
            }
        }
        if (sb.isBlank()) "Nenhum resultado instantâneo encontrado para \"$query\"." else sb.toString().trim()
    } catch (e: Exception) {
        "Erro na pesquisa: ${e.message ?: e.javaClass.simpleName}"
    }

    private fun fetch(urlString: String): String? {
        val conn = (URL(urlString).openConnection() as HttpURLConnection).apply {
            connectTimeout = TIMEOUT_MS
            readTimeout = TIMEOUT_MS
            requestMethod = "GET"
            setRequestProperty("User-Agent", "LocalAI-Android/1.0")
        }
        return try {
            if (conn.responseCode in 200..299) {
                conn.inputStream.bufferedReader().use { it.readText() }
            } else null
        } finally {
            conn.disconnect()
        }
    }
}
