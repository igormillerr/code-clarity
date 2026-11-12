package dev.codeclarity.history;

import java.io.IOException;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
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
    private static final Schema CANDIDATE_SCHEMA = schema("/contracts/rule-candidate.schema.json");
    private final Path root;

    HistoryValidator(Path root) { this.root = root; }

    static Map<String, Object> updateInputSchema() {
        return object(JSON.readValue(UPDATE_SCHEMA.getSchemaNode().toString(), Map.class));
    }

    static void validateUpdate(Map<String, Object> request) { validate(UPDATE_SCHEMA, request); }

    static Map<String, Object> candidateInputSchema() {
        return object(JSON.readValue(CANDIDATE_SCHEMA.getSchemaNode().toString(), Map.class));
    }

    static void validateCandidateRequest(Map<String, Object> request) { validate(CANDIDATE_SCHEMA, request); }

    void validateState(Map<String, Object> history) {
        validate(HISTORY_SCHEMA, history);
        for (var review : array(history.get("reviews"))) { validateReview(object(review)); }
        var derived = copy(history);
        HistoryProjection.derive(derived);
        require(derived.equals(history), "History statistics/findings/examples are inconsistent with reviews and feedback.");
        var candidates = index(array(history.get("ruleCandidates")), "candidateId");
        for (var candidate : candidates.values()) { validateCandidate(candidate, history, false); }
        var seen = new java.util.ArrayList<Map<String, Object>>();
        for (var candidate : candidates.values()) {
            require(seen.stream().noneMatch(previous -> equivalentCandidate(previous, candidate)), "Duplicate equivalent rule candidate.");
            seen.add(candidate);
        }
    }

    /** Validate eligibility at creation; historical proposals retain their original feedback provenance. */
    void validateCandidate(Map<String, Object> candidate, Map<String, Object> history, boolean requireLatestFeedback) {
        validateCandidateRequest(Map.of("candidate", candidate));
        for (var key : List.of("candidateId", "categoryId", "title", "description")) { text(candidate, key); }
        var categoryId = text(candidate, "categoryId");
        require(index(array(history.get("categories")), "categoryId").containsKey(categoryId), "Unknown candidate category.");
        var findings = index(array(history.get("findings")), "findingId");
        var supportingIds = new HashSet<>(array(candidate.get("supportingFindingIds")));
        var occurrences = new HashSet<List<Object>>();
        for (var value : supportingIds) {
            var finding = findings.get(value);
            require(finding != null && categoryId.equals(finding.get("categoryId")), "Candidate support must reference known findings of its category.");
            occurrences.add(occurrence(finding));
        }
        require(occurrences.size() >= 3, "Candidate requires at least three distinct source/snapshot occurrences.");
        var feedback = index(array(history.get("feedback")), "feedbackId");
        var latest = new LinkedHashMap<String, Map<String, Object>>();
        for (var event : feedback.values()) { latest.put(text(event, "findingId"), event); }
        var fixedOccurrences = new HashSet<List<Object>>();
        for (var value : array(candidate.get("confirmedFeedbackIds"))) {
            var event = feedback.get(value);
            require(event != null && supportingIds.contains(event.get("findingId")), "Candidate feedback must reference a supporting finding.");
            var finding = findings.get(text(event, "findingId"));
            require(event.get("reviewId").equals(finding.get("reviewId")) && "FIXED".equals(event.get("decision"))
                    && "HUMAN".equals(event.get("source")) && "LOCAL_CLI".equals(event.get("authority")),
                    "Candidate requires independently recorded operator FIXED feedback.");
            text(event, "confirmedBy");
            text(event, "confirmationEvidence");
            require(!requireLatestFeedback || event.equals(latest.get(text(event, "findingId"))),
                    "Candidate must cite the latest authoritative FIXED event for every confirmed finding.");
            fixedOccurrences.add(occurrence(finding));
        }
        require(fixedOccurrences.size() >= 2, "Candidate requires two distinct operator-confirmed FIXED occurrences.");
        for (var example : index(array(candidate.get("examples")), "findingId").values()) {
            var id = text(example, "findingId");
            require(supportingIds.contains(id), "Candidate example must reference a supporting finding.");
            var finding = findings.get(id);
            for (var entry : example.entrySet()) {
                require(entry.getValue().equals(finding.get(entry.getKey())), "Candidate example must match stored source evidence: " + entry.getKey());
            }
        }
    }

    static boolean equivalentCandidate(Map<String, Object> first, Map<String, Object> second) {
        return first.get("categoryId").equals(second.get("categoryId"))
                && (normalizedTitle(first).equals(normalizedTitle(second))
                || new HashSet<>(array(first.get("supportingFindingIds"))).equals(new HashSet<>(array(second.get("supportingFindingIds")))));
    }

    private static String normalizedTitle(Map<String, Object> candidate) {
        return text(candidate, "title").strip().replaceAll("\\s+", " ").toLowerCase(Locale.ROOT);
    }

    private static List<Object> occurrence(Map<String, Object> finding) {
        var location = object(finding.get("location"));
        return List.of(finding.get("snapshotId"), location.get("path"), location.get("startLine"), location.get("endLine"));
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
