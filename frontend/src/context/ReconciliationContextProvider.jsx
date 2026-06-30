import { useState } from "react";

import ReconciliationContextInternal from "./ReconciliationContextInternal";

export function ReconciliationProvider({ children }) {
  const [sourceFile, setSourceFile] = useState(null);
  const [targetFile, setTargetFile] = useState(null);

  const [sourcePreview, setSourcePreview] = useState(null);
  const [targetPreview, setTargetPreview] = useState(null);

  const [mapping, setMapping] = useState(null);

  const [comparisonResult, setComparisonResult] = useState(null);

  return (
    <ReconciliationContextInternal.Provider
      value={{
        sourceFile,
        setSourceFile,

        targetFile,
        setTargetFile,

        sourcePreview,
        setSourcePreview,

        targetPreview,
        setTargetPreview,

        mapping,
        setMapping,

        comparisonResult,
        setComparisonResult,
      }}
    >
      {children}
    </ReconciliationContextInternal.Provider>
  );
}

