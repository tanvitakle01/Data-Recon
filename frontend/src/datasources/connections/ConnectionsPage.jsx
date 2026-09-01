import { useCallback, useEffect, useState } from "react";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  ConfirmDialog,
  Modal,
  Spinner,
} from "@bristlecone/canopy";
import ConnectionForm from "./ConnectionForm";
import * as connectionsApi from "./connectionsApi";
import "./connectionsPage.css";

const KIND_LABELS = { s4: "SAP S/4HANA", ibp: "SAP IBP" };

function statusBadge(conn) {
  if (!conn.enabled) return <Badge variant="default">Disabled</Badge>;
  if (conn.last_test_status === "success") return <Badge variant="success">Verified</Badge>;
  if (conn.last_test_status === "failure") return <Badge variant="error">Test failing</Badge>;
  return <Badge variant="warning">Not yet tested</Badge>;
}

function ConnectionsPage() {
  const [connections, setConnections] = useState([]);
  const [loading, setLoading] = useState(true);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [pendingDelete, setPendingDelete] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setConnections(await connectionsApi.listConnections());
    } finally {
      setLoading(false);
    }
  }, []);

  // Mount fetch deliberately doesn't call `load()` (which synchronously
  // sets `loading` before its first await) — matches the pattern in
  // AuthContext.jsx: state updates happen only inside the .then/.finally
  // callback, never synchronously in the effect body itself.
  useEffect(() => {
    let active = true;
    connectionsApi
      .listConnections()
      .then((data) => {
        if (active) setConnections(data);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  function openCreate() {
    setEditing(null);
    setFormOpen(true);
  }

  function openEdit(conn) {
    setEditing(conn);
    setFormOpen(true);
  }

  function handleSaved() {
    setFormOpen(false);
    setEditing(null);
    load();
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    await connectionsApi.deleteConnection(pendingDelete.id);
    setPendingDelete(null);
    load();
  }

  return (
    <div className="connections-page">
      <div className="connections-page__header">
        <div>
          <h3 className="connections-page__title">Connections</h3>
          <p className="connections-page__subtitle">
            SAP and live-system connections used for reconciliation fetches. Credentials are encrypted and
            never shown once saved.
          </p>
        </div>
        <Button onClick={openCreate}>Add connection</Button>
      </div>

      {loading ? (
        <Spinner label="Loading connections" />
      ) : connections.length === 0 ? (
        <Card className="connections-page__empty">
          <CardContent>No connections yet. Add one to enable live fetch.</CardContent>
        </Card>
      ) : (
        <div className="connections-page__list">
          {connections.map((conn) => (
            <Card key={conn.id} className="connections-page__card">
              <CardHeader className="connections-page__card-header">
                <div>
                  <CardTitle>{conn.name}</CardTitle>
                  <p className="connections-page__card-meta">
                    {KIND_LABELS[conn.kind] || conn.kind} · {conn.environment.toUpperCase()} · {conn.base_url}
                  </p>
                </div>
                <div className="connections-page__badges">
                  {conn.skip_tls_verify && <Badge variant="error">TLS verification off</Badge>}
                  {statusBadge(conn)}
                </div>
              </CardHeader>
              <CardContent className="connections-page__card-actions">
                <Button variant="outline" size="sm" onClick={() => openEdit(conn)}>
                  Edit
                </Button>
                <Button variant="destructive" size="sm" onClick={() => setPendingDelete(conn)}>
                  Delete
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Modal open={formOpen} onClose={() => setFormOpen(false)} title={editing ? "Edit connection" : "Add connection"}>
        <ConnectionForm existing={editing} onSaved={handleSaved} onCancel={() => setFormOpen(false)} />
      </Modal>

      <ConfirmDialog
        isOpen={Boolean(pendingDelete)}
        title="Delete connection"
        message={`Delete "${pendingDelete?.name}"? This cannot be undone.`}
        confirmText="Delete"
        variant="destructive"
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}

export default ConnectionsPage;
