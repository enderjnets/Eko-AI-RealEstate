import { describe, expect, it } from "vitest";

import { briefSend, type BriefSendInput } from "../briefSend";

const ask = (over: Partial<BriefSendInput> = {}) =>
  briefSend({
    saving: false,
    dirty: false,
    failed: false,
    sent: false,
    everSaved: false,
    ...over,
  });

describe("the brief's Send button", () => {
  it("can be pressed on a page that was loaded and not touched — the measured failure", () => {
    // Natalia opened the brief the day after filling it in, pressed Send, and
    // nothing left the browser: 1 GET, 0 POSTs. `!dirty` was the guard, and a
    // freshly loaded page is never dirty.
    expect(ask({ everSaved: true }).enabled).toBe(true);
  });

  it("can still be pressed a second after an edit, once the autosave has run", () => {
    // The autosave fires 1,200ms after the last tap and clears `dirty`. That
    // left the button alive for about a second per edit, which is the same
    // bug wearing a different hat.
    expect(ask({ dirty: false, everSaved: true }).enabled).toBe(true);
  });

  it("refuses only while a write is in flight", () => {
    // The one honest reason to say no: a press now would race the request
    // already going out.
    expect(ask({ saving: true }).enabled).toBe(false);
    expect(ask({ saving: true, dirty: true }).enabled).toBe(false);
  });

  it("can be pressed on a brief nobody has answered", () => {
    // "Read it and had nothing to say" is a real answer — `PartnerBrief` keeps
    // `opened_at` precisely to tell it apart from "hasn't read it". Refusing
    // the press would throw away the cheaper half of that signal.
    expect(ask().enabled).toBe(true);
  });
});

describe("what the page says it just did", () => {
  it("answers a deliberate press with a different word than the autosave", () => {
    // The half that fixing the button alone would have missed. A press used to
    // land on the same "Saved" the timer had been showing for a second, so a
    // working button still looked like it had ignored her — and a person who
    // thinks the button did nothing presses it again.
    expect(ask({ sent: true, everSaved: true }).status).toBe("brief.sent");
    expect(ask({ sent: false, everSaved: true }).status).toBe("brief.saved");
  });

  it("stops saying sent as soon as something is edited again", () => {
    // What we were told about is no longer what is on screen. Leaving "Sent"
    // up would be the page lying on the reassuring side, which is the only
    // direction that costs anything here.
    expect(ask({ sent: true, dirty: true, everSaved: true }).status).toBe("brief.unsaved");
  });

  it("puts a failure above everything, because it is the one that asks for another press", () => {
    expect(ask({ failed: true, sent: true, dirty: true, everSaved: true }).status).toBe(
      "brief.saveFailed",
    );
    expect(ask({ failed: true, saving: true }).status).toBe("brief.saveFailed");
  });

  it("says it is working while it works", () => {
    expect(ask({ saving: true, dirty: true }).status).toBe("brief.saving");
  });

  it("distinguishes a brief nobody has touched from one that has been written", () => {
    // Not cosmetic: it is the difference between "she has not started" and
    // "she answered and we have it", which are two different conversations to
    // have with a partner.
    expect(ask().status).toBe("brief.untouched");
    expect(ask({ everSaved: true }).status).toBe("brief.saved");
  });

  it("never reports a failure as a success", () => {
    // A person who believes they saved stops. Every state that carries a
    // failure has to say so, whatever else is true at the same time.
    const states: Partial<BriefSendInput>[] = [
      {},
      { dirty: true },
      { sent: true },
      { everSaved: true },
      { saving: true },
      { sent: true, everSaved: true, dirty: true },
    ];
    for (const s of states) {
      expect(ask({ ...s, failed: true }).status).toBe("brief.saveFailed");
    }
  });
});
