import ReactDOM from "react-dom/client";

import App from "./App";

import {
  ReconciliationProvider,
} from "./context/ReconciliationContext";

ReactDOM.createRoot(document.getElementById("root")).render(
  <ReconciliationProvider>
    <App />
  </ReconciliationProvider>
);



