/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
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
    // 302 and not 301 on purpose: a permanent redirect is cached hard by
    // browsers, and the day the campaign changes we would be fighting caches
    // on devices we cannot reach.
    const bio = (network) => ({
      source: `/${network.short}`,
      destination:
        `/?utm_source=${network.source}&utm_medium=bio&utm_campaign=profile`,
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
    // naming rather than assuming: `/fall` is a public path, so no middleware
    // rule rewrites it and the query survives. `bio()` above points at `/`,
    // which on the panel host IS rewritten — to `/leads`, dropping the query
    // — so a bio link pasted with the panel hostname loses its attribution.
    // If a destination ever stops being a public path, it has to become
    // absolute to the brand domain.
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
      bio({ short: "ig", source: "instagram" }),
      // Spelled-out aliases, for anywhere the two letters look like a typo.
      bio({ short: "youtube", source: "youtube" }),
      bio({ short: "tiktok", source: "tiktok" }),
      bio({ short: "instagram", source: "instagram" }),
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
