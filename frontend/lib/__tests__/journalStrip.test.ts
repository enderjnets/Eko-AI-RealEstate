import { afterEach, describe, expect, it, vi } from "vitest";
const hooks = vi.hoisted(() => ({ run: undefined as undefined | (() => void | (() => void)), current: undefined as unknown }));
vi.mock("react", () => ({ useEffect: (run: () => void) => { hooks.run = run; }, useRef: () => ({ current: hooks.current }) }));
import { Strip } from "@/components/journal/Strip";

function mount(reduce = false) {
  vi.useFakeTimers();
  vi.stubGlobal("React", { createElement: () => null, Fragment: "fragment" });
  const events = new Map<string, () => void>();
  const panels = ["richmond", "brushcreek"].map((slug, i) => {
    const handlers = new Map<string, (e: unknown) => void>();
    const link = { tabIndex: 0 };
    const label = { style: {} as Record<string, string>, querySelector: () => link };
    const overlay = { style: {} as Record<string, string> };
    return { style: {} as Record<string, string>, dataset: { slug }, offsetLeft: i * 100,
      label, overlay, handlers, link,
      querySelector: (q: string) => q === "[data-lab]" ? label : overlay,
      setAttribute: vi.fn(),
      addEventListener: (name: string, cb: (e: unknown) => void) => handlers.set(name, cb),
      removeEventListener: (name: string) => handlers.delete(name) };
  });
  const frames = new Map<number, FrameRequestCallback>(); let id = 0;
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => { frames.set(++id, cb); return id; });
  vi.stubGlobal("cancelAnimationFrame", (key: number) => frames.delete(key));
  vi.stubGlobal("Image", class { src = ""; });
  vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });
  vi.stubGlobal("window", { matchMedia: () => ({ matches: reduce }),
    addEventListener: vi.fn(), removeEventListener: vi.fn(), setTimeout, clearTimeout, setInterval, clearInterval });
  vi.stubGlobal("document", { hidden: false, visibilityState: "visible",
    addEventListener: (name: string, cb: () => void) => events.set(name, cb), removeEventListener: (name: string) => events.delete(name) });
  hooks.current = { clientWidth: 800, querySelectorAll: () => panels, scrollTo: vi.fn() };
  Strip(); const cleanup = hooks.run?.();
  const click = (i: number) => panels[i].handlers.get("click")?.({ target: { closest: () => null } });
  const flush = () => { const batch = [...frames.values()]; frames.clear(); batch.forEach(cb => cb(0)); };
  return { panels, frames, click, flush, cleanup };
}
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); });
describe("Journal carousel", () => {
  it("switches labels without motion and keeps only the active link tabbable", () => {
    const m = mount(true); m.click(1);
    expect(m.panels[1].label.style.transition).toBe("none");
    expect(m.panels[0].label.style.transform).toBe("translateX(0)");
    expect(m.panels[0].label.style.pointerEvents).toBe("none");
    expect(m.panels[0].link.tabIndex).toBe(-1);
    expect(m.panels[1].link.tabIndex).toBe(0);
    expect(m.frames.size).toBe(0);
    if (typeof m.cleanup === "function") m.cleanup();
  });
  it("cancels a pending photo frame when switching, and all work when unmounted", () => {
    const m = mount();
    vi.advanceTimersByTime(2400);
    expect(m.frames.size).toBeGreaterThan(0);
    m.click(1); m.flush();
    expect(m.panels[0].overlay.style.opacity).toBe("0");
    if (typeof m.cleanup === "function") m.cleanup();
    expect(m.frames.size).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
    expect(m.panels[0].handlers.size).toBe(0);
  });
});
