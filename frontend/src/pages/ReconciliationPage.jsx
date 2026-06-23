import { useMemo, useState } from "react";
import api from "../api/api";
import UploadSection from "../components/UploadSection";
import Mapping from "../components/Mapping";

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
      <h1>Data Reconciliation Module</h1>
      <p>Select Source & Target files, then run reconciliation</p>
      <UploadSection />
    </div>
  );
}

export default ReconciliationPage;







