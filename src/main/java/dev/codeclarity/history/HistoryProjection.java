package dev.codeclarity.history;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import static dev.codeclarity.history.HistoryJson.*;

/** Deterministic projection of immutable reviews and feedback into findings, examples and counts. */
final class HistoryProjection {
    static void derive(Map<String, Object> history) {
        var reviews = index(array(history.get("reviews")), "reviewId");
        var categories = index(array(history.get("categories")), "categoryId");
        var findings = new LinkedHashMap<String, Map<String, Object>>();
        var scopes = new java.util.HashSet<ReviewScope>();
        for (var review : reviews.values()) {
            require(scopes.add(ReviewScope.of(review)), "Duplicate review scope.");
            for (var value : array(review.get("findings"))) {
                var finding = copy(object(value));
                var id = text(finding, "findingId");
                require(findings.putIfAbsent(id, finding) == null, "Duplicate findingId " + id);
                require(categories.containsKey(text(finding, "categoryId")), "Unknown finding category.");
                finding.put("status", "DETECTED");
            }
        }
        var feedback = index(array(history.get("feedback")), "feedbackId");
        for (var event : feedback.values()) {
            var finding = findings.get(text(event, "findingId"));
            require(finding != null && finding.get("reviewId").equals(event.get("reviewId")), "Feedback references an unknown finding.");
            finding.put("status", event.get("decision"));
        }
        for (var category : categories.values()) {
            text(category, "name");
            category.put("statistics", counts(List.of()));
            category.put("examples", new ArrayList<>());
        }
        for (var category : categories.values()) {
            var own = findings.values().stream().filter(f -> f.get("categoryId").equals(category.get("categoryId"))).toList();
            category.put("statistics", counts(own));
            List<Map<String, Object>> examples = new ArrayList<>();
            for (var finding : own) {
                Map<String, Object> example = new LinkedHashMap<>();
                for (var key : List.of("findingId", "reviewId", "snapshotId", "location", "description", "recommendation", "evidence", "status")) {
                    example.put(key, finding.get(key));
                }
                example.put("feedbackIds", feedback.values().stream().filter(f -> f.get("findingId").equals(finding.get("findingId")))
                        .map(f -> f.get("feedbackId")).toList());
                examples.add(example);
            }
            category.put("examples", examples);
        }
        history.put("findings", new ArrayList<>(findings.values()));
        var statistics = counts(new ArrayList<>(findings.values()));
        statistics.put("reviewCount", reviews.size());
        statistics.put("categoryCount", categories.size());
        history.put("statistics", statistics);
    }

    private static Map<String, Object> counts(List<? extends Map<String, Object>> findings) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("occurrenceCount", findings.size());
        for (var status : List.of("DETECTED", "FIXED", "REJECTED")) {
            result.put(status.toLowerCase(java.util.Locale.ROOT) + "Count", (int) findings.stream().filter(f -> status.equals(f.get("status"))).count());
        }
        return result;
    }

}
