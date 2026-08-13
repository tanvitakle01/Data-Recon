import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Alert, Button, Input } from "@bristlecone/canopy";
import { useAuth } from "./useAuth";
import "./authForm.css";

function LoginPage() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await signIn({ email, password });
      navigate("/home", { replace: true });
    } catch {
      // Generic on purpose — never reveal whether the email is registered.
      setError("Invalid email or password.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="auth-form" onSubmit={handleSubmit}>
      <h1 className="auth-form__title">Sign in</h1>
      <p className="auth-form__subtitle">Welcome back. Enter your details to continue.</p>

      {error && <Alert variant="error">{error}</Alert>}

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
        autoComplete="current-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
      />

      <Button type="submit" loading={submitting} className="auth-form__submit">
        Sign in
      </Button>

      <div className="auth-form__links">
        <Link to="/password-reset">Forgot password?</Link>
        <Link to="/signup">Create an account</Link>
      </div>
    </form>
  );
}

export default LoginPage;
