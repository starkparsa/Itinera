import { signIn } from "@/auth";

export default function LoginPage() {
  return (
    <div className="login-page">
      <h1>🧭 AI Travel Planner</h1>
      <p>Sign in to plan trips and save your chat history.</p>
      <form
        action={async () => {
          "use server";
          await signIn("google", { redirectTo: "/" });
        }}
      >
        <button type="submit" className="google-signin-button">
          Continue with Google
        </button>
      </form>
    </div>
  );
}
