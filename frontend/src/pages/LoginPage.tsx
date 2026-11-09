import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

type Mode = "login" | "register";

const PASSWORD_MIN = 10; // igual ao backend (cmlive.web.auth)

export function LoginPage() {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/analytics";

  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const errorRef = useRef<HTMLParagraphElement>(null);
  const ids = { email: useId(), password: useId(), hint: useId(), error: useId() };

  // Leva o foco para o erro, para quem usa leitor de ecrã ou teclado saber o que falhou.
  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (mode === "register" && password.length < PASSWORD_MIN) {
      setError(`A password tem de ter pelo menos ${PASSWORD_MIN} caracteres.`);
      return;
    }
    setPending(true);
    try {
      await (mode === "login" ? login(email, password) : register(email, password));
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível concluir o pedido.");
    } finally {
      setPending(false);
    }
  };

  const isLogin = mode === "login";
  const title = isLogin ? "Entrar" : "Criar conta";
  return (
    <main className="auth">
      <h1>{title}</h1>
      <p className="muted">
        Com uma conta pode guardar as suas linhas favoritas e vê-las destacadas no mapa e na análise.
      </p>

      <form className="card form" onSubmit={onSubmit} noValidate aria-describedby={error ? ids.error : undefined}>
        {error && (
          <p id={ids.error} ref={errorRef} className="form-error" role="alert" tabIndex={-1}>
            {error}
          </p>
        )}
        <div className="field">
          <label htmlFor={ids.email}>Email</label>
          <input
            id={ids.email}
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-invalid={error ? true : undefined}
          />
        </div>
        <div className="field">
          <label htmlFor={ids.password}>Password</label>
          <input
            id={ids.password}
            type="password"
            autoComplete={isLogin ? "current-password" : "new-password"}
            required
            minLength={isLogin ? undefined : PASSWORD_MIN}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={isLogin ? undefined : ids.hint}
          />
          {!isLogin && (
            <p id={ids.hint} className="muted small">
              Pelo menos {PASSWORD_MIN} caracteres.
            </p>
          )}
        </div>
        <button type="submit" className="primary" disabled={pending} aria-busy={pending}>
          {pending ? "A enviar…" : title}
        </button>
      </form>

      <p>
        {isLogin ? "Ainda não tem conta? " : "Já tem conta? "}
        <button
          type="button"
          className="link"
          onClick={() => {
            setMode(isLogin ? "register" : "login");
            setError(null);
          }}
        >
          {isLogin ? "Criar conta" : "Entrar"}
        </button>
      </p>
      <p>
        <Link to="/">← mapa ao vivo</Link> · <Link to="/analytics">análise de atrasos</Link>
      </p>
    </main>
  );
}
