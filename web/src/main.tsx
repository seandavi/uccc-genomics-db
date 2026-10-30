import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.tsx";
import { fetchAccount, fetchRequests, fetchTransport } from "./transport.ts";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App transport={fetchTransport()} account={fetchAccount()} requests={fetchRequests()} />
  </StrictMode>,
);
