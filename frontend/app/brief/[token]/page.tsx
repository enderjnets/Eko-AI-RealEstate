"use client";

/**
 * The page we hand to the people we work with, instead of an email with a list
 * at the bottom.
 *
 * Every ask we had for the two agents this product is built around used to
 * arrive as prose ending in "reply with these three lines", and the reply we
 * needed was a person retyping nine names into a mail client on a phone. That
 * reply does not come, and expecting it was our failure rather than theirs.
 *
 * Three decisions here are load-bearing.
 *
 * **The page renders a payload, not a design.** Every block below comes out of
 * `partner_briefs.payload`, so the next brief is a JSON file and a script run,
 * not a deploy. Nine of these will exist by Christmas and no two will ask the
 * same thing.
 *
 * **Nothing is pre-selected against them.** Every person in a `people` block
 * starts as "will receive a letter", and the only taps needed are the
 * exceptions. A page that made her confirm nine names one at a time would be
 * the same chore as the email, with worse ergonomics.
 *
 * **It saves as they go.** They are reading this on a phone, probably between
 * other things, and the one outcome we cannot have is twenty minutes of
 * answers lost to a backgrounded tab. A debounced autosave writes without
 * being asked; the button stays because a person needs to be able to finish
 * something on purpose.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

import { useI18n } from "@/lib/i18n";
import { loadBrief, saveBrief, type Brief, type BriefBlock } from "@/lib/brief";

/** What a person's row can be set to. `send` is the unchosen default. */
type PersonState = "send" | "out" | "touch";

interface PersonAnswer {
  state?: PersonState;
  /** What she actually calls them, when the county's spelling is wrong. */
  correct?: string;
  /** Whether the name field is open. UI state, kept so a reload restores it. */
  naming?: boolean;
}

type Answers = Record<string, unknown>;

/** How long after the last keystroke we write. Long enough not to post on
 *  every letter, short enough that putting the phone down saves. */
const AUTOSAVE_MS = 1200;

