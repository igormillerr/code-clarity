package dev.codeclarity.core;

import dev.codeclarity.core.model.SourceEntity;
import dev.codeclarity.core.model.SourceRange;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;

/** Matches only unique adapter-provided keys within a Git file pair. */
public final class EntityMatcher {
    private EntityMatcher() {}

    public enum Status { MATCHED, ADDED, REMOVED, AMBIGUOUS, UNVERIFIED }

    public record Match(String key, Status status, List<SourceEntity> before, List<SourceEntity> after) {
        public Match {
            before = List.copyOf(before);
            after = List.copyOf(after);
        }

        public String displaySignature() {
            if (after.size() == 1) { return after.getFirst().signature(); }
            if (before.size() == 1) { return before.getFirst().signature(); }
            return key;
        }
    }

    public static List<Match> match(List<SourceEntity> before, List<SourceEntity> after,
                                    List<SourceRange> baseLines, List<SourceRange> headLines,
                                    boolean baseComplete, boolean headComplete) {
        var oldGroups = group(before);
        var newGroups = group(after);
        var keys = new LinkedHashSet<>(oldGroups.keySet());
        keys.addAll(newGroups.keySet());
        List<Match> matches = new ArrayList<>();
        for (String key : keys) {
            var oldCandidates = oldGroups.getOrDefault(key, List.of());
            var newCandidates = newGroups.getOrDefault(key, List.of());
            if (!touched(oldCandidates, baseLines) && !touched(newCandidates, headLines)) {
                continue;
            }
            Status status;
            if (oldCandidates.size() > 1 || newCandidates.size() > 1
                    || oldCandidates.stream().anyMatch(SourceEntity::matchingAmbiguous)
                    || newCandidates.stream().anyMatch(SourceEntity::matchingAmbiguous)) {
                status = Status.AMBIGUOUS;
            } else if (!baseComplete || !headComplete
                    || oldCandidates.stream().anyMatch(entity -> entity.matchingWarning() != null)
                    || newCandidates.stream().anyMatch(entity -> entity.matchingWarning() != null)) {
                status = Status.UNVERIFIED;
            } else if (oldCandidates.isEmpty()) {
                status = Status.ADDED;
            } else if (newCandidates.isEmpty()) {
                status = Status.REMOVED;
            } else {
                status = Status.MATCHED;
            }
            matches.add(new Match(key, status, oldCandidates, newCandidates));
        }
        return List.copyOf(matches);
    }

    private static Map<String, List<SourceEntity>> group(List<SourceEntity> entities) {
        Map<String, List<SourceEntity>> groups = new LinkedHashMap<>();
        for (var entity : entities) {
            groups.computeIfAbsent(entity.matchingKey(), ignored -> new ArrayList<>()).add(entity);
        }
        return groups;
    }

    private static boolean touched(List<SourceEntity> entities, List<SourceRange> ranges) {
        return entities.stream().anyMatch(entity -> ranges.stream().anyMatch(entity.lines()::overlaps));
    }
}
