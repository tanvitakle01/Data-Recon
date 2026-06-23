import { useState } from "react";
import api from "../api/api";

function S4Preview() {
  const [loading, setLoading] = useState(false);
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");

  const loadSalesOrders = async () => {
    setLoading(true);
    setError("");
    setRows([]);

    try {
      const response = await api.get("/api/s4/test-preview");
      console.log("API Response", response.data);
      console.log("Rows", response.data.data);

      if (response.data?.success) {
        setRows(response.data.data || []);
      } else {
        setError(response.data?.error || "Connection Failed");
      }
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Connection Failed");
    } finally {
      setLoading(false);
    }
  };

  // Backend currently returns header-level A_SalesOrder rows.
  // Render the keys that actually exist in that payload.
  const columns = [
    { key: "SalesOrder", label: "Sales Order" },
    { key: "SalesOrderType", label: "Order Type" },
    { key: "SoldToParty", label: "Customer" },
    { key: "RequestedDeliveryDate", label: "Requested Delivery Date" },
    { key: "TotalNetAmount", label: "Net Amount" },
  ];

  return (
    <div style={{ maxWidth: "1200px", margin: "0 auto", padding: "20px" }}>
      <h1>SAP S/4 Preview Test</h1>

      <button onClick={loadSalesOrders} disabled={loading}>
        Load Sales Orders
      </button>

      <div style={{ marginTop: "16px" }}>
        {loading && <div>Loading SAP data...</div>}

        {!loading && error && (
          <div>
            <div>Connection Failed</div>
            <div>{error}</div>
          </div>
        )}

        {!loading && !error && rows && rows.length > 0 && (
          <div>
            <div>Connection Successful</div>
            <div>Rows Returned: {rows.length}</div>
          </div>
        )}

        {!loading && !error && rows && rows.length === 0 && (
          <div>Connection Successful</div>
        )}

        {!loading && !error && rows && rows.length > 0 && (
          <table
            border="1"
            cellPadding="6"
            cellSpacing="0"
            style={{ marginTop: "12px", width: "100%" }}
          >
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c.key}>{c.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, idx) => (
                <tr key={idx}>
                  {columns.map((c) => (
                    <td key={c.key}>{r?.[c.key] ?? ""}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export default S4Preview;