export default function BriefPage({ params }: { params: { token: string } }) {
  const { t } = useI18n();
  const [brief, setBrief] = useState<Brief | null>(null);
  const [missing, setMissing] = useState(false);
  const [answers, setAnswers] = useState<Answers>({});

  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  // Read in a ref as well as state: the debounce timer fires outside React's
  // render, and closing over `answers` would post whatever was current when
  // the timer was scheduled rather than what is on screen when it fires.
  const latest = useRef<Answers>({});
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** `dirty` for the leave handler, which is registered once and must not
   *  re-register to see a new value. */
  const dirtyRef = useRef(false);

  useEffect(() => {
    let alive = true;
    loadBrief(params.token).then((result) => {
      if (!alive) return;
      if (!result) {
        setMissing(true);
        return;
      }
      setBrief(result);
      setAnswers(result.answers || {});
      latest.current = result.answers || {};
      setSavedAt(result.answered_at);
    });
    return () => {
      alive = false;
    };
  }, [params.token]);

  /** `deliberate` = they pressed the button, rather than the timer firing.
   *  It rides along to the server, which uses it to decide whether this save
   *  is worth an email — see the notify coalescing in `public.py`. */
  const flush = useCallback(
    async (deliberate = false) => {
      if (timer.current) {
        clearTimeout(timer.current);
        timer.current = null;
      }
      setSaving(true);
      const ok = await saveBrief(params.token, latest.current, deliberate);
      setSaving(false);
      setFailed(!ok);
      if (ok) {
        setDirty(false);
        dirtyRef.current = false;
        setSavedAt(new Date().toISOString());
      }
      return ok;
    },
    [params.token],
  );

  const update = useCallback(
    (mutate: (draft: Answers) => void) => {
      setAnswers((prev) => {
        const next = { ...prev };
        mutate(next);
        latest.current = next;
        return next;
      });
      setDirty(true);
      dirtyRef.current = true;
      setFailed(false);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        void flush(false);
      }, AUTOSAVE_MS);
    },
    [flush],
  );

  // A tab being hidden is the last moment we are certain to get. `pagehide`
  // rather than `beforeunload`: iOS Safari does not reliably fire the latter,
  // and iOS Safari is where this page is read.
  useEffect(() => {
    const onLeave = () => {
      if (!dirtyRef.current) return;
      const body = JSON.stringify({ answers: latest.current, notify: false });
      // `sendBeacon` because a normal fetch is cancelled when the page goes
      // away; this one is queued by the browser and survives it.
      navigator.sendBeacon?.(
        `/api/v1/public/brief/${encodeURIComponent(params.token)}`,
        new Blob([body], { type: "application/json" }),
      );
    };
    const onHide = () => {
      if (document.visibilityState === "hidden") onLeave();
    };
    window.addEventListener("pagehide", onLeave);
    document.addEventListener("visibilitychange", onHide);
    return () => {
      window.removeEventListener("pagehide", onLeave);
      document.removeEventListener("visibilitychange", onHide);
    };
    // Deliberately empty: this effect must run ONCE. It used to depend on
    // `dirty`, and the visibilitychange handler was an anonymous function that
    // the cleanup never removed — so every keystroke that flipped `dirty` left
    // another live listener behind, and one tab-hide fired all of them. Four
    // identical POSTs in 51ms, measured in production on 13-sep-2026, each one
    // also sending an email. `dirtyRef` is what lets this close over nothing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.token]);

  if (missing) {
    return (
      <div className="eko-brief">
        <div className="wrap centered">
          <p>{t("brief.missing")}</p>
        </div>
      </div>
    );
  }

  if (!brief) {
    return (
      <div className="eko-brief">
        <div className="wrap centered">
          <Loader2 className="h-5 w-5 animate-spin" aria-label={t("brief.loading")} />
        </div>
      </div>
    );
  }

  const status = failed
    ? t("brief.saveFailed")
    : saving
      ? t("brief.saving")
      : dirty
        ? t("brief.unsaved")
        : savedAt
          ? t("brief.saved")
          : t("brief.untouched");

  return (
    <div className="eko-brief">
      <header className="mast">
        <div className="wrap">
          {brief.payload.eyebrow ? <p className="eyebrow">{brief.payload.eyebrow}</p> : null}
          <h1>{brief.payload.headline || brief.title}</h1>
          {brief.payload.standfirst ? (
            <p className="standfirst">{brief.payload.standfirst}</p>
          ) : null}
          <p className="privacy">{t("brief.private")}</p>
        </div>
      </header>

      {/* The same status as the bar at the bottom, pinned to the TOP.
          Not redundancy: on a phone the bottom bar sits behind the keyboard
          the moment a text box is focused, so while somebody is typing — the
          exact moment they need to know their words are safe — the only
          confirmation on the page is invisible. Measured on 13-sep-2026: the
          saves were landing and the person filling it in could not tell.
          Hidden when there is nothing to say, so it never steals a line from
          the reading. */}
      {(dirty || saving || failed || savedAt) ? (
        <div className={`topstate${failed ? " bad" : !dirty && savedAt ? " good" : ""}`}>
          <div className="wrap">{status}</div>
        </div>
      ) : null}

      <div className="wrap">
        {(brief.payload.blocks || []).map((block, i) => (
          <Block key={block.id || `b${i}`} block={block} answers={answers} update={update} />
        ))}
      </div>

      <div className="savebar">
        <div className="wrap">
          <span className={`state${failed ? " bad" : !dirty && savedAt ? " good" : ""}`}>
            {status}
          </span>
          <button type="button" onClick={() => void flush(true)} disabled={saving || !dirty}>
            {t("brief.send")}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── the blocks ────────────────────────────────────────────────────────── */

function Block({
  block,
  answers,
  update,
}: {
  block: BriefBlock;
  answers: Answers;
  update: (mutate: (draft: Answers) => void) => void;
}) {
  switch (block.kind) {
    case "plan":
      return <PlanBlock block={block} />;
    case "asks":
      return <AsksBlock block={block} />;
    case "prose":
      return <ProseBlock block={block} />;
    case "questions":
      return <QuestionsBlock block={block} answers={answers} update={update} />;
    case "people":
      return <PeopleBlock block={block} answers={answers} update={update} />;
    case "letter":
      return <LetterBlock block={block} answers={answers} update={update} />;
    case "doc":
      return <DocBlock block={block} />;
    case "colophon":
      return <ColophonBlock block={block} />;
    default:
      // An unknown block is a payload written for a newer page. Rendering
      // nothing is the only safe answer: guessing would put a half-drawn
      // question in front of somebody who would then answer it.
      return null;
  }
}

function SectionHead({ block }: { block: BriefBlock }) {
  return (
    <>
      {block.kicker ? <p className="kicker">{block.kicker}</p> : null}
      {block.heading ? <h2 className="sec">{block.heading}</h2> : null}
    </>
  );
}

/** Paragraphs, and optional sub-headed groups. */
function Paragraphs({ items, lede }: { items?: string[]; lede?: boolean }) {
  if (!items?.length) return null;
  return (
    <>
      {items.map((text, i) => (
        <p key={i} className={lede && i === 0 ? "lede" : undefined}>
          {text}
        </p>
      ))}
    </>
  );
}

function PlanBlock({ block }: { block: BriefBlock }) {
  return (
    <div className="plan">
      {block.kicker ? <p className="kicker">{block.kicker}</p> : null}
      {block.heading ? <h2>{block.heading}</h2> : null}
      <Paragraphs items={block.body} />
      {(block.groups || []).map((group, i) => (
        <div key={i}>
          {group.label ? <span className="label">{group.label}</span> : null}
          {group.steps?.length ? (
            <ol>
              {group.steps.map((step, j) => (
                <li key={j}>{step}</li>
              ))}
            </ol>
          ) : null}
          <Paragraphs items={group.body} />
        </div>
      ))}
    </div>
  );
}

function AsksBlock({ block }: { block: BriefBlock }) {
  const jump = (anchor?: string) => {
    if (!anchor) return;
    // `scrollIntoView` rather than an `href="#id"`: fragment navigation is not
    // reliable inside an embedding frame, and this page is opened from links
    // in places we do not control.
    document.getElementById(anchor)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  return (
    <div className="asks">
      {block.heading ? <h2>{block.heading}</h2> : null}
      <ol>
        {(block.items || []).map((item, i) => (
          <li key={i}>
            <button type="button" onClick={() => jump(item.anchor)}>
              <span className="n">{i + 1}</span>
              <span>
                {item.label}
                {item.who ? <span className="who">{item.who}</span> : null}
              </span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}

function ProseBlock({ block }: { block: BriefBlock }) {
  return (
    <>
      <hr className="rule" />
      <section id={block.id}>
        <SectionHead block={block} />
        <Paragraphs items={block.body} lede={block.lede} />
        {block.card?.length ? (
          <div className={`card${block.cardStyle ? ` ${block.cardStyle}` : ""}`}>
            <Paragraphs items={block.card} />
          </div>
        ) : null}
      </section>
    </>
  );
}

function Field({
  field,
  answers,
  update,
}: {
  field: NonNullable<BriefBlock["fields"]>[number];
  answers: Answers;
  update: (mutate: (draft: Answers) => void) => void;
}) {
  const value = typeof answers[field.id] === "string" ? (answers[field.id] as string) : "";
  const set = (next: string) => update((draft) => void (draft[field.id] = next));
  return (
    <div className="qa">
      <label htmlFor={field.id}>
        {field.label}
        {field.hint ? <span className="hint">{field.hint}</span> : null}
      </label>
      {field.single ? (
        <input
          type="text"
          id={field.id}
          value={value}
          onChange={(e) => set(e.target.value)}
        />
      ) : (
        <textarea id={field.id} value={value} onChange={(e) => set(e.target.value)} />
      )}
    </div>
  );
}

function QuestionsBlock({
  block,
  answers,
  update,
}: {
  block: BriefBlock;
  answers: Answers;
  update: (mutate: (draft: Answers) => void) => void;
}) {
  return (
    <>
      <hr className="rule" />
      <section id={block.id}>
        <SectionHead block={block} />
        <Paragraphs items={block.body} />
        <div className={`card${block.cardStyle ? ` ${block.cardStyle}` : ""}`}>
          {(block.fields || []).map((field) => (
            <Field key={field.id} field={field} answers={answers} update={update} />
          ))}
        </div>
      </section>
    </>
  );
}

function PeopleBlock({
  block,
  answers,
  update,
}: {
  block: BriefBlock;
  answers: Answers;
  update: (mutate: (draft: Answers) => void) => void;
}) {
  const { t } = useI18n();
  const people = block.people || [];
  const key = block.id || "people";
  const rows = (answers[key] as Record<string, PersonAnswer>) || {};

  const tally = useMemo(() => {
    let go = 0;
    let out = 0;
    let touch = 0;
    for (const person of people) {
      const state = rows[person.id]?.state || "send";
      if (state === "out") out++;
      else if (state === "touch") touch++;
      else go++;
    }
    return { go, out, touch };
  }, [people, rows]);

  const setRow = (id: string, mutate: (row: PersonAnswer) => void) =>
    update((draft) => {
      const all = { ...((draft[key] as Record<string, PersonAnswer>) || {}) };
      const row = { ...(all[id] || {}) };
      mutate(row);
      all[id] = row;
      draft[key] = all;
    });

  return (
    <>
      <hr className="rule" />
      <section id={block.id}>
        <SectionHead block={block} />
        <Paragraphs items={block.body} lede={block.lede} />

        <div className="tally">
          <span className="go">
            <b>{tally.go}</b> {block.labels?.go || t("brief.willGet")}
          </span>
          <span className="touch">
            <b>{tally.touch}</b> {block.labels?.touch || t("brief.inTouch")}
          </span>
          <span className="out">
            <b>{tally.out}</b> {block.labels?.out || t("brief.leftOut")}
          </span>
        </div>

        <ol className="people">
          {people.map((person, i) => {
            const row = rows[person.id] || {};
            const state: PersonState = row.state || "send";
            return (
              <li className="person" data-state={state} key={person.id}>
                <div className="top">
                  <span className="num">{i + 1}</span>
                  <div>
                    <p className="name">{person.name}</p>
                    {person.detail ? <p className="addr">{person.detail}</p> : null}
                    {person.meta ? <p className="meta">{person.meta}</p> : null}
                    {person.flag ? <span className="flagline">{person.flag}</span> : null}
                  </div>
                </div>

                <div className="choices">
                  <button
                    type="button"
                    className="b-out"
                    aria-pressed={state === "out"}
                    onClick={() =>
                      setRow(person.id, (r) => {
                        r.state = r.state === "out" ? undefined : "out";
                      })
                    }
                  >
                    {block.actions?.out || t("brief.actionOut")}
                  </button>
                  <button
                    type="button"
                    className="b-touch"
                    aria-pressed={state === "touch"}
                    onClick={() =>
                      setRow(person.id, (r) => {
                        r.state = r.state === "touch" ? undefined : "touch";
                      })
                    }
                  >
                    {block.actions?.touch || t("brief.actionTouch")}
                  </button>
                  <button
                    type="button"
                    className="b-name"
                    aria-pressed={!!row.naming}
                    onClick={() =>
                      setRow(person.id, (r) => {
                        r.naming = !r.naming;
                      })
                    }
                  >
                    {block.actions?.name || t("brief.actionName")}
                  </button>
                </div>

                {row.naming ? (
                  <div className="namefix">
                    <label htmlFor={`name-${person.id}`}>
                      {block.actions?.namePrompt || t("brief.namePrompt")}
                    </label>
                    <input
                      type="text"
                      id={`name-${person.id}`}
                      value={row.correct || ""}
                      onChange={(e) =>
                        setRow(person.id, (r) => {
                          r.correct = e.target.value;
                        })
                      }
                    />
                  </div>
                ) : null}

                <p className={`status ${state}`}>
                  {state === "out"
                    ? block.states?.out || t("brief.stateOut")
                    : state === "touch"
                      ? block.states?.touch || t("brief.stateTouch")
                      : block.states?.go || t("brief.stateGo")}
                </p>
              </li>
            );
          })}
        </ol>

        {block.note ? (
          <div className="card flag">
            <Paragraphs items={block.note} />
            {(block.fields || []).map((field) => (
              <Field key={field.id} field={field} answers={answers} update={update} />
            ))}
          </div>
        ) : null}
      </section>
    </>
  );
}

function LetterBlock({
  block,
  answers,
  update,
}: {
  block: BriefBlock;
  answers: Answers;
  update: (mutate: (draft: Answers) => void) => void;
}) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const key = block.id || "letter";
  const chosen = answers[`${key}.state`];

  const copy = async () => {
    // The WHOLE letter, never what the box happens to show. The preview
    // scrolls; a copy that stopped where the scroll did would paste a
    // half-written email with a "continues below" note inside it.
    const text = block.letter || "";
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      try {
        document.execCommand("copy");
      } catch {
        /* nothing else to try; the text is on screen to select by hand */
      }
      document.body.removeChild(area);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2200);
  };

  return (
    <>
      <hr className="rule" />
      <section id={block.id}>
        <SectionHead block={block} />
        <Paragraphs items={block.body} />
        <div className="letter">{block.letter}</div>
        <button type="button" className="action" onClick={() => void copy()}>
          {copied ? t("brief.copied") : block.actions?.copy || t("brief.copy")}
        </button>

        {block.choices?.length ? (
          <div className="card" style={{ marginTop: 18 }}>
            <div className="qa">
              <label>{block.choiceLabel || t("brief.whereItStands")}</label>
              <div className="choices">
                {block.choices.map((choice) => (
                  <button
                    key={choice.value}
                    type="button"
                    className={choice.value === "sent" ? "b-touch" : "b-out"}
                    aria-pressed={chosen === choice.value}
                    onClick={() =>
                      update((draft) => {
                        draft[`${key}.state`] =
                          draft[`${key}.state`] === choice.value ? undefined : choice.value;
                      })
                    }
                  >
                    {choice.label}
                  </button>
                ))}
              </div>
            </div>
            {(block.fields || []).map((field) => (
              <Field key={field.id} field={field} answers={answers} update={update} />
            ))}
          </div>
        ) : null}
      </section>
    </>
  );
}

function DocBlock({ block }: { block: BriefBlock }) {
  return (
    <>
      <hr className="rule" />
      <section id={block.id}>
        <SectionHead block={block} />
        <Paragraphs items={block.body} />
        {(block.docs || []).map((doc, i) => (
          <a
            className="doc"
            key={i}
            href={doc.href}
            target="_blank"
            rel="noopener noreferrer"
          >
            <span className="ic" aria-hidden="true">
              {doc.icon || "📄"}
            </span>
            <span>
              <span className="t">{doc.title}</span>
              {doc.subtitle ? <span className="s">{doc.subtitle}</span> : null}
            </span>
          </a>
        ))}
      </section>
    </>
  );
}

function ColophonBlock({ block }: { block: BriefBlock }) {
  return (
    <footer>
      {block.signature ? <p className="sign">{block.signature}</p> : null}
      <Paragraphs items={block.body} />
    </footer>
  );
}
