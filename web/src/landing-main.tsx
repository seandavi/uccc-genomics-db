import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { Landing, discoverRedirect } from "./Landing.tsx";
import { fetchPublicSummary } from "./transport.ts";
import type { PublicSummary } from "./types.ts";
import "./styles.css";

function Root() {
  const [summary, setSummary] = useState<PublicSummary | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    fetchPublicSummary().then(setSummary, () => setError(true));
  }, []);
  return <Landing summary={summary} error={error} />;
}

const go = () => {
  const to = discoverRedirect(location.hash);
  if (to) location.replace(to);
  return to !== null;
};
window.addEventListener("hashchange", go);   // a share link pasted into an open landing tab (issue 104)
if (!go()) createRoot(document.getElementById("root")!).render(<StrictMode><Root /></StrictMode>);
