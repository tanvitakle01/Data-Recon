import { createContext, useContext, useState } from "react";

const ReconciliationContext = createContext();

export const ReconciliationProvider = ({ children }) => {

  const [sourceFile, setSourceFile] = useState(null);
  const [targetFile, setTargetFile] = useState(null);

  const [sourcePreview, setSourcePreview] = useState(null);
  const [targetPreview, setTargetPreview] = useState(null);

  const [mapping, setMapping] = useState(null);

  const [comparisonResult, setComparisonResult] = useState(null);

  return (
    <ReconciliationContext.Provider
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
    </ReconciliationContext.Provider>
  );
};

export const useReconciliation = () =>
  useContext(ReconciliationContext);