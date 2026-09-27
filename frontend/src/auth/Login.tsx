import { useState } from "react";
import axios from "axios";
import { ShieldCheck } from "lucide-react";

import api from "../api/client";
import { useAuth } from "./AuthContext";

function loginErrorMessage(error: unknown): string {
  if (!axios.isAxiosError(error) || !error.response) {
    return "Não foi possível acessar a API. Confirme que o backend está em execução.";
  }
  if (error.response.status === 401) return "Usuário ou senha inválidos.";
  return "Não foi possível entrar. Tente novamente.";
}

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { login } = useAuth();

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const response = await api.post("/api/v1/auth/login", { username, password });
      login(response.data.access_token);
    } catch (error) {
      setError(loginErrorMessage(error));
    }
  }

  return <main className="login-screen"><form className="login-card" onSubmit={handleSubmit}>
    <ShieldCheck size={26} color="#1c577e" aria-hidden="true" />
    <p className="eyebrow">CONFERÊNCIA FISCAL</p>
    <h2>Acesso seguro</h2>
    <p>Entre para consultar e revisar as auditorias da sua organização.</p>
    <label>Usuário<input autoComplete="username" required value={username} onChange={(event) => setUsername(event.target.value)} /></label>
    <label>Senha<input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
    {error ? <div className="notice notice-error" role="alert">{error}</div> : null}
    <button className="button button-primary" type="submit">Entrar</button>
  </form></main>;
}
