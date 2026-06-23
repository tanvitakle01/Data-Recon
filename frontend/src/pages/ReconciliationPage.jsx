import { useMemo, useState } from "react";
import api from "../api/api";
import UploadSection from "../components/UploadSection";

function ReconciliationPage() {
  const pageStyle = useMemo(
    () => ({
      maxWidth: "1200px",
      margin: "0 auto",
      padding: "20px",
    }),
    [],
  );

  return (
    <div style={pageStyle}>
      <h1>Data Reconciliation</h1>
      <p>Select Source + Target files, then run reconciliation (mapping happens inside the backend).</p>

      {/* Single Step-1 UI source of truth (prevents duplicate radio groups/forms). */}
      <UploadSection />
    </div>
  );
}

export default ReconciliationPage;







