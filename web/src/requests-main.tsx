import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RequestsPage } from "./Requests.tsx";
import { fetchAccount, fetchRequests } from "./transport.ts";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RequestsPage api={fetchRequests()} account={fetchAccount()} />
  </StrictMode>,
);
