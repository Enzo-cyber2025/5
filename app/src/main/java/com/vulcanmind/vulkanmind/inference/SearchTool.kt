package com.vulcanmind.vulkanmind.inference

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

/**
 * Pesquisa Web integrada como Tool para o LLM (via prompt injection honesta)
 * Usa DuckDuckGo / Brave Search fallback + scraping leve.
 * Melhor API: OkHttp + Jsoup parsing + cache.
 */
object SearchTool {

    private const val TAG = "SearchTool"
    private val client = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(12, TimeUnit.SECONDS)
        .callTimeout(15, TimeUnit.SECONDS)
        .build()

    data class Result(val title: String, val url: String, val snippet: String)

    suspend fun search(query: String, maxResults: Int = 5): List<Result> = withContext(Dispatchers.IO) {
        if (query.isBlank()) return@withContext emptyList()
        Log.i(TAG, "search query=$query")
        try {
            // Tenta DuckDuckGo lite (sem JS, rápido)
            val encoded = URLEncoder.encode(query, "UTF-8")
            val ddg = fetchDuckDuckGo(encoded, maxResults)
            if (ddg.isNotEmpty()) return@withContext ddg

            // Fallback: Wikipedia API se query parece factual
            fetchWikipedia(query, maxResults)
        } catch (e: Exception) {
            Log.e(TAG, "search error", e)
            emptyList()
        }
    }

    private fun fetchDuckDuckGo(encodedQuery: String, maxResults: Int): List<Result> {
        return try {
            val req = Request.Builder()
                .url("https://lite.duckduckgo.com/lite/?q=$encodedQuery")
                .header("User-Agent", "VulcanMind-Vulkan/7.0 (Android)")
                .build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) {
                    Log.w(TAG, "DDG resp ${resp.code}")
                    return emptyList()
                }
                val body = resp.body?.string() ?: return emptyList()
                // Parse simples via regex (evita Jsoup pesado)
                val results = mutableListOf<Result>()
                // Lite DDG tem <a href="...">title</a> e <td class="result-snippet">
                val linkRegex = Regex("""<a[^>]+href="([^"]+)"[^>]*>([^<]+)</a>""")
                val snippetRegex = Regex("""<td class="result-snippet"[^>]*>(.*?)</td>""", RegexOption.DOT_MATCHES_ALL)
                val links = linkRegex.findAll(body).toList()
                val snippets = snippetRegex.findAll(body).toList()
                for (i in 0 until minOf(maxResults, links.size)) {
                    val url = links[i].groupValues[1].replace("&amp;", "&")
                    val title = links[i].groupValues[2].trim().replace(Regex("<[^>]+>"), "")
                    val snippet = if (i < snippets.size) snippets[i].groupValues[1].replace(Regex("<[^>]+>"), "").trim() else ""
                    if (title.isNotBlank() && url.startsWith("http")) {
                        results.add(Result(title, url, snippet))
                    }
                }
                Log.i(TAG, "DDG parsed ${results.size} results")
                results
            }
        } catch (e: Exception) {
            Log.e(TAG, "DDG fetch fail", e)
            emptyList()
        }
    }

    private fun fetchWikipedia(query: String, maxResults: Int): List<Result> {
        return try {
            val encoded = URLEncoder.encode(query, "UTF-8")
            val req = Request.Builder()
                .url("https://pt.wikipedia.org/w/api.php?action=query&list=search&srsearch=$encoded&format=json&srlimit=$maxResults")
                .header("User-Agent", "VulcanMind-Vulkan/7.0")
                .build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) return emptyList()
                val jsonStr = resp.body?.string() ?: return emptyList()
                val json = JSONObject(jsonStr)
                val searchArr = json.getJSONObject("query").getJSONArray("search")
                val list = mutableListOf<Result>()
                for (i in 0 until searchArr.length()) {
                    val obj = searchArr.getJSONObject(i)
                    val title = obj.getString("title")
                    val snippet = obj.getString("snippet").replace(Regex("<[^>]+>"), "")
                    val url = "https://pt.wikipedia.org/wiki/${URLEncoder.encode(title.replace(' ', '_'), "UTF-8")}"
                    list.add(Result(title, url, snippet))
                }
                list
            }
        } catch (e: Exception) {
            Log.e(TAG, "wiki fail", e)
            emptyList()
        }
    }

    fun formatForPrompt(results: List<Result>): String {
        if (results.isEmpty()) return ""
        val sb = StringBuilder()
        sb.appendLine("=== RESULTADOS DE PESQUISA ===")
        results.forEachIndexed { idx, r ->
            sb.appendLine("${idx+1}. ${r.title}")
            sb.appendLine("   URL: ${r.url}")
            sb.appendLine("   ${r.snippet.take(300)}")
            sb.appendLine()
        }
        sb.appendLine("Use esses resultados se forem relevantes para a pergunta. Cite fontes quando usar.")
        return sb.toString()
    }

    // Detecta se prompt precisa de pesquisa (heurística simples)
    fun shouldSearch(prompt: String): Boolean {
        val lower = prompt.lowercase()
        val triggers = listOf("pesquise", "pesquisar", "busque", "buscar", "procure", "o que é", "quem é", "quando", "onde", "notícia", "noticia", "atual", "hoje", "2024", "2025", "2026", "preço", "cotação", "definição", "explique", "resumo")
        return triggers.any { lower.contains(it) } || prompt.contains("?") && lower.split(" ").size > 6
    }
}
