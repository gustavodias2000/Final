import { useState } from "react";
import axios from "axios";
import { Eye, EyeOff, FileCheck2, History, LoaderCircle, ShieldCheck, UserCheck } from "lucide-react";

import api from "../api/client";
import { useAuth } from "./AuthContext";

type LoginError = { message: string; credentials: boolean };

function loginError(error: unknown): LoginError {
  if (!axios.isAxiosError(error) || !error.response) {
    return { message: "Não foi possível conectar ao servidor. Tente novamente em instantes.", credentials: false };
  }
  if (error.response.status === 401) return { message: "Usuário ou senha inválidos.", credentials: true };
  return { message: "Não foi possível entrar. Tente novamente.", credentials: false };
}

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<LoginError | null>(null);
  const { login } = useAuth();

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const response = await api.post("/api/v1/auth/login", { username, password });
      login(response.data.access_token);
    } catch (error) {
      setError(loginError(error));
      setSubmitting(false);
    }
  }

  return (
    <div className="login">
      <aside className="login-aside">
        <div className="brand">
          <span className="brand-mark"><ShieldCheck size={17} strokeWidth={2} aria-hidden="true" /></span>
          Auditor NCM/CEST
        </div>
        <div>
          <h1>Da planilha à decisão rastreável.</h1>
          <p>Confira a classificação fiscal do seu cadastro com recomendações que mostram de onde vieram.</p>
        </div>
        <ul className="login-facts">
          <li><FileCheck2 size={17} aria-hidden="true" />Cada sugestão de NCM e CEST traz a fonte consultada.</li>
          <li><UserCheck size={17} aria-hidden="true" />Nada é aplicado sem a aprovação de uma pessoa.</li>
          <li><History size={17} aria-hidden="true" />Decisões exportáveis para o seu registro de auditoria.</li>
        </ul>
      </aside>

      <main className="login-main">
        <form className="login-form" onSubmit={handleSubmit}>
          <header>
            <h2>Entrar</h2>
            <p>Use as credenciais da sua organização.</p>
          </header>
          <div className="field">
            <label htmlFor="username">Usuário</label>
            <input id="username" autoComplete="username" autoFocus required value={username} aria-invalid={error?.credentials || undefined} aria-describedby={error ? "login-error" : undefined} onChange={(event) => setUsername(event.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="password">Senha</label>
            <div className="password-wrap">
              <input id="password" type={showPassword ? "text" : "password"} autoComplete="current-password" required value={password} aria-invalid={error?.credentials || undefined} aria-describedby={error ? "login-error" : undefined} onChange={(event) => setPassword(event.target.value)} />
              <button type="button" className="password-toggle" onClick={() => setShowPassword((value) => !value)} aria-label="Mostrar senha" aria-pressed={showPassword}>
                {showPassword ? <EyeOff size={16} aria-hidden="true" /> : <Eye size={16} aria-hidden="true" />}
              </button>
            </div>
          </div>
          {error ? <div className="notice notice-error" id="login-error" role="alert">{error.message}</div> : null}
          <button className="button button-primary button-lg" type="submit" disabled={submitting}>
            {submitting ? <><LoaderCircle className="spin" size={16} aria-hidden="true" /> Entrando</> : "Entrar"}
          </button>
        </form>
      </main>
    </div>
  );
}
