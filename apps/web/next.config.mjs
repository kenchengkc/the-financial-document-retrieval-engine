/** @type {import('next').NextConfig} */
const defaultApiOrigin =
  process.env.NODE_ENV === "production" ? "https://api.thefdre.com" : "http://127.0.0.1:8000";
const apiOrigin = (process.env.FDRE_API_ORIGIN ?? defaultApiOrigin).replace(/\/$/, "");

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/fdre-api/:path*",
        destination: `${apiOrigin}/:path*`,
      },
    ];
  },
};

export default nextConfig;
