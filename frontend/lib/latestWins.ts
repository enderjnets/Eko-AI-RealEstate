/**
 * Guards against an older in-flight request overwriting a newer one.
 *
 * The browser gives no ordering guarantee between two fetches. When a panel can
 * be refreshed from more than one place — cancel a visit here, book one from
 * the matched listings there — the slower first response can land last and
 * replace fresh data with stale. In the visits panel that means the list snaps
 * back to before the booking, which reads as "it didn't work" and invites a
 * second attempt. A second attempt is a second real calendar invite in the
 * lead's inbox.
 *
 * Lives here rather than inline in the component because the component tree has
 * no test harness (no jsdom, no testing-library) and this is the part with the
 * behaviour worth pinning.
 *
 *   const gate = useRef(latestWins()).current;
 *   const mine = gate.start();
 *   const data = await load();
 *   if (mine()) setState(data);
 */
export function latestWins() {
  let latest = 0;
  return {
    /** Claim a turn. The returned predicate is true only while it is still the newest. */
    start(): () => boolean {
      const id = ++latest;
      return () => id === latest;
    },
  };
}
