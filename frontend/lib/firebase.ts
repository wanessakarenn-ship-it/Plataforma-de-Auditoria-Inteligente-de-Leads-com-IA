import { getApp, getApps, initializeApp } from "firebase/app";
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

export type AppRole = "admin" | "auditor" | "gestor";

export function isFirebaseConfigured() {
  return Object.values(config).every(Boolean);
}

export function getFirebaseAuth(): Auth {
  if (!isFirebaseConfigured()) {
    throw new Error("Firebase web app configuration is missing.");
  }
  const app = getApps().some((item) => item.name === "bc-lead-intelligence")
    ? getApp("bc-lead-intelligence")
    : initializeApp(config, "bc-lead-intelligence");
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
  const user: User | null = getFirebaseAuth().currentUser;
  if (!user) {
    throw new Error("Entre com sua conta para acessar a plataforma.");
  }
  const token = await user.getIdToken();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  return fetch(input, { ...init, headers });
}
