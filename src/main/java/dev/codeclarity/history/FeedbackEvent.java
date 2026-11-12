package dev.codeclarity.history;

import java.util.Map;
import static dev.codeclarity.history.HistoryJson.*;

/** Operator feedback serialized at the JSON boundary using the existing history contract. */
record FeedbackEvent(String feedbackId, String reviewId, String findingId, String decision,
                     String source, String authority, String confirmedBy, String confirmationEvidence, String recordedAt) {
    Map<String, Object> toJson() { return object(JSON.readValue(JSON.writeValueAsBytes(this), Map.class)); }
}
