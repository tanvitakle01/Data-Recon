import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Alert, Button, Input } from "@bristlecone/canopy";
import { useAuth } from "./useAuth";
import "./authForm.css";

const GENERIC_SIGNUP_ERROR = "Unable to create your account. Please check your details and try again.";

function SignUpPage() {
  const { signUp } = useAuth();
  const navigate = useNavigate();
  const [fullName, setFullName] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");

    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }

    setSubmitting(true);
    try {
      await signUp({ email, password, fullName, organizationName });
      navigate("/home", { replace: true });
    } catch {
      setError(GENERIC_SIGNUP_ERROR);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="auth-form" onSubmit={handleSubmit}>
      <h1 className="auth-form__title">Create your account</h1>
      <p className="auth-form__subtitle">
        This creates a new organization with you as its owner.
      </p>

      {error && <Alert variant="error">{error}</Alert>}

      <Input
        label="Full name"
        autoComplete="name"
        value={fullName}
        onChange={(e) => setFullName(e.target.value)}
        required
      />
      <Input
        label="Organization name"
        autoComplete="organization"
        value={organizationName}
        onChange={(e) => setOrganizationName(e.target.value)}
        required
      />
      <Input
        label="Work email"
        type="email"
        autoComplete="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        required
      />
      <Input
        label="Password"
        type="password"
        autoComplete="new-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        minLength={8}
        required
      />
      <Input
        label="Confirm password"
        type="password"
        autoComplete="new-password"
        value={confirmPassword}
        onChange={(e) => setConfirmPassword(e.target.value)}
        minLength={8}
        required
      />

      <Button type="submit" loading={submitting} className="auth-form__submit">
        Create account
      </Button>

      <p className="auth-form__footnote">
        Already have an account? <Link to="/login">Sign in</Link>
      </p>
    </form>
  );
}

export default SignUpPage;
