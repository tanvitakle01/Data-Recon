import React from "react";
import ReactDOM from "react-dom/client";

// Bundled variable fonts (no CDN): Inter for UI, JetBrains Mono for identifiers.
import "@fontsource-variable/inter/wght.css";
import "@fontsource-variable/jetbrains-mono/wght.css";

import "./styles/redesign.css";
import RedesignApp from "./RedesignApp";

ReactDOM.createRoot(document.getElementById("rdx-root")).render(
  <React.StrictMode>
    <RedesignApp />
  </React.StrictMode>
);
