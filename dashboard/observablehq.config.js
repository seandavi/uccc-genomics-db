// Static site over aggregates of the de-identified genomics DuckDB.
// Data loaders live in src/data/*.py and run at build time via `uv run python`
// (project root is the parent pyproject, so uccc_genomics is importable).
export default {
  title: "UCCC vendor genomics",
  root: "src",
  interpreters: {".py": ["uv", "run", "python"]},
  head: `
    <script async src="https://www.googletagmanager.com/gtag/js?id=G-HR1PFD75WN"></script>
    <script>
      window.dataLayer = window.dataLayer || [];
      function gtag(){dataLayer.push(arguments);}
      gtag('js', new Date());

      gtag('config', 'G-HR1PFD75WN');
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
