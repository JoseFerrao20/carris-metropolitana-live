import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { User } from "../api/types";

export type AuthStatus = "loading" | "anonymous" | "authenticated";

interface AuthValue {
  status: AuthStatus;
  user: User | null;
  favorites: ReadonlySet<string>;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  /** Alterna uma favorita de forma otimista; se o servidor falhar, repõe e relança o erro. */
  toggleFavorite: (lineId: string) => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [favorites, setFavorites] = useState<ReadonlySet<string>>(new Set());

  const loadFavorites = useCallback(async () => {
    setFavorites(new Set(await api.favorites()));
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .me()
      .then(async (u) => {
        if (cancelled) return;
        setUser(u);
        setStatus(u ? "authenticated" : "anonymous");
        if (u) await loadFavorites();
      })
      .catch(() => !cancelled && setStatus("anonymous"));
    return () => {
      cancelled = true;
    };
  }, [loadFavorites]);

  const afterSignIn = useCallback(
    async (u: User) => {
      setUser(u);
      setStatus("authenticated");
      await loadFavorites();
    },
    [loadFavorites],
  );

  const login = useCallback(async (e: string, p: string) => afterSignIn(await api.login(e, p)), [afterSignIn]);
  const register = useCallback(async (e: string, p: string) => afterSignIn(await api.register(e, p)), [afterSignIn]);

  const logout = useCallback(async () => {
    await api.logout();
    setUser(null);
    setStatus("anonymous");
    setFavorites(new Set());
  }, []);

  const toggleFavorite = useCallback(
    async (lineId: string) => {
      const had = favorites.has(lineId);
      const flip = (add: boolean) =>
        setFavorites((prev) => {
          const next = new Set(prev);
          if (add) next.add(lineId);
          else next.delete(lineId);
          return next;
        });
      flip(!had);
      try {
        await (had ? api.removeFavorite(lineId) : api.addFavorite(lineId));
      } catch (e) {
        flip(had);
        throw e;
      }
    },
    [favorites],
  );

  const value = useMemo<AuthValue>(
    () => ({ status, user, favorites, login, register, logout, toggleFavorite }),
    [status, user, favorites, login, register, logout, toggleFavorite],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth tem de ser usado dentro de <AuthProvider>");
  return ctx;
}
