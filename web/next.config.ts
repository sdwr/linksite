import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactCompiler: true,
  async redirects() {
    return [
      {
        source: "/",
        destination: "/add",
        permanent: false,
      },
    ];
  },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: "http://localhost:8000/api/:path*" },
      { source: "/admin", destination: "http://localhost:8000/admin" },
      { source: "/admin/:path*", destination: "http://localhost:8000/admin/:path*" },
      { source: "/links", destination: "http://localhost:8000/links" },
      { source: "/browse", destination: "http://localhost:8000/browse" },
      { source: "/add", destination: "http://localhost:8000/add" },
      { source: "/link/:path*", destination: "http://localhost:8000/link/:path*" },
    ];
  },
};

export default nextConfig;
