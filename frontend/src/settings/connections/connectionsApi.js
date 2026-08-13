import api from "../../services/api";

export async function listConnections(kind) {
  const { data } = await api.get("/api/connections", { params: kind ? { kind } : {} });
  return data;
}

export async function testConnection(payload) {
  const { data } = await api.post("/api/connections/test", payload);
  return data;
}

export async function createConnection(payload) {
  const { data } = await api.post("/api/connections", payload);
  return data;
}

export async function updateConnection(id, payload) {
  const { data } = await api.put(`/api/connections/${id}`, payload);
  return data;
}

export async function deleteConnection(id) {
  await api.delete(`/api/connections/${id}`);
}
