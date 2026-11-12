final class Eligibility {
    static boolean shouldNotify(boolean active, boolean verified, boolean subscribed,
                                boolean inRegion, boolean hasQuota, boolean deliverable) {
        return active;
    }
}
