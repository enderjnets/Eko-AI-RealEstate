import { afterEach, describe, expect, it, vi } from "vitest";

const effects = vi.hoisted(() => ({ run: undefined as undefined | (() => void | (() => void)) }));
vi.mock("react", () => ({ useEffect: (run: () => void) => { effects.run = run; } }));
import { ArticleMotion } from "@/components/journal/ArticleMotion";

function mount(reduce = false) {
  const events = new Map<string, () => void>();
  const img = { style: { transform: "" } };
  const lead = { firstElementChild: img, offsetHeight: 600,
    getBoundingClientRect: () => ({ top: 100, height: 600 }),
    addEventListener: (name: string, cb: () => void) => events.set(name, cb),
    removeEventListener: (name: string) => events.delete(name) };
  const frames = new Map<number, FrameRequestCallback>();
  let id = 0;
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => { frames.set(++id, cb); return id; });
  vi.stubGlobal("cancelAnimationFrame", (key: number) => frames.delete(key));
  vi.stubGlobal("window", { innerHeight: 800, matchMedia: () => ({ matches: reduce }),
    addEventListener: vi.fn(), removeEventListener: vi.fn(), setTimeout: vi.fn(), clearTimeout: vi.fn() });
  vi.stubGlobal("document", { hidden: false, visibilityState: "visible", querySelector: () => null,
    querySelectorAll: (q: string) => q === "[data-lead]" ? [lead] : [],
    addEventListener: vi.fn(), removeEventListener: vi.fn() });
  ArticleMotion();
  const cleanup = effects.run?.();
  const flush = () => { const batch = [...frames.values()]; frames.clear(); batch.forEach(cb => cb(0)); };
  return { events, img, frames, flush, cleanup };
}

afterEach(() => vi.unstubAllGlobals());
describe("article photo interaction", () => {
  it("finishes hover zoom without needing a scroll event and stops requesting frames", () => {
    const m = mount(); m.flush();
    m.events.get("mouseenter")?.();
    expect(m.frames.size).toBe(1);
    for (let i = 0; i < 100; i++) m.flush();
    expect(m.img.style.transform).toContain("scale(1.160)");
    expect(m.frames.size).toBe(0);
    m.events.get("mouseleave")?.();
    for (let i = 0; i < 100; i++) m.flush();
    expect(m.img.style.transform).toContain("scale(1.120)");
    expect(m.frames.size).toBe(0);
    if (typeof m.cleanup === "function") m.cleanup();
    expect(m.events.size).toBe(0);
  });
  it("does not install animation work with reduced motion", () => {
    const m = mount(true);
    expect(m.events.size).toBe(0);
    expect(m.frames.size).toBe(0);
  });
});
