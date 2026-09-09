import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://192.168.1.202",  // dev only; prod served by Caddy same-origin
    },
  },
});
