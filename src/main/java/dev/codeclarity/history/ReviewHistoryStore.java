package dev.codeclarity.history;

import java.io.IOException;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import static dev.codeclarity.history.HistoryJson.*;

import java.security.MessageDigest;
import java.time.Instant;
import java.util.HexFormat;
import java.util.Set;

/** Public history use cases. Persistence, validation and projections are separate collaborators. */
public final class ReviewHistoryStore {
    private final HistoryValidator validator;
    private final HistoryFileStorage storage;

    public ReviewHistoryStore(Path repositoryRoot) throws IOException {
        var root = repositoryRoot.toRealPath();
        validator = new HistoryValidator(root);
        storage = new HistoryFileStorage(root, validator);
    }

    public Map<String, Object> get() {
        try { return storage.read(); }
        catch (IOException exception) { throw new IllegalStateException("Could not read review history: " + exception.getMessage(), exception); }
    }

    public static Map<String, Object> updateInputSchema() { return HistoryValidator.updateInputSchema(); }

    public Map<String, Object> update(Map<String, Object> request) {
        HistoryValidator.validateUpdate(request);
        var input = copy(request);
        index(array(input.getOrDefault("categories", List.of())), "categoryId");
        return storage.mutate(history -> {
            var categories = index(array(history.get("categories")), "categoryId");
            for (var value : array(input.getOrDefault("categories", List.of()))) {
                var category = object(value);
                text(category, "name");
                var existing = categories.get(text(category, "categoryId"));
                if (existing == null) {
                    existing = new LinkedHashMap<>(category);
                    array(history.get("categories")).add(existing);
                    categories.put(text(category, "categoryId"), existing);
                } else {
                    existing.putAll(category);
                }
            }
            if (input.containsKey("review")) {
                var review = object(input.get("review"));
                validator.validateReview(review);
                var reviews = index(array(history.get("reviews")), "reviewId");
                var id = text(review, "reviewId");
                var existing = reviews.get(id);
                if (existing != null) {
                    require(existing.equals(review), "Conflicting payload for reviewId " + id);
                } else {
                    for (var stored : reviews.values()) {
                        require(!ReviewScope.of(stored).equals(ReviewScope.of(review)),
                                "Scope already stored as " + stored.get("reviewId") + "; reuse its original reviewId and payload.");
                    }
                    array(history.get("reviews")).add(review);
                }
                for (var finding : array(review.get("findings"))) {
                    var categoryId = text(object(finding), "categoryId");
                    if (!categories.containsKey(categoryId)) {
                        var category = new LinkedHashMap<String, Object>(Map.of("categoryId", categoryId, "name", categoryId));
                        array(history.get("categories")).add(category);
                        categories.put(categoryId, category);
                    }
                }
            }
        });
    }

    /** Local operator entrypoint only: deliberately unavailable as a model-supplied MCP parameter. */
    public Map<String, Object> recordFeedback(String reviewId, String findingId, String decision,
                                             String confirmedBy, String evidence) {
        require(Set.of("FIXED", "REJECTED").contains(decision), "Feedback decision must be FIXED or REJECTED.");
        require(confirmedBy != null && !confirmedBy.isBlank() && evidence != null && !evidence.isBlank(),
                "Feedback requires confirmed-by and evidence.");
        return storage.mutate(history -> {
            var finding = index(array(history.get("findings")), "findingId").get(findingId);
            require(finding != null && finding.get("reviewId").equals(reviewId), "Unknown review/finding pair.");
            var identity = List.of(reviewId, findingId, decision, confirmedBy, evidence);
            var id = "feedback-" + digest(JSON.writeValueAsBytes(identity));
            if (index(array(history.get("feedback")), "feedbackId").containsKey(id)) { return; }
            var event = new FeedbackEvent(id, reviewId, findingId, decision, "HUMAN", "LOCAL_CLI",
                    confirmedBy, evidence, Instant.now().toString());
            array(history.get("feedback")).add(event.toJson());
        });
    }

    private static String digest(byte[] bytes) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)); }
        catch (java.security.NoSuchAlgorithmException exception) { throw new IllegalStateException(exception); }
    }

}
