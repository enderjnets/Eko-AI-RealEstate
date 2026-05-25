/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
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
