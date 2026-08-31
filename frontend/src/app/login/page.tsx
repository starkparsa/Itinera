import { signIn } from "@/auth";
import { Button } from "@/components/ui/button";

export default function LoginPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 px-8 text-center">
      <div className="flex flex-col items-center gap-2">
        <span className="text-4xl" aria-hidden>
          🧭
        </span>
        <h1 className="text-2xl font-semibold tracking-tight">Itinera</h1>
        <p className="text-muted-foreground">Sign in to plan trips and save your chat history.</p>
      </div>
      <form
        action={async () => {
          "use server";
          await signIn("google", { redirectTo: "/" });
        }}
      >
        <Button type="submit" size="lg" className="px-6">
          Continue with Google
        </Button>
      </form>
    </div>
  );
}
