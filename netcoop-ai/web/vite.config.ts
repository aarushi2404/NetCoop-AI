import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// dev: `npm run dev` proxies /api to `python -m netcoop serve-api` (port 8000)
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
});
