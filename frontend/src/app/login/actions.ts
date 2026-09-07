"use server";

import { signIn } from "@/auth";

// Split out of page.tsx (a server component) so LoginCard (a client
// component, needed for the tab/toggle/toast interactivity below) can
// still trigger the real OAuth flow -- Server Actions defined in their
// own "use server" file can be imported and called directly from client
// code, same RPC mechanism as a <form action={...}>.
export async function googleSignIn() {
  await signIn("google", { redirectTo: "/" });
}
