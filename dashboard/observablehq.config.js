// Static site over aggregates of the de-identified genomics DuckDB.
// Data loaders live in src/data/*.py and run at build time via `uv run python`
// (project root is the parent pyproject, so uccc_genomics is importable).
export default {
  title: "UCCC vendor genomics",
  root: "src",
  interpreters: {".py": ["uv", "run", "python"]},
  head: `
    <script>
      (function () {
        var h = location.hostname;
        if (h === "localhost" || h === "127.0.0.1" || h === "[::1]" ||
            /\.(workers\.dev|netlify\.app|ts\.net)$/.test(h) ||
            /^\d{1,3}(\.\d{1,3}){3}$/.test(h) || h.indexOf(":") !== -1) return;
        var s = document.createElement("script");
        s.async = true;
        s.src = "https://www.googletagmanager.com/gtag/js?id=G-KLLV1GCF4E";
        document.head.appendChild(s);
        window.dataLayer = window.dataLayer || [];
        window.gtag = function () { dataLayer.push(arguments); };
        gtag("js", new Date());
        gtag("config", "G-KLLV1GCF4E", {content_group: "uccc-genomics"});
      })();
    </script>
  `,
  pages: [
    {name: "Overview", path: "/"},
    {name: "Cohort exploration", path: "/cohort"},
    {name: "Genes", path: "/genes"},
    {name: "Biomarkers", path: "/biomarkers"},
    {name: "Coverage & quality", path: "/coverage"},
  ],
  footer: "Aggregates only. Counts below 5 are omitted. Dates are shifted per patient by up to ±6 months, so use year granularity.",
  toc: false,
};
