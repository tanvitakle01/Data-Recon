import { useState } from "react";
import ReconciliationPage from "./pages/ReconciliationPage";

function App() {
  const [mode] = useState("s4-preview");

  return <ReconciliationPage />;
}


export default App;



