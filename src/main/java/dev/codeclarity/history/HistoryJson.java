package dev.codeclarity.history;

import tools.jackson.core.StreamReadFeature;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.json.JsonMapper;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Strict JSON boundary shared by storage and schema validation. */
final class HistoryJson {
    static final JsonMapper JSON = JsonMapper.builder()
            .enable(StreamReadFeature.STRICT_DUPLICATE_DETECTION)
            .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).build();
    static Map<String, Map<String, Object>> index(List<Object> values, String key) {
        var result = new LinkedHashMap<String, Map<String, Object>>();
        for (var value : values) {
            var object = object(value);
            var id = text(object, key);
            require(result.putIfAbsent(id, object) == null, "Duplicate " + key + ": " + id);
        }
        return result;
    }

    static String text(Map<String, Object> object, String key) {
        require(object.get(key) instanceof String s && !s.isBlank(), "Missing non-empty " + key);
        return (String) object.get(key);
    }
    @SuppressWarnings("unchecked")
    static Map<String, Object> object(Object value) {
        require(value instanceof Map<?, ?>, "Expected a JSON object.");
        return (Map<String, Object>) value;
    }
    @SuppressWarnings("unchecked")
    static List<Object> array(Object value) {
        require(value instanceof List<?>, "Expected a JSON array.");
        return (List<Object>) value;
    }
    static Map<String, Object> copy(Map<String, Object> value) { return object(JSON.readValue(JSON.writeValueAsBytes(value), Map.class)); }
    static void require(boolean condition, String message) { if (!condition) { throw new IllegalArgumentException(message); } }
}
