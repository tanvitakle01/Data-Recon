import api from "../services/api";

export async function signUp({ email, password, fullName, organizationName }) {
  const { data } = await api.post("/api/auth/signup", {
    email,
    password,
    full_name: fullName,
    organization_name: organizationName,
  });
  return data;
}

export async function signIn({ email, password }) {
  const { data } = await api.post("/api/auth/signin", { email, password });
  return data;
}

export async function signOut() {
  await api.post("/api/auth/signout");
}

export async function fetchCurrentUser() {
  const { data } = await api.get("/api/auth/me");
  return data;
}

export async function requestPasswordReset(email) {
  await api.post("/api/auth/password-reset/request", { email });
}

export async function confirmPasswordReset({ accessToken, newPassword }) {
  await api.post("/api/auth/password-reset/confirm", {
    access_token: accessToken,
    new_password: newPassword,
  });
}
