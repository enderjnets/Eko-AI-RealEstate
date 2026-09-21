/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // All images use plain <img>. Disable the unused optimizer so private media cannot enter its shared cache.
  images: { unoptimized: true },
  async redirects() {
    // Short links for the profile field of each network, because the long
    // tagged URL cannot be pasted where it needs to go:
    //
    //   * TikTok only offers a website field on a business account.
    //   * Instagram refused the edit.
    //   * Several apps silently drop everything after the "?" when saving.
    //
    // A short path sidesteps all three: there is no query string to lose, the
    // profile shows something readable, and the tagging happens here, where it
    // is versioned and testable rather than typed into someone's phone.
    //
    // Next emits a temporary 307 here. A permanent redirect would be cached
    // hard by browsers, and the day the campaign changes we would be fighting
    // caches on devices we cannot reach.
    // `to` exists because a bio link is a bet on which page suits the person
    // arriving from that network, and the bet is not the same all year.
    //
    // Instagram's points at the autumn guide as of 18-sep-2026, measured:
    // `/fall` is the best-read page on the site — 63% average scroll against
    // 31% for the home page — while the three sessions that did reach `/start`
    // from Instagram left at 0%. The tagging does not change, and that is the
    // point: `utm_medium=bio` is what tells a profile click from a caption
    // link, so the two stay countable apart even though they now land together.
    //
    // EXPIRES 1-nov-2026. `/fall` is twelve places sorted by the elevation
    // their aspens turn at; in November it is a guide to something that already
    // happened, and a visitor who followed a profile link would land on last
    // month. On that date Instagram goes back to `/start`. Deliberately NOT
    // automated on a date check: a redirect that changes by itself is a
    // redirect nobody re-reads, and this one deserves a person deciding
    // whether the next season has a page of its own. The reminder lives in
    // PROJECT_STATUS, and the test below fails if the date passes unattended.
    const bio = (network) => ({
      source: `/${network.short}`,
      destination:
        `${network.to || "/start"}?utm_source=${network.source}` +
        `&utm_medium=bio&utm_campaign=profile`,
      permanent: false,
    });

    // One short path per band of the autumn guide, so four Instagram pieces
    // that all send people to the same page can still be told apart.
    //
    // A caption is not a link: on Instagram the URL has to be TYPED, so a
    // tagged one is unusable and `/fall/1` is the whole trick. Written as a
    // redirect and not as a real `/fall/[n]` segment, which would publish four
    // indexable URLs carrying the same guide.
    //
    // The destination is relative, and that is safe HERE for a reason worth
    // naming rather than assuming: `/fall` and the bio destination `/start`
    // are public paths, so no middleware rule rewrites them and their queries
    // survive. If a destination ever stops being a public path, it has to
    // become absolute to the brand domain.
    // One short path per person who might share the site by hand.
    //
    // On 11-sep somebody posted the site on Facebook and it brought 26 real
    // sessions from Denver suburbs — the best day the site has had. Nobody
    // knows who did it, so it cannot be thanked, repeated, or asked for
    // again. A share carries no tag: whoever pastes the plain domain is
    // invisible, and `source=facebook` is the most the report can ever say.
    //
    // The content tag is the person's first name and not their initial. The
    // whole point of these is that somebody reads the breakdown weeks later
    // and knows what it means without a decoder ring; "n" needs one and
    // "natalia" does not. The short path stays a single letter because that
    // is the part a person has to type or remember.
    const partner = (person) => ({
      source: `/${person.short}`,
      destination:
        `/start?utm_source=partner&utm_medium=share&utm_content=${person.name}`,
      permanent: false,
    });

    const fall = (band) => ({
      source: `/fall/${band}`,
      destination:
        `/fall?utm_source=instagram&utm_medium=social` +
        `&utm_campaign=fall2026&utm_content=band${band}`,
      permanent: false,
    });

    return [
      bio({ short: "yt", source: "youtube" }),
      bio({ short: "tt", source: "tiktok" }),
      bio({ short: "ig", source: "instagram", to: "/fall" }),
      // Spelled-out aliases, for anywhere the two letters look like a typo.
      bio({ short: "youtube", source: "youtube" }),
      bio({ short: "tiktok", source: "tiktok" }),
      bio({ short: "instagram", source: "instagram", to: "/fall" }),
      partner({ short: "n", name: "natalia" }),
      partner({ short: "r", name: "robbie" }),
      partner({ short: "e", name: "ender" }),
      fall(1),
      fall(2),
      fall(3),
      fall(4),
    ];
  },
  async rewrites() {
    return [
      {
        // The frontend is reached at multiple origins (LAN 10.0.0.240:3004,
        // Tailscale 100.88.47.99:3004, future Cloudflare). To keep one API URL
        // that works from all of them, we proxy /api/* to the backend service
        // inside the Docker network. Clients always hit a relative /api path.
        source: "/api/:path*",
        destination: `${process.env.INTERNAL_API_URL || "http://backend:8000"}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
