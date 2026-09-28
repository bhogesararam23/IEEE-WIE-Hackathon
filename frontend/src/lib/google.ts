/**
 * Thin wrapper around Google Identity Services (loaded in index.html), so
 * SignIn.tsx doesn't need to know about `window.google`'s shape. GIS has no
 * official npm types package for the plain <script> embed, so this declares
 * only the handful of members actually used here.
 */

interface GoogleCredentialResponse {
  credential: string;
}

interface GoogleIdConfiguration {
  client_id: string;
  callback: (response: GoogleCredentialResponse) => void;
}

interface GoogleButtonOptions {
  type?: "standard" | "icon";
  theme?: "outline" | "filled_blue" | "filled_black";
  size?: "large" | "medium" | "small";
  width?: number;
  text?: "signin_with" | "signup_with" | "continue_with" | "signin";
}

interface GoogleAccountsId {
  initialize: (config: GoogleIdConfiguration) => void;
  renderButton: (parent: HTMLElement, options: GoogleButtonOptions) => void;
}

declare global {
  interface Window {
    google?: { accounts: { id: GoogleAccountsId } };
  }
}

export const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined;

/**
 * Renders the "Sign in with Google" button into `container` once the GIS
 * script has loaded. Polls briefly rather than assuming it's already there:
 * the script tag is `async defer`, so it can still be loading when this
 * component first mounts.
 */
export function renderGoogleButton(
  container: HTMLElement,
  onCredential: (idToken: string) => void,
): () => void {
  let cancelled = false;
  let attempts = 0;

  const tryRender = () => {
    if (cancelled) return;
    if (window.google?.accounts?.id && googleClientId) {
      window.google.accounts.id.initialize({
        client_id: googleClientId,
        callback: (response) => onCredential(response.credential),
      });
      window.google.accounts.id.renderButton(container, {
        type: "standard",
        theme: "outline",
        size: "large",
        text: "signin_with",
      });
      return;
    }
    attempts += 1;
    if (attempts < 40) setTimeout(tryRender, 150); // ~6s ceiling
  };

  tryRender();
  return () => {
    cancelled = true;
  };
}
