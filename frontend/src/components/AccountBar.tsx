import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

/** Estado da sessão: "Entrar" ou "email · Sair". */
export function AccountBar() {
  const { status, user, logout } = useAuth();
  const location = useLocation();
  const [error, setError] = useState<string | null>(null);

  if (status === "loading") return null;
  if (!user) {
    return (
      <Link to="/entrar" state={{ from: location.pathname }} className="account">
        Entrar para guardar linhas favoritas
      </Link>
    );
  }
  return (
    <span className="account">
      <span>{user.email}</span>
      {" · "}
      <button
        type="button"
        className="link"
        onClick={() => logout().catch(() => setError("Não foi possível terminar a sessão."))}
      >
        Sair
      </button>
      {error && <span role="alert"> {error}</span>}
    </span>
  );
}
