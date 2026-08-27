"use client";

/**
 * The links that do not fit, behind one trigger.
 *
 * Extracted rather than written: this dropdown already existed twice, in
 * `LanguageSwitcher` (the cleaner one — `aria-haspopup`, `role="listbox"`, an
 * outside-click handler) and in `Nav`'s Inbox button (the only one that closes
 * on ESC and on navigation). Neither had all three. A third hand-rolled copy
 * would have inherited whichever half its author happened to read.
 *
 * **Static split, not measurement.** Which items overflow is decided by
 * breakpoint at the call site, not by a ResizeObserver watching the row. A
 * measuring version reflows on every resize, needs a first paint to know
 * anything, and is a great deal of machinery for a nav whose contents change
 * about twice a year.
 *
 * **`direction="up"` is not decoration.** In the bottom tab bar this panel is
 * anchored to the bottom edge of the screen, so a `top-full` panel opens into
 * the area below the viewport and is simply not there. Anything mounted inside
 * `.eko-tabbar` wants `up`.
 *
 * One thing NOT to change: no `overflow-x` on whatever row hosts this. CSS
 * computes `overflow-y: visible` to `auto` the moment `overflow-x` stops being
 * visible, which clips an absolutely-positioned panel to zero pixels. That is
 * measured, and it is why the nav row this feeds is not a scroller — see the
 * comment in `Nav.tsx`.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { MoreHorizontal, type LucideIcon } from "lucide-react";

export type OverflowItem = {
  href: string;
  label: string;
  Icon: LucideIcon;
  /** Opens in a new tab — `/docs` is the backend's Swagger UI, not a route. */
  external?: boolean;
};

export function OverflowMenu({
  items,
  label,
  variant = "inline",
  direction = "down",
  className = "",
}: {
  items: OverflowItem[];
  /** Trigger text and accessible name. */
  label: string;
  /** `inline` sits in a row of links; `tab` is a full-height bottom-bar tab. */
  variant?: "inline" | "tab";
  direction?: "down" | "up";
  /**
   * Classes for the WRAPPER, not the button — responsive hiding included.
   *
   * On the button alone it hid the trigger and left the panel painted: open the
   * menu on a tablet, rotate to landscape, and a floating list of links sat
   * over the page with nothing to close it but ESC. It also left a zero-width
   * flex child still earning its `gap`. Hiding the wrapper takes the panel with
   * it.
   *
   * `open` is deliberately NOT reset on the way across: coming back down, the
   * panel reappears together with the button that owns it, which is state
   * preserved rather than a menu nobody can dismiss. Measured both directions
   * — an earlier draft of this very comment claimed a reset that did not exist.
   */
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const pathname = usePathname();

  // Outside click AND Escape. The Escape half existed only on the Inbox menu,
  // so every other dropdown in this app trapped a keyboard user who had opened
  // it by accident.
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // Close on navigation, or the panel survives the click that used it and hangs
  // over the page the reader just asked for.
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  // And close when focus leaves it. Without this, tabbing out of an open panel
  // left it in the DOM over the page — and a keyboard user could open this one
  // while the Inbox dropdown was still open, painting one over the other.
  useEffect(() => {
    if (!open) return;
    function onFocusOut(e: FocusEvent) {
      const next = e.relatedTarget as Node | null;
      if (ref.current && next && !ref.current.contains(next)) setOpen(false);
    }
    const node = ref.current;
    node?.addEventListener("focusout", onFocusOut);
    return () => node?.removeEventListener("focusout", onFocusOut);
  }, [open]);

  if (items.length === 0) return null;

  // Whether the page being read is one of the hidden ones. Without this the bar
  // shows no active tab at all while sitting on Analytics, which reads as being
  // nowhere.
  const holdsCurrent = items.some((i) =>
    !i.external && pathname.startsWith(i.href),
  );

  const panelPosition =
    direction === "up" ? "bottom-full mb-2" : "top-full mt-2";

  return (
    <div
      className={`${variant === "tab" ? "relative flex-1 min-w-0" : "relative"} ${className}`}
      ref={ref}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        aria-current={holdsCurrent ? "page" : undefined}
        className={
          variant === "tab"
            ? `relative w-full flex flex-col items-center justify-center gap-1 min-h-[56px] py-2 text-[10px] font-medium transition-colors ${
                holdsCurrent || open
                  ? "text-eko-violet"
                  : "text-gray-500 hover:text-gray-300"
              }`
            : `px-2 xl:px-3 py-1.5 rounded-md text-sm transition-colors inline-flex items-center gap-1.5 ${
                holdsCurrent || open
                  ? "text-white bg-white/5"
                  : "text-gray-300 hover:text-white hover:bg-white/5"
              }`
        }
      >
        <MoreHorizontal
          className={variant === "tab" ? "w-[21px] h-[21px] shrink-0" : "w-3.5 h-3.5"}
        />
        <span className={variant === "tab" ? "max-w-full truncate px-0.5" : ""}>
          {label}
        </span>
      </button>

      {open && (
        <div
          role="menu"
          className={`absolute right-0 ${panelPosition} w-52 rounded-xl border border-white/10 bg-eko-noir/95 backdrop-blur-md shadow-2xl shadow-black/40 py-1 z-50`}
        >
          {items.map((item) => {
            const active = !item.external && pathname.startsWith(item.href);
            const classes = `w-full flex items-center gap-2.5 px-3 py-2.5 text-sm text-left transition-colors ${
              active ? "text-white bg-white/5" : "text-gray-300 hover:bg-white/5 hover:text-white"
            }`;
            return item.external ? (
              <a
                key={item.href}
                href={item.href}
                target="_blank"
                rel="noopener noreferrer"
                role="menuitem"
                onClick={() => setOpen(false)}
                className={classes}
              >
                <item.Icon className="w-4 h-4 shrink-0 text-eko-violet" />
                <span className="truncate">{item.label}</span>
              </a>
            ) : (
              <Link
                key={item.href}
                href={item.href}
                role="menuitem"
                aria-current={active ? "page" : undefined}
                onClick={() => setOpen(false)}
                className={classes}
              >
                <item.Icon className="w-4 h-4 shrink-0 text-eko-violet" />
                <span className="truncate">{item.label}</span>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
