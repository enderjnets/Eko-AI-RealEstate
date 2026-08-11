import { describe, expect, it } from "vitest";

import { pendingLabelKey } from "../inboxBadge";

describe("pendingLabelKey", () => {
  it("names each known channel", () => {
    expect(pendingLabelKey("email")).toBe("inbox.badge.emailPending");
    expect(pendingLabelKey("voice")).toBe("inbox.badge.voicePending");
    expect(pendingLabelKey("whatsapp")).toBe("inbox.badge.whatsappPending");
    expect(pendingLabelKey("sms")).toBe("inbox.badge.smsPending");
    expect(pendingLabelKey("web")).toBe("inbox.badge.webPending");
  });

  it("never calls an unknown channel SMS", () => {
    // The regression: the chain ended in `: "inbox.badge.smsPending"`, so a
    // lead who filled in the web form was shown as having texted the office.
    // A badge is a claim about how to reach someone; the fallback has to say
    // nothing rather than say something false.
    for (const unknown of ["web", "fax", "", "carrier-pigeon", null, undefined]) {
      expect(pendingLabelKey(unknown)).not.toBe("inbox.badge.smsPending");
    }
    expect(pendingLabelKey("fax")).toBe("inbox.badge.pending");
    // A lead with no channel at all was also announced as SMS.
    expect(pendingLabelKey(null)).toBe("inbox.badge.pending");
  });
});
