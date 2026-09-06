package app.ggufchat.util

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Renderizador Markdown minimalista (negrito, itálico, código, links, listas, títulos). */
object Markdown {

    fun render(md: String, base: Color = Color.Unspecified): AnnotatedString {
        val lines = md.split("\n")
        val out = buildAnnotatedString {
            var inCode = false
            var listIdx = 0
            var emitted = false       // já escreveu algum conteúdo?
            var prevBlank = false     // a linha anterior era vazia?

            fun sep(p: Boolean = false) {
                if (!emitted) return
                append("\n")
                if (p) append("\n")
                prevBlank = false
            }

            for (raw in lines) {
                var line = raw
                val trimmed = line.trimStart()
                when {
                    trimmed.startsWith("```") -> {
                        if (inCode) {
                            inCode = false
                            prevBlank = false
                        } else {
                            inCode = true
                            if (emitted && !prevBlank) sep()
                        }
                        emitted = true
                        prevBlank = false
                        continue
                    }
                    inCode -> {
                        if (emitted && !prevBlank) sep()
                        pushStyle(SpanStyle(fontFamily = FontFamily.Monospace, color = base))
                        append(line)
                        pop()
                        emitted = true
                        prevBlank = false
                        continue
                    }
                }
                when {
                    trimmed.startsWith("### ") -> {
                        if (emitted && !prevBlank) sep()
                        withStyle(SpanStyle(fontWeight = FontWeight.Bold, fontSize = 15.sp)) {
                            append(trimmed.removePrefix("### "))
                        }
                    }
                    trimmed.startsWith("## ") -> {
                        if (emitted && !prevBlank) sep()
                        withStyle(SpanStyle(fontWeight = FontWeight.Bold, fontSize = 17.sp)) {
                            append(trimmed.removePrefix("## "))
                        }
                    }
                    trimmed.startsWith("# ") -> {
                        if (emitted && !prevBlank) sep()
                        withStyle(SpanStyle(fontWeight = FontWeight.Bold, fontSize = 19.sp)) {
                            append(trimmed.removePrefix("# "))
                        }
                    }
                    trimmed.startsWith("- ") || trimmed.startsWith("* ") || trimmed.startsWith("• ") -> {
                        if (emitted && !prevBlank) sep()
                        append(if (line.length - trimmed.length > 0) "    • " else "• ")
                        appendInline(trimmed.drop(2), base)
                    }
                    Regex("""^\d+[.)] """).containsMatchIn(trimmed) -> {
                        if (emitted && !prevBlank) sep()
                        listIdx++
                        append(if (line.length - trimmed.length > 0) "    " else "")
                        append("${listIdx}. ")
                        appendInline(trimmed.replaceFirst(Regex("""^\d+[.)] """), ""), base)
                    }
                    trimmed.startsWith("> ") -> {
                        if (emitted && !prevBlank) sep()
                        withStyle(SpanStyle(color = (base.takeIf { it != Color.Unspecified } ?: Color.Gray).copy(alpha = 0.8f))) {
                            appendInline(trimmed.removePrefix("> "), base)
                        }
                    }
                    line.isBlank() -> {
                        if (emitted && !inCode) {
                            append("\n")
                            prevBlank = true
                        }
                        continue
                    }
                    else -> {
                        if (emitted && !prevBlank) sep()
                        appendInline(trimmed, base)
                    }
                }
                emitted = true
                prevBlank = false
            }
        }
        return out
    }

