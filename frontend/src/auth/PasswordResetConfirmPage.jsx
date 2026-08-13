import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Button, Input } from "@bristlecone/canopy";
import { useAuth } from "./useAuth";
import "./authForm.css";

function parseAccessTokenFromHash() {
  // Supabase's recovery email redirects here with the token in the URL
  // FRAGMENT (never sent to any server) — this is the one place Supabase's
  // own token briefly touches the browser; see backend/auth/supabase_client.py
  // for why that's an accepted, narrow exception. It is used exactly once,
  // below, and never stored.
  const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
  return new URLSearchParams(hash).get("access_token");
}

function PasswordResetConfirmPage() {
  const { confirmPasswordReset } = useAuth();
  const navigate = useNavigate();
  // Read once at mount — the fragment is static for the lifetime of this
  // page load, so a lazy initial state avoids a redundant effect+setState.
  const [accessToken] = useState(() => parseAccessTokenFromHash());
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");

    if (newPassword !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    if (!accessToken) {
      setError("This reset link is invalid or has expired. Request a new one.");
      return;
    }

    setSubmitting(true);
    try {
      await confirmPasswordReset({ accessToken, newPassword });
      setDone(true);
    } catch {
      setError("That reset link is invalid or has expired.");
    } finally {
      setSubmitting(false);
    }
  }

  if (done) {
    return (
      <div className="auth-form">
        <h1 className="auth-form__title">Password updated</h1>
        <p className="auth-form__subtitle">You can now sign in with your new password.</p>
        <Button className="auth-form__submit" onClick={() => navigate("/login", { replace: true })}>
          Go to sign in
        </Button>
      </div>
    );
  }

  return (
    <form className="auth-form" onSubmit={handleSubmit}>
      <h1 className="auth-form__title">Set a new password</h1>

      {error && <Alert variant="error">{error}</Alert>}

      <Input
        label="New password"
        type="password"
        autoComplete="new-password"
        value={newPassword}
        onChange={(e) => setNewPassword(e.target.value)}
        minLength={8}
        required
      />
      <Input
        label="Confirm new password"
        type="password"
        autoComplete="new-password"
        value={confirmPassword}
        onChange={(e) => setConfirmPassword(e.target.value)}
        minLength={8}
        required
      />

      <Button type="submit" loading={submitting} className="auth-form__submit">
        Update password
      </Button>
    </form>
  );
}

export default PasswordResetConfirmPage;
