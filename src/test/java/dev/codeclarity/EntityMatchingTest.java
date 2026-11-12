package dev.codeclarity;

import dev.codeclarity.core.EntityMatcher;
import dev.codeclarity.core.model.SourceEntity;
import dev.codeclarity.core.model.SourceRange;
import java.util.List;
import static dev.codeclarity.core.EntityMatcher.Status.*;

public final class EntityMatchingTest {
    private static final SourceRange ALL = new SourceRange(1, 100);

    public static void main(String[] args) {
        var oldFunction = new SourceEntity("Service.f(self, x)", new SourceRange(2, 4), "Service.f");
        var newFunction = new SourceEntity("Service.f(self, x, y)", new SourceRange(8, 10), "Service.f");
        var result = match(List.of(oldFunction), List.of(newFunction), List.of(ALL), List.of(ALL), true, true);
        check(result.size() == 1 && result.getFirst().status() == MATCHED, "parameter change");
        check(result.getFirst().before().getFirst().signature().equals(oldFunction.signature()), "old signature retained");
        check(result.getFirst().displaySignature().equals(newFunction.signature()), "new signature displayed");

        result = match(List.of(oldFunction), List.of(newFunction), List.of(ALL), List.of(), true, true);
        check(result.size() == 1 && result.getFirst().status() == MATCHED, "deletion-only touch");
        check(match(List.of(oldFunction), List.of(newFunction), List.of(), List.of(), true, true).isEmpty(), "untouched excluded");

        var duplicate = new SourceEntity("Service.f(self, z)", new SourceRange(30, 32), "Service.f");
        result = match(List.of(oldFunction, duplicate), List.of(oldFunction),
                List.of(new SourceRange(3, 3)), List.of(), true, true);
        check(result.getFirst().status() == AMBIGUOUS && result.getFirst().before().size() == 2,
                "untouched duplicate prevents greedy exact matching");
        result = match(List.of(oldFunction), List.of(oldFunction, duplicate), List.of(ALL), List.of(ALL), true, true);
        check(result.getFirst().status() == AMBIGUOUS, "duplicate head");
        var ambiguousOwner = new SourceEntity("Service.f(self, x)", ALL, "Service.f", true);
        check(match(List.of(ambiguousOwner), List.of(oldFunction), List.of(ALL), List.of(ALL), true, true)
                .getFirst().status() == AMBIGUOUS, "adapter marks an ambiguous owner even with one candidate");

        var javaOld = new SourceEntity("Service#f(int)", ALL);
        var javaNew = new SourceEntity("Service#f(int, int)", ALL);
        check(javaOld.matchingKey().equals(javaOld.signature()) && javaOld.matchingWarning() == null
                && oldFunction.matchingWarning() == null && ambiguousOwner.matchingWarning() == null,
                "backward-compatible constructors default warnings to null");
        result = match(List.of(javaOld), List.of(javaNew), List.of(ALL), List.of(ALL), true, true);
        check(result.size() == 2 && result.get(0).status() == REMOVED && result.get(1).status() == ADDED,
                "Java default matching stays exact");

        var unsafe = new SourceEntity("Owner.anonymous(expression:1)#run()", ALL, null, false,
                "Lexical identity is unverified.");
        check(unsafe.matchingKey().equals(unsafe.signature()), "null canonical matching key defaults to signature");
        check(match(List.of(unsafe), List.of(unsafe), List.of(ALL), List.of(ALL), true, true)
                .getFirst().status() == UNVERIFIED, "unsafe identity is not a verified match");
        check(match(List.of(), List.of(unsafe), List.of(), List.of(ALL), true, true)
                .getFirst().status() == UNVERIFIED, "unsafe addition is not a verified added identity");
        var unsafeAmbiguous = new SourceEntity("Service.f(self, x)", ALL, "Service.f", true,
                "Enclosing identity is unverified.");
        check(match(List.of(unsafeAmbiguous), List.of(oldFunction), List.of(ALL), List.of(ALL), true, true)
                .getFirst().status() == AMBIGUOUS, "ambiguity retains precedence over identity warnings");

        result = match(List.of(oldFunction), List.of(), List.of(ALL), List.of(), true, false);
        check(result.getFirst().status() == UNVERIFIED, "parse failure is not removal");
        check(match(List.of(), List.of(newFunction), List.of(), List.of(ALL), true, true).getFirst().status() == ADDED,
                "new entity");
        check(match(List.of(oldFunction), List.of(), List.of(ALL), List.of(), true, true).getFirst().status() == REMOVED,
                "removed entity");
        var renamed = new SourceEntity("Service.g(self, x)", ALL, "Service.g");
        check(match(List.of(oldFunction), List.of(renamed), List.of(ALL), List.of(ALL), true, true).size() == 2,
                "renamed functions not guessed");
        System.out.println("Passed: adapter matching keys, parameter changes, duplicates, partial analysis, exact Java matching and unsafe identity warnings.");
    }

    private static List<EntityMatcher.Match> match(List<SourceEntity> before, List<SourceEntity> after,
                                                  List<SourceRange> oldLines, List<SourceRange> newLines,
                                                  boolean oldComplete, boolean newComplete) {
        return EntityMatcher.match(before, after, oldLines, newLines, oldComplete, newComplete);
    }

    private static void check(boolean value, String message) {
        if (!value) { throw new AssertionError(message); }
    }
}
