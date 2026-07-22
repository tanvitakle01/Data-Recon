import ReactDOM from "react-dom/client";

// Bundled variable fonts (no runtime network / CDN): Inter for UI, JetBrains
// Mono for technical identifiers (PRDID, VBAP-MATNR, contract IDs, …).
import "@fontsource-variable/inter/wght.css";
import "@fontsource-variable/jetbrains-mono/wght.css";

import "./index.css";
import "./styles/reconciliation.css";

import App from "./App";

ReactDOM.createRoot(document.getElementById("root")).render(<App />);



