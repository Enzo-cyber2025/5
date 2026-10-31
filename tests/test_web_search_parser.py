"""Compile and exercise the Android-independent HTML parsing portion of WebSearch."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_duckduckgo_result_extraction_and_citation_sanitization(tmp_path):
    javac = shutil.which("javac")
    java = shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required; GitHub Actions supplies Temurin")

    src = tmp_path / "src"
    log = src / "android/util/Log.java"
    log.parent.mkdir(parents=True)
    log.write_text('''package android.util;
public final class Log {
    public static int w(String tag, String message, Throwable error) { return 0; }
}
''')
    harness = src / "com/ggufchat/app/WebSearchParserTest.java"
    harness.parent.mkdir(parents=True)
    harness.write_text(r'''package com.ggufchat.app;
import java.lang.reflect.Method;
import java.util.List;
public final class WebSearchParserTest {
    public static void main(String[] args) throws Exception {
        Method parse = WebSearch.class.getDeclaredMethod("parse", String.class, int.class);
        parse.setAccessible(true);
        String html = "<a class=\"result__a\" href=\"https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fsource&amp;rut=abc\">Caf&#233; &amp; <b>GGUF</b></a>" +
            "<a class=\"result__snippet\" href=\"#\">Fact&nbsp;with &#x1F512;</a>" +
            "<a class=\"result__a\" href=\"javascript:alert(1)\">unsafe</a>" +
            "<a class=\"result__snippet\" href=\"#\">ignore</a>";
        @SuppressWarnings("unchecked")
        List<WebSearch.Result> results = (List<WebSearch.Result>) parse.invoke(null, html, 8);
        assert results.size() == 1 : results.size();
        Object row = results.get(0);
        java.lang.reflect.Field title = row.getClass().getField("title");
        java.lang.reflect.Field url = row.getClass().getField("url");
        java.lang.reflect.Field snippet = row.getClass().getField("snippet");
        assert "Café & GGUF".equals(title.get(row)) : title.get(row);
        assert "https://example.org/source".equals(url.get(row)) : url.get(row);
        assert ((String) snippet.get(row)).contains("🔒") : snippet.get(row);
        String prompt = WebSearch.toPromptText(results);
        assert prompt.contains("dados externos não confiáveis");
        assert prompt.contains("https://example.org/source");
        assert WebSearch.toPromptText(null).contains("não retornou resultados verificáveis");
    }
}
''')
    out = tmp_path / "classes"
    out.mkdir()
    subprocess.run([
        javac, "--release", "8", "-d", str(out), str(log),
        str(ROOT / "apk-fix/java/com/ggufchat/app/WebSearch.java"), str(harness),
    ], check=True)
    subprocess.run([java, "-ea", "-cp", str(out), "com.ggufchat.app.WebSearchParserTest"], check=True)
