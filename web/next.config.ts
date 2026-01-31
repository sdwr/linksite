import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactCompiler: true,
  async rewrites() {
    return [
      // Proxy API calls to FastAPI backend
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
      // Proxy admin pages to FastAPI backend
      {
        source: "/admin",
        destination: "http://localhost:8000/admin",
      },
      {
        source: "/admin/:path*",
        destination: "http://localhost:8000/admin/:path*",
      },
      // Proxy links page to FastAPI backend
      {
        source: "/links",
        destination: "http://localhost:8000/links",
      },
      // Proxy scratchpad pages to FastAPI backend
      {
        source: "/browse",
        destination: "http://localhost:8000/browse",
      },
      {
        source: "/add",
        destination: "http://localhost:8000/add",
      },
      {
        source: "/link/:path*",
        destination: "http://localhost:8000/link/:path*",
      },
    ];
  },
};

export default nextConfig;
