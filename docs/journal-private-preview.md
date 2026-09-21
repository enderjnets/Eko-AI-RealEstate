# Journal private review

Approved by Ender, 21 September 2026. Preserve the latest design while limiting access to Natalia, Robbie and their broker.

URL: https://www.denverhomestory.com/blog/twelve-houses-worth-the-detour
Username: `journal`. Password: `JOURNAL_PREVIEW_PASSWORD`, runtime-only frontend environment; at least 20 ASCII characters. Empty/short configuration denies access. Generate randomly and share privately, never commit it or put it in a URL.

Pages require credentials in middleware AND server page/layout code. Images are in `frontend/private/journal`, served by an authenticated route at the existing `/blog/...` URLs. Listing photos remain gitignored. Docker also removes any legacy `public/blog` copied into a build context. No shared caching; no indexing; public homepage links hidden. Private review page views do not mount LandingTracker. The contact form remains real: do not submit test inquiries to the broker.

Before deploying, seed untracked photos into `private/journal/img` from the previous container, without changing their bytes. Compare all 48 hashes and keep a protected backup. Rebuilding an older image is NOT a safe rollback: it would publish the photos again. Fix forward or keep /blog blocked at ingress during rollback.

After deploying, purge old /blog content from Cloudflare on BOTH hostnames (DHS and the panel), then test anonymous/wrong/correct credentials, direct images, RSC, middleware-bypass headers, image optimizer requests, traversal, homepage links, calculator/contact/fall and health. Old copies already downloaded to third-party devices cannot be recalled.

Rotating the password and recreating only frontend revokes the old credentials. Browser Basic-auth sessions may persist until the browser is closed; a forgotten password prompt can be reopened in a private window. Never send credentials in a query string.

This preview is for permissions review, not distribution. Restricted access and retaining watermarks do not themselves establish photo rights. Confirm standing permissions for future Journal articles and separate social/video use with the responsible broker. Current photos came cropped in the design package; originals are not yet recovered.
