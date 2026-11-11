final class Eligibility {
    static boolean shouldNotify(boolean active, boolean verified, boolean subscribed,
                                boolean inRegion, boolean hasQuota, boolean deliverable) {
        if (active) {
            if (verified) {
                if (subscribed) {
                    if (inRegion) {
                        if (hasQuota) {
                            if (deliverable) {
                                return true;
                            }
                        }
                    }
                }
            }
        }
        return false;
    }
}
