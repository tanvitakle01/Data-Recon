import { Navigate } from "react-router-dom";
import { useAuth } from "./useAuth";

/** Route guard: renders children only once the session is confirmed. */
function RequireAuth({ children }) {
  const { status } = useAuth();
  if (status === "anonymous") return <Navigate to="/login" replace />;
  return children;
}

export default RequireAuth;
