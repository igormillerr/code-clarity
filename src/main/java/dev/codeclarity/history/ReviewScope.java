package dev.codeclarity.history;

import java.util.List;
import java.util.Map;
import static dev.codeclarity.history.HistoryJson.*;

/** Review identity within a repository; repository ownership is validated separately. */
record ReviewScope(String baseSha, String headSha, String snapshotId, List<String> languages, List<String> paths) {
    static ReviewScope of(Map<String, Object> review) {
        var scope = object(review.get("scope"));
        return new ReviewScope(text(scope, "baseSha"), text(scope, "headSha"), text(scope, "snapshotId"),
                array(scope.get("languages")).stream().map(Object::toString).sorted().toList(),
                array(scope.get("paths")).stream().map(Object::toString).sorted().toList());
    }
}
