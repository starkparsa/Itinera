import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import LoginCard from "./LoginCard";
import { ToastProvider } from "@/components/ui/toast";

function renderCard(onGoogleSignIn = vi.fn().mockResolvedValue(undefined)) {
  render(
    <ToastProvider>
      <LoginCard onGoogleSignIn={onGoogleSignIn} />
    </ToastProvider>
  );
  return { onGoogleSignIn };
}

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

  it("Facebook has no real backend yet -- it toasts instead of pretending to sign in", async () => {
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /Continue with Facebook/ }));
    await waitFor(() => expect(screen.getByText("Facebook sign-in isn't available yet")).toBeInTheDocument());
  });

  it("Continue with email reveals the email/password form", () => {
    renderCard();
    expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Continue with email/ }));
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });

  it("blocks submit on an invalid email, without ever pretending to authenticate", () => {
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /Continue with email/ }));
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "not-an-email" } });
    fireEvent.click(screen.getByRole("button", { name: "Log in" }));
    expect(screen.getByText("Enter a valid email address.")).toBeInTheDocument();
  });

  it("a valid email submit still just toasts -- no fake success or fake wrong-password error", async () => {
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /Continue with email/ }));
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "jordan@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Log in" }));
    await waitFor(() => expect(screen.getByText("Email sign-in isn't available yet")).toBeInTheDocument());
  });

  it("password visibility toggle switches the input type", () => {
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /Continue with email/ }));
    const password = screen.getByLabelText("Password") as HTMLInputElement;
    expect(password.type).toBe("password");
    fireEvent.click(screen.getByLabelText("Show password"));
    expect(password.type).toBe("text");
  });

  it("Forgot password toasts the same honest message, not a dead link", async () => {
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /Continue with email/ }));
    fireEvent.click(screen.getByRole("button", { name: "Forgot password?" }));
    await waitFor(() => expect(screen.getByText("Password reset isn't available yet")).toBeInTheDocument());
  });
});
