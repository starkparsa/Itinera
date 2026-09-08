"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff, Mail, Trophy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { ChipGroup, ChipOption } from "@/components/ui/toggle-chip";
import { useToast } from "@/components/ui/toast";
import { emailLogin, emailSignUp } from "@/app/login/actions";

// Same field styling convention OnboardingFlow.tsx already established
// (fieldClass) -- one shared class for every text-ish input, including
// [color-scheme:light]'s dark-mode-popup fix, so a future select/date
// input added here wouldn't need rediscovering that bug.
const fieldClass =
  "w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 [color-scheme:light]";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
// Client-side courtesy only -- mirrors schemas.py's RegisterRequest
// validator exactly, but that backend check is the authoritative one.
const MIN_PASSWORD_LENGTH = 8;

type AuthMode = "login" | "signup";

function passwordStrengthError(password: string): string | null {
  if (password.length < MIN_PASSWORD_LENGTH) return `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
  if (!/[A-Z]/.test(password)) return "Password must include an uppercase letter.";
  if (!/[0-9]/.test(password)) return "Password must include a number.";
  if (!/[^A-Za-z0-9]/.test(password)) return "Password must include a special character.";
  return null;
}

export default function LoginCard({
  onGoogleSignIn,
  onFacebookSignIn,
}: {
  onGoogleSignIn: () => Promise<void>;
  onFacebookSignIn: () => Promise<void>;
}) {
  const { toast } = useToast();
  const router = useRouter();
  const [mode, setMode] = useState<AuthMode>("login");
  const [emailOpen, setEmailOpen] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [googlePending, setGooglePending] = useState(false);
  const [facebookPending, setFacebookPending] = useState(false);
  const [emailPending, setEmailPending] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [emailError, setEmailError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  // Form-level, not field-level -- "incorrect email or password" (login)
  // or "an account with this email already exists" (signup) isn't about
  // one specific field, matching OnboardingFlow.tsx's own Alert usage for
  // a save failure.
  const [formError, setFormError] = useState<string | null>(null);

  // Password reset has no real backend yet -- Google, Facebook, and
  // email/password are this app's three actually-wired methods. It shows
  // this same honest "not live yet" toast rather than a fabricated
  // success, so nothing here silently pretends to work.
  const notWired = (label: string) => () =>
    toast({ title: `${label} isn't available yet`, description: "Use Google to continue for now." });

  async function handleGoogle() {
    setGooglePending(true);
    try {
      await onGoogleSignIn();
    } finally {
      // Only reached if the redirect the action performs didn't navigate
      // away (e.g. it threw) -- a successful sign-in never returns here.
      setGooglePending(false);
    }
  }

  async function handleFacebook() {
    setFacebookPending(true);
    try {
      await onFacebookSignIn();
    } finally {
      setFacebookPending(false);
    }
  }

  // onClick, not a <form onSubmit> -- matches OnboardingFlow.tsx's own
  // convention (every save/continue action there is wired via onClick on
  // a Button, never native form submission), since Button wraps
  // @base-ui/react's primitive rather than rendering a plain <button>,
  // and relying on it to forward type="submit" through to a real submit
  // control is exactly the kind of implicit behavior that convention
  // avoids.
  async function handleEmailSubmit() {
    setFormError(null);
    if (!EMAIL_RE.test(email)) {
      setEmailError("Enter a valid email address.");
      return;
    }
    setEmailError(null);

    if (mode === "signup") {
      const strengthError = passwordStrengthError(password);
      if (strengthError) {
        setPasswordError(strengthError);
        return;
      }
    }
    setPasswordError(null);

    setEmailPending(true);
    const result = mode === "signup" ? await emailSignUp(email, password) : await emailLogin(email, password);
    setEmailPending(false);

    if (!result.ok) {
      setFormError(result.error ?? "Something went wrong. Try again.");
      return;
    }
    router.push("/");
  }

  const copy =
    mode === "signup"
      ? {
          title: "Join Itinera",
          sub: "Create an account to start planning and tracking your trips.",
          emailCta: "Sign up with email",
          submit: "Create account",
          gamify: "New accounts start at Level 1 -- your first badge unlocks after your first trip.",
          switcherLead: "Already have an account?",
          switcherAction: "Log in",
        }
      : {
          title: "Welcome back",
          sub: "Sign in to plan trips and save your chat history.",
          emailCta: "Continue with email",
          submit: "Log in",
          gamify: "Sign in to start earning passport stamps for every trip you plan.",
          switcherLead: "New here?",
          switcherAction: "Create an account",
        };

  return (
    // h-screen + overflow-y-auto (not min-h-screen + overflow-hidden): this
    // app's globals.css sets `overflow: hidden` on html/body so ChatApp's
    // own inner region is the only thing that scrolls -- that rule would
    // otherwise trap this page's content with no way to reach it once the
    // card (email form open, gamification hint, switcher line) grows
    // taller than a short viewport. Capping this div's own height to the
    // viewport and letting it scroll internally keeps the same
    // one-scroll-region-per-page contract the rest of the app already
    // follows, just owned by this page instead of ChatApp's.
    <div className="dusk-login-bg relative flex h-screen flex-col items-center overflow-y-auto px-4 py-10">
      <div className="dusk-login-stars pointer-events-none fixed inset-0" aria-hidden />
      <DuskSkyline />
      <div className="dusk-login-vignette pointer-events-none fixed inset-0" aria-hidden />

      {/* my-auto, not the parent's justify-center: centering via margin
          on this child (not justify-content on the scroll container)
          is what keeps the top of the card reachable by scrolling once
          it grows taller than the viewport -- justify-center on an
          overflowing flex container clips the start of the overflow
          instead of letting a scrollbar reach it. */}
      <div
        id="main-content"
        className="relative z-10 my-auto w-full max-w-[380px] rounded-2xl border border-border bg-card p-7 text-card-foreground shadow-[0_24px_48px_-16px_rgba(0,0,0,0.45)] sm:p-9"
      >
        <div className="mb-5 flex flex-col items-center gap-2 text-center">
          <img src="/logo-mark.png" alt="" aria-hidden className="h-10 w-10" />
          <h1 className="text-lg font-semibold tracking-tight">{copy.title}</h1>
          <p className="text-sm text-muted-foreground">{copy.sub}</p>
        </div>

        <ChipGroup legend="Log in or sign up">
          <div className="grid w-full grid-cols-2 gap-2 [&_label]:w-full [&_span]:flex [&_span]:w-full [&_span]:justify-center">
            <ChipOption type="radio" name="authmode" checked={mode === "login"} onChange={() => setMode("login")}>
              Log in
            </ChipOption>
            <ChipOption type="radio" name="authmode" checked={mode === "signup"} onChange={() => setMode("signup")}>
              Sign up
            </ChipOption>
          </div>
        </ChipGroup>

        <div className="mt-5 flex flex-col gap-2.5">
          <Button
            type="button"
            variant="outline"
            size="lg"
            className="h-11 w-full gap-2.5 text-sm"
            onClick={handleGoogle}
            disabled={googlePending}
          >
            <GoogleGlyph />
            {googlePending ? "Continuing..." : "Continue with Google"}
          </Button>
          <Button
            type="button"
            size="lg"
            className="h-11 w-full gap-2.5 bg-[#1877F2] text-sm text-white hover:bg-[#1877F2]/90"
            onClick={handleFacebook}
            disabled={facebookPending}
          >
            <FacebookGlyph />
            {facebookPending ? "Continuing..." : "Continue with Facebook"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="lg"
            className="h-11 w-full gap-2 text-sm text-muted-foreground"
            aria-expanded={emailOpen}
            onClick={() => setEmailOpen((o) => !o)}
          >
            <Mail className="size-4" />
            {copy.emailCta}
          </Button>
        </div>

        {emailOpen && (
          <div className="mt-4 flex flex-col gap-3">
            {formError && (
              <Alert variant="destructive">
                <AlertDescription>{formError}</AlertDescription>
              </Alert>
            )}

            {/* label wraps only the field name, not the hint/error text --
                a description span nested inside <label> becomes part of
                its accessible name (e.g. "Password" turns into
                "PasswordAt least 8 characters..."), which is wrong for
                assistive tech and broke a very literal getByLabelText
                match in tests. aria-describedby links the description
                without folding it into the name. */}
            <div className="flex flex-col gap-1.5">
              <label htmlFor="login-email" className="text-sm font-medium">
                Email
              </label>
              <input
                id="login-email"
                type="email"
                className={fieldClass}
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (emailError) setEmailError(null);
                }}
                placeholder="you@example.com"
                autoComplete="email"
                aria-describedby={emailError ? "login-email-error" : undefined}
              />
              {emailError && (
                <span id="login-email-error" className="text-xs font-normal text-destructive">
                  {emailError}
                </span>
              )}
            </div>

            <div className="flex flex-col gap-1.5">
              <label htmlFor="login-password" className="text-sm font-medium">
                Password
              </label>
              <span className="relative">
                <input
                  id="login-password"
                  type={showPassword ? "text" : "password"}
                  className={`${fieldClass} pr-9`}
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value);
                    if (passwordError) setPasswordError(null);
                  }}
                  autoComplete={mode === "signup" ? "new-password" : "current-password"}
                  aria-describedby="login-password-hint"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleEmailSubmit();
                  }}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((s) => !s)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  className="absolute top-1/2 right-1.5 -translate-y-1/2 rounded-md p-1.5 text-muted-foreground hover:bg-muted"
                >
                  {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </span>
              {passwordError ? (
                <span id="login-password-hint" className="text-xs font-normal text-destructive">
                  {passwordError}
                </span>
              ) : mode === "signup" ? (
                <span id="login-password-hint" className="text-xs font-normal text-muted-foreground">
                  At least 8 characters, with an uppercase letter, a number, and a special character.
                </span>
              ) : (
                <span id="login-password-hint" className="sr-only" />
              )}
            </div>

            {mode === "login" ? (
              <div className="flex items-center justify-between text-xs">
                <label className="flex items-center gap-1.5 text-muted-foreground">
                  <input type="checkbox" defaultChecked className="accent-primary" />
                  Remember me
                </label>
                <button type="button" onClick={notWired("Password reset")} className="font-medium text-primary hover:underline">
                  Forgot password?
                </button>
              </div>
            ) : null}

            <Button type="button" size="lg" className="h-11 w-full text-sm" onClick={handleEmailSubmit} disabled={emailPending}>
              {emailPending ? "Please wait..." : copy.submit}
            </Button>
          </div>
        )}

        <div className="mt-4 flex items-center gap-2 rounded-lg border border-border bg-muted/60 px-3 py-2 text-xs text-muted-foreground">
          <Trophy className="size-4 shrink-0 text-primary" aria-hidden />
          <span>{copy.gamify}</span>
        </div>

        <p className="mt-4 text-center text-sm text-muted-foreground">
          {copy.switcherLead}{" "}
          <button
            type="button"
            onClick={() => setMode(mode === "login" ? "signup" : "login")}
            className="font-medium text-primary hover:underline"
          >
            {copy.switcherAction}
          </button>
        </p>
      </div>
    </div>
  );
}

