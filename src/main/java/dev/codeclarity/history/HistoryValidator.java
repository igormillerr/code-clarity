package dev.codeclarity.history;

import java.io.IOException;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import static dev.codeclarity.history.HistoryJson.*;

import com.networknt.schema.InputFormat;
import com.networknt.schema.Schema;
import com.networknt.schema.SchemaRegistry;
import com.networknt.schema.SpecificationVersion;

/** Schema and repository/domain invariants; performs no history-file writes. */
final class HistoryValidator {
    private static final Schema REVIEW_SCHEMA = schema("/contracts/review.schema.json");
    private static final Schema HISTORY_SCHEMA = schema("/contracts/review-history.schema.json");
    private static final Schema UPDATE_SCHEMA = schema("/contracts/history-update.schema.json");
    private final Path root;

    HistoryValidator(Path root) { this.root = root; }

    static Map<String, Object> updateInputSchema() {
        return object(JSON.readValue(UPDATE_SCHEMA.getSchemaNode().toString(), Map.class));
    }

    static void validateUpdate(Map<String, Object> request) { validate(UPDATE_SCHEMA, request); }

    void validateState(Map<String, Object> history) {
        validate(HISTORY_SCHEMA, history);
        for (var review : array(history.get("reviews"))) { validateReview(object(review)); }
        var derived = copy(history);
        HistoryProjection.derive(derived);
        require(derived.equals(history), "History statistics/findings/examples are inconsistent with reviews and feedback.");
    }

    void validateReview(Map<String, Object> review) {
        validate(REVIEW_SCHEMA, review);
        var scope = object(review.get("scope"));
        require(repositoryIdentity(text(scope, "repoRoot")).equals(root), "Review belongs to a different repository.");
        require(scope.get("snapshotId").equals(scope.get("headSha")), "Snapshot must equal headSha.");
        require("NOT_RUN".equals(object(review.get("ruleDiscovery")).get("status")), "Persist the stable pre-discovery report (NOT_RUN).");
        require(!Boolean.TRUE.equals(review.get("synthetic")), "Synthetic demonstration history cannot be imported.");
        for (var value : array(review.get("findings"))) {
            var finding = object(value);
            require(finding.get("reviewId").equals(review.get("reviewId")), "Finding reviewId mismatch.");
            require(!Boolean.TRUE.equals(finding.get("synthetic")), "Synthetic finding cannot be imported.");
            require(!finding.containsKey("status") || "DETECTED".equals(finding.get("status")), "New findings must be DETECTED.");
            require(List.of(scope.get("baseSha"), scope.get("headSha")).contains(finding.get("snapshotId")), "Finding snapshot mismatch.");
            var location = object(finding.get("location"));
            var path = text(location, "path");
            require(!path.startsWith("/") && !path.contains("\\") && !path.contains(":") && path.indexOf('\0') < 0
                    && java.util.Arrays.stream(path.split("/", -1)).noneMatch(p -> p.isEmpty() || p.equals(".") || p.equals("..")),
                    "Finding path must be repository-relative.");
            require(((Number) location.get("endLine")).intValue() >= ((Number) location.get("startLine")).intValue(), "Invalid finding range.");
        }
    }

    private static Path repositoryIdentity(String path) {
        try { return Path.of(path).toRealPath(); }
        catch (IOException exception) { throw new IllegalArgumentException("Review repository is unavailable: " + path, exception); }
    }

    private static Schema schema(String name) {
        try (var resource = ReviewHistoryStore.class.getResourceAsStream(name)) {
            if (resource == null) { throw new IllegalStateException("Missing history contract " + name); }
            return SchemaRegistry.withDefaultDialect(SpecificationVersion.DRAFT_2020_12).getSchema(resource, InputFormat.JSON);
        } catch (IOException exception) { throw new IllegalStateException("Could not load history contract.", exception); }
    }

    private static void validate(Schema schema, Object value) {
        var errors = schema.validate(JSON.writeValueAsString(value), InputFormat.JSON);
        require(errors.isEmpty(), "Invalid history/review JSON: " + errors);
    }

}
