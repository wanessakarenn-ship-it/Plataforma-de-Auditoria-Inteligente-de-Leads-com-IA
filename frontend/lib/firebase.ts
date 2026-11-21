import { getApps, initializeApp, type FirebaseApp } from "firebase/app";
import {
  getAuth,
  GoogleAuthProvider,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut,
  type Auth,
  type User,
} from "firebase/auth";

const config = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY ?? "",
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN ?? "",
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID ?? "",
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID ?? "",
};
const appName = "bc-lead-intelligence";
const expectedProjectId = "prime-amulet-439718-e3";
const backendUrl = process.env.NEXT_PUBLIC_API_URL?.trim() ?? "";

export const isPreviewEnvironment = process.env.NEXT_PUBLIC_APP_ENV === "preview";

export function getBackendUnavailableReason() {
  if (isPreviewEnvironment) {
    return "O backend FastAPI não foi publicado. Operações que dependem da API estão indisponíveis neste ambiente de testes.";
  }
  if (!backendUrl) {
    return "O backend FastAPI não está configurado neste ambiente. Operações que dependem da API estão indisponíveis.";
  }

  let parsedUrl: URL;
  try {
    parsedUrl = new URL(backendUrl);
  } catch {
    return "NEXT_PUBLIC_API_URL não contém uma URL válida.";
  }

  if (
    process.env.NODE_ENV === "production" &&
    (parsedUrl.protocol !== "https:" ||
      parsedUrl.hostname === "localhost" ||
      parsedUrl.hostname === "127.0.0.1" ||
      parsedUrl.hostname === "::1")
  ) {
    return "A URL da API de produção deve usar HTTPS e não pode apontar para localhost.";
  }

  return null;
}

function matchesConfig(app: FirebaseApp) {
  return (
    app.options.apiKey === config.apiKey &&
    app.options.authDomain === config.authDomain &&
    app.options.projectId === config.projectId &&
    app.options.appId === config.appId
  );
}

export type AppRole = "admin" | "auditor" | "gestor";

export function isFirebaseConfigured() {
  if (!Object.values(config).every(Boolean) || config.projectId !== expectedProjectId) {
    return false;
  }
  const existingApp = getApps().find((item) => item.name === appName);
  return !existingApp || matchesConfig(existingApp);
}

export function getFirebaseAuth(): Auth {
  if (!Object.values(config).every(Boolean)) {
    throw new Error("Firebase web app configuration is missing.");
  }
  if (config.projectId !== expectedProjectId) {
    throw new Error("Firebase web app configuration uses an unexpected project.");
  }
  const existingApp = getApps().find((item) => item.name === appName);
  if (existingApp && !matchesConfig(existingApp)) {
    throw new Error("Firebase app is already initialized with a different configuration.");
  }
  const app = existingApp ?? initializeApp(config, appName);
  return getAuth(app);
}

export async function signInWithEmail(email: string, password: string) {
  return signInWithEmailAndPassword(getFirebaseAuth(), email, password);
}

export async function signInWithGoogle() {
  return signInWithPopup(getFirebaseAuth(), new GoogleAuthProvider());
}

export function observeFirebaseUser(
  callback: (user: User | null) => void,
  onError: (error: Error) => void,
) {
  return onAuthStateChanged(getFirebaseAuth(), callback, onError);
}

export async function signOutFromFirebase() {
  await signOut(getFirebaseAuth());
}

export async function fetchWithFirebaseToken(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const unavailableReason = getBackendUnavailableReason();
  if (unavailableReason) {
    throw new Error(unavailableReason);
  }

  const baseUrl = new URL(backendUrl);
  const requestUrl = new URL(
    input instanceof Request ? input.url : input.toString(),
    baseUrl,
  );
  const basePath = baseUrl.pathname.replace(/\/+$/, "");
  if (
    requestUrl.origin !== baseUrl.origin ||
    (basePath && requestUrl.pathname !== basePath && !requestUrl.pathname.startsWith(`${basePath}/`))
  ) {
    throw new Error("Solicitação bloqueada: a URL não pertence ao backend configurado.");
  }

  const user: User | null = getFirebaseAuth().currentUser;
  if (!user) {
    throw new Error("Entre com sua conta para acessar a plataforma.");
  }
  const token = await user.getIdToken();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  return fetch(requestUrl, { ...init, headers });
}
