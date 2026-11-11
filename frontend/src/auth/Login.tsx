import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { Eye, EyeOff, FileCheck2, History, LoaderCircle, ShieldCheck, UserCheck } from "lucide-react";

import api from "../api/client";
import { useAuth } from "./AuthContext";
import { ThemeToggle } from "../theme";

type LoginError = { message: string; credentials: boolean };

// A API gratuita na Render dorme depois de um tempo sem uso e leva perto de um
// minuto para acordar. Nesse intervalo ela responde 502/503/504 ou a conexão cai
// sem resposta; o login tenta de novo sozinho em vez de mostrar erro de imediato.
const SLOW_MS = 4000;
const MAX_ATTEMPTS = 3;
const RETRY_DELAY_MS = 3000;
const WAKING_STATUSES = new Set([502, 503, 504]);

function isServerWaking(error: unknown) {
  if (!axios.isAxiosError(error)) return false;
  if (!error.response) return error.code !== "ECONNABORTED";
  return WAKING_STATUSES.has(error.response.status);
}

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function requestLogin(username: string, password: string) {
  for (let attempt = 1; ; attempt += 1) {
    try {
      return await api.post<{ access_token: string }>("/api/v1/auth/login", { username, password });
    } catch (error) {
      if (attempt >= MAX_ATTEMPTS || !isServerWaking(error)) throw error;
      await wait(RETRY_DELAY_MS * attempt);
    }
  }
}

function loginError(error: unknown): LoginError {
  if (!axios.isAxiosError(error)) {
    return { message: "Não foi possível entrar. Tente novamente.", credentials: false };
  }
  if (error.response?.status === 401) return { message: "Usuário ou senha inválidos.", credentials: true };
  if (!error.response) {
    return { message: "Não foi possível falar com o servidor. Confira sua internet; se estiver tudo certo, o servidor pode estar iniciando: tente de novo em um minuto.", credentials: false };
  }
  if (WAKING_STATUSES.has(error.response.status)) {
    return { message: "O servidor ainda está iniciando. Tente de novo em um minuto.", credentials: false };
  }
  return { message: "Não foi possível entrar. Tente novamente.", credentials: false };
}

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<LoginError | null>(null);
  const [serverReady, setServerReady] = useState(false);
  const [submittedAt, setSubmittedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const openedAt = useRef(Date.now());
  const passwordRef = useRef<HTMLInputElement>(null);
  const { login } = useAuth();

  // Acorda a API assim que a tela abre, enquanto a pessoa digita.
  useEffect(() => {
    let active = true;
    api.get("/health", { timeout: 90_000 })
      .catch(() => undefined)
      .finally(() => { if (active) setServerReady(true); });
    return () => { active = false; };
  }, []);

  const waitingSince = !serverReady ? openedAt.current : submittedAt;
  useEffect(() => {
    if (waitingSince === null) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [waitingSince]);

  const waitedMs = waitingSince === null ? 0 : Math.max(0, now - waitingSince);
  const showWaking = waitingSince !== null && waitedMs >= SLOW_MS;
  const waitedSeconds = Math.floor(waitedMs / 1000);

  function clearError() {
    if (error) setError(null);
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    setSubmittedAt(Date.now());
    setNow(Date.now());
    try {
      const response = await requestLogin(username, password);
      login(response.data.access_token);
    } catch (error) {
      const failure = loginError(error);
      if (axios.isAxiosError(error) && error.response && !isServerWaking(error)) setServerReady(true);
      setError(failure);
      setSubmitting(false);
      setSubmittedAt(null);
      if (failure.credentials) {
        passwordRef.current?.focus();
        passwordRef.current?.select();
      }
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
        <ThemeToggle className="login-theme" />
        <form className="login-form" onSubmit={handleSubmit}>
          <header>
            <h2>Entrar</h2>
            <p>Use as credenciais da sua organização.</p>
          </header>
          <div className="field">
            <label htmlFor="username">Usuário</label>
            <input id="username" autoComplete="username" autoFocus required value={username} aria-invalid={error?.credentials || undefined} aria-describedby={error ? "login-error" : undefined} onChange={(event) => { setUsername(event.target.value); clearError(); }} />
          </div>
          <div className="field">
            <label htmlFor="password">Senha</label>
            <div className="password-wrap">
              <input ref={passwordRef} id="password" type={showPassword ? "text" : "password"} autoComplete="current-password" required value={password} aria-invalid={error?.credentials || undefined} aria-describedby={error ? "login-error" : undefined} onChange={(event) => { setPassword(event.target.value); clearError(); }} />
              <button type="button" className="password-toggle" onClick={() => setShowPassword((value) => !value)} aria-label="Mostrar senha" aria-pressed={showPassword}>
                {showPassword ? <EyeOff size={16} aria-hidden="true" /> : <Eye size={16} aria-hidden="true" />}
              </button>
            </div>
          </div>
          {error ? <div className="notice notice-error" id="login-error" role="alert">{error.message}</div> : null}
          <div className="login-status" role="status">
            {showWaking && !error ? <div className="notice notice-info">
              <LoaderCircle className="spin" size={16} aria-hidden="true" />
              <span>
                {submitting
                  ? "O servidor está iniciando. Pode levar até 1 minuto; não precisa clicar de novo."
                  : "Preparando o servidor. Pode levar até 1 minuto na primeira entrada do dia; você já pode digitar."}
                <span className="notice-timer" aria-hidden="true"> {waitedSeconds} s</span>
              </span>
            </div> : null}
          </div>
          <button className="button button-primary button-lg" type="submit" disabled={submitting}>
            {submitting ? <><LoaderCircle className="spin" size={16} aria-hidden="true" /> Entrando</> : "Entrar"}
          </button>
        </form>
      </main>
    </div>
  );
}