    private fun androidx.compose.ui.text.AnnotatedString.Builder.appendInline(text: String, base: Color) {
        val parts = splitInline(text)
        for (p in parts) {
            when (p.type) {
                "code" -> withStyle(SpanStyle(fontFamily = FontFamily.Monospace, background = base.copy(alpha = 0.12f))) {
                    append(p.text)
                }
                "bold" -> withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(p.text) }
                "italic" -> withStyle(SpanStyle(fontStyle = FontStyle.Italic)) { append(p.text) }
                "bolditalic" -> withStyle(SpanStyle(fontWeight = FontWeight.Bold, fontStyle = FontStyle.Italic)) {
                    append(p.text)
                }
                "link" -> withStyle(SpanStyle(color = Color(0xFF4FC3F7), textDecoration = TextDecoration.Underline)) {
                    append(p.text)
                }
                else -> append(p.text)
            }
        }
    }

    private class Part(val type: String, val text: String)

    private fun splitInline(s: String): List<Part> {
        val parts = ArrayList<Part>()
        val sb = StringBuilder()
        var i = 0
        fun flush() {
            if (sb.isNotEmpty()) {
                parts.add(Part("text", sb.toString()))
                sb.clear()
            }
        }
        while (i < s.length) {
            if (s.startsWith("`", i)) {
                val end = s.indexOf('`', i + 1)
                if (end > 0) {
                    flush()
                    parts.add(Part("code", s.substring(i + 1, end)))
                    i = end + 1
                    continue
                }
            }
            if (s.startsWith("***", i)) {
                val end = s.indexOf("***", i + 3)
                if (end > 0) {
                    flush()
                    parts.add(Part("bolditalic", s.substring(i + 3, end)))
                    i = end + 3
                    continue
                }
            }
            if (s.startsWith("**", i)) {
                val end = s.indexOf("**", i + 2)
                if (end > 0) {
                    flush()
                    parts.add(Part("bold", s.substring(i + 2, end)))
                    i = end + 2
                    continue
                }
            }
            if (s.startsWith("*", i)) {
                val end = s.indexOf('*', i + 1)
                if (end > 0) {
                    flush()
                    parts.add(Part("italic", s.substring(i + 1, end)))
                    i = end + 1
                    continue
                }
            }
            if (s.startsWith("__", i)) {
                val end = s.indexOf("__", i + 2)
                if (end > 0) {
                    flush()
                    parts.add(Part("bold", s.substring(i + 2, end)))
                    i = end + 2
                    continue
                }
            }
            if (s.startsWith("[", i)) {
                val close = s.indexOf(']', i + 1)
                if (close > 0 && s.startsWith("(", close + 1)) {
                    val end = s.indexOf(')', close + 1)
                    if (end > 0) {
                        flush()
                        parts.add(Part("link", s.substring(i + 1, close)))
                        i = end + 1
                        continue
                    }
                }
            }
            sb.append(s[i])
            i++
        }
        flush()
        return parts
    }

    /** Divide o texto de um turno do assistente em (raciocínio, resposta). */
    fun splitThinking(raw: String): Pair<String, String> {
        var text = raw
        val patterns = listOf(
            Regex("<think>([\\s\\S]*?)</think>", RegexOption.IGNORE_CASE),
            Regex("<\\|thinking\\|>([\\s\\S]*?)<\\|/thinking\\|>"),
            Regex("<\\|start_thinking\\|>([\\s\\S]*?)<\\|end_thinking\\|>")
        )
        for (p in patterns) {
            val m = p.find(text)
            if (m != null) {
                val thinking = m.groupValues[1].trim()
                return thinking to text.removeRange(m.range).trim()
            }
        }
        return "" to text
    }
}

@Composable
fun CodeBlock(text: String, onCopy: () -> Unit) {
    val clipboard = LocalClipboardManager.current
    Column(
        Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surfaceContainerHighest)
            .padding(vertical = 4.dp)
    ) {
        Row(
            Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState())
                .padding(horizontal = 10.dp, vertical = 8.dp)
        ) {
            Text(
                text = AnnotatedString(text, SpanStyle(fontFamily = FontFamily.Monospace)),
                fontSize = 13.sp
            )
        }
        Text(
            text = "copiar",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.primary,
            modifier = Modifier
                .padding(start = 8.dp, bottom = 4.dp)
                .clickable {
                    clipboard.setText(AnnotatedString(text))
                    onCopy()
                }
        )
    }
}
