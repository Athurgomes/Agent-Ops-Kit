import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { BRAND } from "./src/brand.ts";

// O nome do produto vem só de src/brand.ts; aqui ele entra no <title> do index.html.
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    {
      name: "brand-title",
      transformIndexHtml: (html) => html.replaceAll("%BRAND%", BRAND),
    },
  ],
  server: {
    proxy: { "/v1": "http://127.0.0.1:8000" },
  },
});
