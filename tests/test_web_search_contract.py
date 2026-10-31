from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "apk-fix/java/com/ggufchat/app/WebSearch.java"


def test_search_helper_keeps_existing_generation_api():
    source = SOURCE.read_text()
    assert re.search(r"public static List<Result> search\(String query, int requestedLimit\)", source)
    assert re.search(r"public static String toPromptText\(List<Result> results\)", source)
    # GenerationService already calls this helper only when the user enables
    # webSearch; preserving these signatures lets the existing call sites work.


def test_search_has_bounded_network_and_parse_work():
    source = SOURCE.read_text()
    assert "MAX_RESPONSE_BYTES = 1024 * 1024" in source
    assert "MAX_QUERY_CHARS = 600" in source
    assert "MAX_RESULTS = 8" in source
    assert "setConnectTimeout(CONNECT_TIMEOUT_MS)" in source
    assert "setReadTimeout(READ_TIMEOUT_MS)" in source
    assert 'https://html.duckduckgo.com/html/?q=' in source
    assert 'https://lite.duckduckgo.com/lite/?q=' in source
    assert "readBounded(connection.getInputStream())" in source


def test_results_are_cited_and_marked_untrusted_and_network_fails_open():
    source = SOURCE.read_text()
    assert "URL: " in source
    assert "dados externos não confiáveis" in source
    assert "continuing with local model" in source
    assert "não retornou resultados verificáveis" in source
    # Links must be web URLs, never javascript:, file:, or arbitrary schemes.
    assert 'scheme.equalsIgnoreCase("http") || scheme.equalsIgnoreCase("https")' in source
