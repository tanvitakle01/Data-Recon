import { useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Button, Input } from "@bristlecone/canopy";
import { useAuth } from "./useAuth";
import "./authForm.css";

function PasswordResetRequestPage() {
  const { requestPasswordReset } = useAuth();
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await requestPasswordReset(email);
    } finally {
      // Always the same outcome, whether or not the email is registered —
      // that symmetry is what prevents email enumeration.
      setSubmitting(false);
      setSent(true);
    }
  }

  if (sent) {
    return (
      <div className="auth-form">
        <h1 className="auth-form__title">Check your email</h1>
        <Alert variant="info">
          If an account exists for that email address, we've sent instructions to reset the password.
        </Alert>
        <p className="auth-form__footnote">
          <Link to="/login">Back to sign in</Link>
        </p>
      </div>
    );
  }

  return (
    <form className="auth-form" onSubmit={handleSubmit}>
      <h1 className="auth-form__title">Reset your password</h1>
      <p className="auth-form__subtitle">
        Enter your work email and we'll send you a link to reset your password.
      </p>

      <Input
        label="Work email"
        type="email"
        autoComplete="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        required
      />

      <Button type="submit" loading={submitting} className="auth-form__submit">
        Send reset link
      </Button>

      <p className="auth-form__footnote">
        <Link to="/login">Back to sign in</Link>
      </p>
    </form>
  );
}

export default PasswordResetRequestPage;
