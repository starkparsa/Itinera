import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import LoginCard from "./LoginCard";
import { ToastProvider } from "@/components/ui/toast";
import { emailLogin, emailSignUp } from "@/app/login/actions";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("@/app/login/actions", () => ({
  emailLogin: vi.fn(),
  emailSignUp: vi.fn(),
}));

function renderCard(
  onGoogleSignIn = vi.fn().mockResolvedValue(undefined),
  onFacebookSignIn = vi.fn().mockResolvedValue(undefined)
) {
  render(
    <ToastProvider>
      <LoginCard onGoogleSignIn={onGoogleSignIn} onFacebookSignIn={onFacebookSignIn} />
    </ToastProvider>
  );
  return { onGoogleSignIn, onFacebookSignIn };
}

function openEmailForm() {
  fireEvent.click(screen.getByRole("button", { name: /(Continue with|Sign up with) email/ }));
}

beforeEach(() => {
  pushMock.mockReset();
  vi.mocked(emailLogin).mockReset();
  vi.mocked(emailSignUp).mockReset();
  vi.mocked(emailLogin).mockResolvedValue({ ok: true });
  vi.mocked(emailSignUp).mockResolvedValue({ ok: true });
});

describe("LoginCard", () => {
  it("opens on login copy by default", () => {
    renderCard();
    expect(screen.getByText("Welcome back")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Log in" })).toBeChecked();
  });

  it("switching to Sign up swaps all the mode-dependent copy", () => {
    renderCard();
    fireEvent.click(screen.getByLabelText("Sign up"));
    expect(screen.getByText("Join Itinera")).toBeInTheDocument();
    expect(screen.getByText(/New accounts start at Level 1/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign up with email" })).toBeInTheDocument();
  });

  it("the switcher line at the bottom also flips mode", () => {
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: "Create an account" }));
    expect(screen.getByText("Join Itinera")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Log in" }));
    expect(screen.getByText("Welcome back")).toBeInTheDocument();
  });

  it("Continue with Google calls the real sign-in action", async () => {
    const { onGoogleSignIn } = renderCard();
    fireEvent.click(screen.getByRole("button", { name: /Continue with Google/ }));
    await waitFor(() => expect(onGoogleSignIn).toHaveBeenCalledTimes(1));
  });

  it("Continue with Facebook calls the real sign-in action", async () => {
    const { onFacebookSignIn } = renderCard();
    fireEvent.click(screen.getByRole("button", { name: /Continue with Facebook/ }));
    await waitFor(() => expect(onFacebookSignIn).toHaveBeenCalledTimes(1));
  });

  it("Continue with email reveals the email/password form", () => {
    renderCard();
    expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();
    openEmailForm();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });

  it("blocks submit on an invalid email, without calling the real login action", () => {
    renderCard();
    openEmailForm();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "not-an-email" } });
    fireEvent.click(screen.getByRole("button", { name: "Log in" }));
    expect(screen.getByText("Enter a valid email address.")).toBeInTheDocument();
    expect(emailLogin).not.toHaveBeenCalled();
  });

  it("a correct login calls the real emailLogin action and navigates home", async () => {
    renderCard();
    openEmailForm();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "jordan@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "Correct-Horse9" } });
    fireEvent.click(screen.getByRole("button", { name: "Log in" }));
    await waitFor(() => expect(emailLogin).toHaveBeenCalledWith("jordan@example.com", "Correct-Horse9"));
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/"));
  });

  it("a failed login shows the backend's real error message, not a fake one", async () => {
    vi.mocked(emailLogin).mockResolvedValue({ ok: false, error: "Incorrect email or password." });
    renderCard();
    openEmailForm();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "jordan@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "Wrong-Password1" } });
    fireEvent.click(screen.getByRole("button", { name: "Log in" }));
    await waitFor(() => expect(screen.getByText("Incorrect email or password.")).toBeInTheDocument());
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("signup blocks a weak password client-side, without calling the real signup action", () => {
    renderCard();
    fireEvent.click(screen.getByLabelText("Sign up"));
    openEmailForm();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "jordan@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "weak" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(screen.getByText(/Password must be at least 8 characters/)).toBeInTheDocument();
    expect(emailSignUp).not.toHaveBeenCalled();
  });

  it("a valid signup calls the real emailSignUp action and navigates home", async () => {
    renderCard();
    fireEvent.click(screen.getByLabelText("Sign up"));
    openEmailForm();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "jordan@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "Correct-Horse9" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(emailSignUp).toHaveBeenCalledWith("jordan@example.com", "Correct-Horse9"));
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/"));
  });

  it("a duplicate-email signup shows the backend's real error, not a fake success", async () => {
    vi.mocked(emailSignUp).mockResolvedValue({ ok: false, error: "An account with this email already exists." });
    renderCard();
    fireEvent.click(screen.getByLabelText("Sign up"));
    openEmailForm();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "jordan@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "Correct-Horse9" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(screen.getByText("An account with this email already exists.")).toBeInTheDocument());
  });

  it("password visibility toggle switches the input type", () => {
    renderCard();
    openEmailForm();
    const password = screen.getByLabelText("Password") as HTMLInputElement;
    expect(password.type).toBe("password");
    fireEvent.click(screen.getByLabelText("Show password"));
    expect(password.type).toBe("text");
  });

  it("Forgot password toasts the same honest message, not a dead link", async () => {
    renderCard();
    openEmailForm();
    fireEvent.click(screen.getByRole("button", { name: "Forgot password?" }));
    await waitFor(() => expect(screen.getByText("Password reset isn't available yet")).toBeInTheDocument());
  });
});
