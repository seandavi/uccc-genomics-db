import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built pages talk only to this origin, plus Google Analytics (/assets/ga.js, production hostname only).
// No fonts or other CDNs.
const GA = "https://www.googletagmanager.com https://*.google-analytics.com https://*.analytics.google.com";
const CSP = `default-src 'self'; script-src 'self' ${GA}; style-src 'self' 'unsafe-inline'; ` +
  `img-src 'self' data: ${GA}; connect-src 'self' ${GA}; base-uri 'none'; form-action 'none'; object-src 'none'`;

export default defineConfig({
  plugins: [react(), {name: "csp", apply: "build", transformIndexHtml: () =>
    [{tag: "meta", attrs: {"http-equiv": "Content-Security-Policy", content: CSP}, injectTo: "head-prepend"},
     {tag: "script", attrs: {src: "/assets/ga.js"}, injectTo: "head"}]}],
  build: {rolldownOptions: {input: {landing: "index.html", discover: "discover.html"}}},
  server: {proxy: {"/api": "http://127.0.0.1:8092"}},
});
