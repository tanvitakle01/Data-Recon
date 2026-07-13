import { useState } from "react";
import { useTicketing } from "../../../ticketing/useTicketing";
import TeamList from "./TeamList";
import TeamFormModal from "./TeamFormModal";
import TeamDetailsDrawer from "./TeamDetailsDrawer";

export default function TeamsTab() {
  const { teams, members, createTeam, updateTeam, deleteTeam } = useTicketing();
  const [creating, setCreating] = useState(false);
  const [editingTeam, setEditingTeam] = useState(null);
  const [viewingTeam, setViewingTeam] = useState(null);
  const [deleteError, setDeleteError] = useState(null);

  const handleDelete = (team) => {
    const result = deleteTeam(team.key);
    if (!result.success) {
      setDeleteError({ teamName: team.name, reason: result.reason });
      window.setTimeout(() => setDeleteError(null), 4000);
    }
  };

  return (
    <div>
      {deleteError ? (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
          Can't delete "{deleteError.teamName}": {deleteError.reason}
        </div>
      ) : null}

      <TeamList
        teams={teams}
        members={members}
        onCreate={() => setCreating(true)}
        onEdit={setEditingTeam}
        onDelete={handleDelete}
        onViewDetails={setViewingTeam}
      />

      {creating ? (
        <TeamFormModal onClose={() => setCreating(false)} onSave={(form) => createTeam(form)} />
      ) : null}

      {editingTeam ? (
        <TeamFormModal team={editingTeam} onClose={() => setEditingTeam(null)} onSave={(form) => updateTeam(editingTeam.key, form)} />
      ) : null}

      {viewingTeam ? <TeamDetailsDrawer team={viewingTeam} onClose={() => setViewingTeam(null)} /> : null}
    </div>
  );
}
