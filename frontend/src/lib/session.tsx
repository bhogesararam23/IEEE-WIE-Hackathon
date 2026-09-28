import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, tokenStore, type CurrentUser } from "./api";

type SessionStatus = "loading" | "anonymous" | "authenticated";

interface SessionValue {
  status: SessionStatus;
  user: CurrentUser | null;
  login: (email: string, password: string) => Promise<void>;
  loginWithGoogle: (idToken: string) => Promise<void>;
  signup: (full_name: string, email: string, password: string) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
  setUser: (user: CurrentUser) => void;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SessionStatus>("loading");
  const [user, setUser] = useState<CurrentUser | null>(null);

  const loadUser = useCallback(async () => {
    if (!tokenStore.read()) {
      setStatus("anonymous");
      setUser(null);
      return;
    }
    try {
      setUser(await api.me());
      setStatus("authenticated");
    } catch {
      // An expired or forged token: drop it so the sign-in screen is reachable.
      tokenStore.clear();
      setUser(null);
      setStatus("anonymous");
    }
  }, []);

  useEffect(() => {
    void loadUser();
  }, [loadUser]);

  const value = useMemo<SessionValue>(
    () => ({
      status,
      user,
      login: async (email, password) => {
        tokenStore.write((await api.login({ email, password })).access_token);
        await loadUser();
      },
      loginWithGoogle: async (idToken) => {
        // No separate giveConsent() call: the backend stamps consent at
        // account creation for a brand-new Google account, matching what
        // signup() below does in two round-trips instead of one.
        tokenStore.write((await api.googleLogin(idToken)).access_token);
        await loadUser();
      },
      signup: async (full_name, email, password) => {
        tokenStore.write(
          (await api.signup({ full_name, email, password })).access_token,
        );
        await api.giveConsent();
        await loadUser();
      },
      logout: () => {
        tokenStore.clear();
        setUser(null);
        setStatus("anonymous");
      },
      refresh: loadUser,
      setUser,
    }),
    [status, user, loadUser],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const context = useContext(SessionContext);
  if (!context) throw new Error("useSession must be used inside SessionProvider");
  return context;
}

/** Reload `data` when `deps` change or `reload()` is called, and expose the flags screens need. */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    loader()
      .then((result) => {
        if (active) {
          setData(result);
          setError(null);
        }
      })
      .catch((cause: Error) => {
        if (active) setError(cause.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
    // The caller owns the dependency list; `nonce` is the manual refresh handle.
  }, [...deps, nonce]);

  return {
    data,
    error,
    loading,
    reload: () => setNonce((count) => count + 1),
    setData,
  };
}