function GoogleGlyph() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.9c1.7-1.57 2.7-3.87 2.7-6.62Z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.9-2.26c-.8.54-1.84.86-3.06.86-2.35 0-4.34-1.59-5.05-3.72H.98v2.33A9 9 0 0 0 9 18Z" />
      <path fill="#FBBC05" d="M3.95 10.7A5.4 5.4 0 0 1 3.67 9c0-.59.1-1.17.28-1.7V4.97H.98A9 9 0 0 0 0 9c0 1.45.35 2.83.98 4.03l2.97-2.33Z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.9 11.42 0 9 0A9 9 0 0 0 .98 4.97L3.95 7.3C4.66 5.17 6.65 3.58 9 3.58Z" />
    </svg>
  );
}

function FacebookGlyph() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M13.5 21v-7.5h2.5l.5-3h-3V8.5c0-.87.24-1.46 1.5-1.46H16.5V4.36c-.26-.03-1.15-.11-2.19-.11-2.17 0-3.66 1.32-3.66 3.75V10.5H8v3h2.65V21h2.85Z" />
    </svg>
  );
}

// Flat building silhouettes, same shapes as the approved mockup -- pure
// inline SVG, no image asset to host/license.
function DuskSkyline() {
  return (
    <svg
      className="pointer-events-none absolute inset-x-0 bottom-0 w-full"
      viewBox="0 0 400 92"
      preserveAspectRatio="none"
      aria-hidden
      style={{ height: "18vh", minHeight: 90, maxHeight: 160 }}
    >
      <g fill="oklch(0.16 0.03 280)">
        <rect x="0" y="46" width="26" height="46" />
        <rect x="24" y="30" width="18" height="62" />
        <rect x="44" y="52" width="22" height="40" />
        <rect x="68" y="20" width="20" height="72" />
        <rect x="90" y="40" width="16" height="52" />
        <rect x="108" y="34" width="24" height="58" />
        <rect x="134" y="10" width="22" height="82" />
        <rect x="158" y="44" width="18" height="48" />
        <rect x="178" y="26" width="26" height="66" />
        <rect x="206" y="38" width="16" height="54" />
        <rect x="224" y="16" width="22" height="76" />
        <rect x="248" y="48" width="20" height="44" />
        <rect x="270" y="32" width="18" height="60" />
        <rect x="290" y="6" width="24" height="86" />
        <rect x="316" y="42" width="18" height="50" />
        <rect x="336" y="24" width="22" height="68" />
        <rect x="360" y="50" width="16" height="42" />
        <rect x="378" y="36" width="22" height="56" />
      </g>
      <g fill="oklch(0.78 0.13 70 / 85%)">
        <rect x="30" y="38" width="3" height="3" /><rect x="30" y="46" width="3" height="3" />
        <rect x="72" y="30" width="3" height="3" /><rect x="72" y="40" width="3" height="3" /><rect x="72" y="50" width="3" height="3" />
        <rect x="112" y="44" width="3" height="3" /><rect x="120" y="52" width="3" height="3" />
        <rect x="140" y="22" width="3" height="3" /><rect x="140" y="34" width="3" height="3" /><rect x="140" y="46" width="3" height="3" />
        <rect x="184" y="36" width="3" height="3" /><rect x="192" y="46" width="3" height="3" />
        <rect x="230" y="28" width="3" height="3" /><rect x="230" y="40" width="3" height="3" />
        <rect x="296" y="18" width="3" height="3" /><rect x="296" y="30" width="3" height="3" /><rect x="296" y="42" width="3" height="3" />
        <rect x="342" y="34" width="3" height="3" /><rect x="342" y="46" width="3" height="3" />
        <rect x="384" y="44" width="3" height="3" />
      </g>
    </svg>
  );
}
