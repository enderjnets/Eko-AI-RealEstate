/**
 * Which label the Inbox shows for a lead awaiting a reply.
 *
 * Extracted from the badge component so the fallback is testable. It used to
 * be the tail of a ternary chain that ended in "SMS pending", which meant any
 * channel the UI did not know about was announced as a text message — a lead
 * who filled in the web form appeared to have texted the office. A badge is a
 * claim about how this person reached you and how to reach them back, so the
 * default has to say nothing rather than say something false.
 */
export function pendingLabelKey(channel: string | null | undefined): string {
  switch (channel) {
    case "email":
      return "inbox.badge.emailPending";
    case "voice":
      return "inbox.badge.voicePending";
    case "whatsapp":
      return "inbox.badge.whatsappPending";
    case "sms":
      return "inbox.badge.smsPending";
    case "web":
      return "inbox.badge.webPending";
    default:
      return "inbox.badge.pending";
  }
}
