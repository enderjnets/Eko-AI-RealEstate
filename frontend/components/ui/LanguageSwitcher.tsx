"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Globe } from "lucide-react";
import { type Lang, useI18n } from "@/lib/i18n";

const OPTIONS: { code: Lang; label: string; flag: string }[] = [
  { code: "en", label: "English", flag: "🇺🇸" },
  { code: "es", label: "Español", flag: "🇪🇸" },
];

export function LanguageSwitcher() {
  const { lang, setLang, t } = useI18n();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="inline-flex min-h-[44px] items-center gap-1.5 px-2.5 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-white/5 transition-colors"
        title={t("lang.label")}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <Globe className="w-3.5 h-3.5" />
        <span className="uppercase text-xs font-medium">{lang}</span>
      </button>
      {open && (
        <div
          role="listbox"
          className="absolute right-0 mt-1 w-40 rounded-lg border border-white/10 bg-eko-noir shadow-xl shadow-black/40 py-1 z-50"
        >
          {OPTIONS.map((o) => (
            <button
              key={o.code}
              type="button"
              role="option"
              aria-selected={lang === o.code}
              onClick={() => {
                setLang(o.code);
                setOpen(false);
              }}
              className={`w-full flex items-center gap-2 px-3 py-1.5 text-sm text-left hover:bg-white/5 ${
                lang === o.code ? "text-white" : "text-gray-400"
              }`}
            >
              <span aria-hidden>{o.flag}</span>
              <span className="flex-1">{o.label}</span>
              {lang === o.code && <Check className="w-3.5 h-3.5 text-eko-violet" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
