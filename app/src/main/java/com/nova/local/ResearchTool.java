package com.nova.local;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URLEncoder;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Privacy-conscious lightweight research tool. It only runs when the user enables Pesquisa. */
public final class ResearchTool {
    private ResearchTool() { }

    public static String search(String query) {
        if (query == null || query.trim().isEmpty()) return "";
        HttpURLConnection connection = null;
        try {
            String encoded = URLEncoder.encode(query.trim(), StandardCharsets.UTF_8.name());
            URL url = new URL("https://api.duckduckgo.com/?q=" + encoded
                    + "&format=json&no_html=1&skip_disambig=1");
            connection = (HttpURLConnection) url.openConnection();
            connection.setConnectTimeout(7000);
            connection.setReadTimeout(9000);
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("User-Agent", "NovaLocal/1.0 (Android)");
            if (connection.getResponseCode() != HttpURLConnection.HTTP_OK) return "";
            String json = read(connection.getInputStream());
            String abstractText = unescape(field(json, "AbstractText"));
            String heading = unescape(field(json, "Heading"));
            String source = unescape(field(json, "AbstractURL"));
            if (abstractText == null || abstractText.trim().isEmpty()) {
                abstractText = firstRelatedTopic(json);
            }
            if (abstractText == null || abstractText.trim().isEmpty()) return "";
            StringBuilder result = new StringBuilder();
            result.append("Pesquisa ao vivo — ");
            if (heading != null && !heading.isEmpty()) result.append(heading).append("\n");
            result.append(trim(abstractText, 1400));
            if (source != null && !source.isEmpty()) result.append("\nFonte: ").append(source);
            return result.toString();
        } catch (Throwable ignored) {
            return "";
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private static String read(InputStream stream) throws Exception {
        StringBuilder out = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            char[] buffer = new char[2048];
            int count;
            while ((count = reader.read(buffer)) != -1 && out.length() < 30000) {
                out.append(buffer, 0, count);
            }
        }
        return out.toString();
    }

    private static String field(String json, String key) {
        Matcher matcher = Pattern.compile("\\\"" + key + "\\\"\\s*:\\s*\\\"((?:\\\\.|[^\\\"])*)\\\"")
                .matcher(json == null ? "" : json);
        return matcher.find() ? matcher.group(1) : "";
    }

    private static String firstRelatedTopic(String json) {
        Matcher matcher = Pattern.compile("\\\"Text\\\"\\s*:\\s*\\\"((?:\\\\.|[^\\\"])*)\\\"")
                .matcher(json == null ? "" : json);
        return matcher.find() ? unescape(matcher.group(1)) : "";
    }

    private static String unescape(String value) {
        if (value == null) return "";
        return value.replace("\\n", "\n").replace("\\r", "\r")
                .replace("\\\"", "\"").replace("\\/", "/").replace("\\\\", "\\");
    }

    private static String trim(String text, int max) {
        String normalized = text.replaceAll("\\s+", " ").trim();
        return normalized.length() > max ? normalized.substring(0, max - 1) + "…" : normalized;
    }
}
