import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built pages talk only to this origin: no analytics, fonts or CDNs (campus app).
const CSP = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; " +
  "connect-src 'self'; base-uri 'none'; form-action 'none'; object-src 'none'";

export default defineConfig({
  plugins: [react(), {name: "csp", apply: "build", transformIndexHtml: () =>
    [{tag: "meta", attrs: {"http-equiv": "Content-Security-Policy", content: CSP}, injectTo: "head-prepend"}]}],
  server: {proxy: {"/api": "http://127.0.0.1:8092"}},
});
