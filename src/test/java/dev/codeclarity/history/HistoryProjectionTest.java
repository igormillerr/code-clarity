package dev.codeclarity.history;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import static dev.codeclarity.history.HistoryJson.*;

/** Domain projection checks independent of filesystem, locks, MCP and schema IO. */
public final class HistoryProjectionTest {
    public static void main(String[] args) {
        var scope = Map.of("repoRoot", "/nonexistent/history-projection-test", "baseSha", "base", "headSha", "head",
                "snapshotId", "head", "languages", List.of("java", "other"), "paths", List.of("b.java", "a.java"));
        var finding = new LinkedHashMap<String, Object>();
        finding.putAll(Map.of("findingId", "f1", "reviewId", "r1", "categoryId", "naming", "snapshotId", "head",
                "location", Map.of("path", "a.java", "startLine", 1, "endLine", 1), "description", "description",
                "recommendation", "recommendation", "evidence", List.of(), "status", "DETECTED"));
        var review = Map.<String, Object>of("reviewId", "r1", "scope", scope, "findings", List.of(finding));
        var original = copy(review);
        Map<String, Object> history = new LinkedHashMap<>();
        history.put("reviews", List.of(review));
        history.put("categories", new ArrayList<>(List.of(new LinkedHashMap<>(Map.of("categoryId", "naming", "name", "Names")),
                new LinkedHashMap<>(Map.of("categoryId", "unused", "name", "Unused")))));
        history.put("feedback", List.of(Map.of("feedbackId", "e1", "findingId", "f1", "reviewId", "r1", "decision", "FIXED"),
                Map.of("feedbackId", "e2", "findingId", "f1", "reviewId", "r1", "decision", "REJECTED")));
        HistoryProjection.derive(history);
        check(review.equals(original), "projection mutated immutable review source");
        check(object(history.get("statistics")).get("rejectedCount").equals(1), "last feedback wins");
        check(object(history.get("statistics")).get("fixedCount").equals(0), "old feedback must not inflate counts");
        var example = object(array(object(array(history.get("categories")).getFirst()).get("examples")).getFirst());
        check(example.get("feedbackIds").equals(List.of("e1", "e2")), "all feedback provenance retained");
        check(object(object(array(history.get("categories")).get(1)).get("statistics")).get("occurrenceCount").equals(0), "empty category counts");
        var first = copy(history);
        HistoryProjection.derive(history);
        check(history.equals(first), "projection must be deterministic and idempotent");
        var reordered = copy(review);
        object(reordered.get("scope")).put("languages", List.of("other", "java"));
        object(reordered.get("scope")).put("paths", List.of("a.java", "b.java"));
        check(ReviewScope.of(review).equals(ReviewScope.of(reordered)), "scope order must not change identity");
        reordered.put("reviewId", "r2");
        history.put("reviews", List.of(review, reordered));
        boolean rejected = false;
        try { HistoryProjection.derive(history); }
        catch (IllegalArgumentException expected) { rejected = true; }
        check(rejected, "duplicate scopes must be rejected without filesystem access");
        System.out.println("Passed: pure history projection, immutable review source, last feedback wins, provenance, empty categories and normalized scope identity.");
    }
    private static void check(boolean condition, String message) { if (!condition) { throw new AssertionError(message); } }
}
