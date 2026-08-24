import api from "./api";

// Thin async wrappers around the shared `api` instance — mirrors
// settings/connections/connectionsApi.js's convention. All of these back the
// Suspend & Resume / Stored Runs feature (see backend/routes/auto_pipeline.py).

export async function listStoredRuns() {
  const { data } = await api.get("/api/recon/auto-run/stored");
  return data;
}

export async function suspendRun(graphRunId, { name, reason } = {}) {
  const { data } = await api.post(`/api/recon/auto-run/${graphRunId}/suspend`, {
    name: name ?? null,
    reason: reason ?? "user requested suspend",
  });
  return data;
}

export async function resumeRun(graphRunId, { force = false } = {}) {
  const { data } = await api.post(`/api/recon/auto-run/${graphRunId}/resume`, { force });
  return data;
}

export async function deleteStoredRun(graphRunId) {
  const { data } = await api.delete(`/api/recon/auto-run/${graphRunId}`);
  return data;
}

export async function getPartialResults(graphRunId) {
  const { data } = await api.get(`/api/recon/auto-run/${graphRunId}/partial-results`);
  return data;
}

// Triggers a browser download rather than returning the CSV text — the
// export route streams `Content-Disposition: attachment`, so the response is
// fetched as a blob and handed to the browser via a throwaway object URL.
export async function exportPartialResults(graphRunId) {
  const res = await api.get(`/api/recon/auto-run/${graphRunId}/partial-results/export`, {
    responseType: "blob",
  });
  const url = window.URL.createObjectURL(res.data);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${graphRunId}_partial_results.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}
