import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./uploads-browser.css";
import { UploadsBrowserApp } from "./UploadsBrowserApp";

createRoot(document.getElementById("uploads-root")!).render(
  <StrictMode>
    <UploadsBrowserApp />
  </StrictMode>,
);
