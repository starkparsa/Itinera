import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import DeleteAccountButton from "./DeleteAccountButton";
import { ToastProvider } from "@/components/ui/toast";
import { deleteAccount } from "@/lib/backend";
import { signOutAction } from "@/lib/authActions";

vi.mock("@/lib/backend", () => ({
  deleteAccount: vi.fn(),
}));

vi.mock("@/lib/authActions", () => ({
  signOutAction: vi.fn(),
}));

function renderButton() {
  return render(
    <ToastProvider>
      <DeleteAccountButton />
    </ToastProvider>
  );
}

beforeEach(() => {
  vi.mocked(deleteAccount).mockReset();
  vi.mocked(signOutAction).mockReset();
});

function openDialogAndConfirm() {
  fireEvent.click(screen.getByRole("button", { name: "Delete account" }));
  // The dialog's own confirm button shares the trigger's accessible name --
  // scope to the dialog to click the right one.
  const dialog = screen.getByRole("alertdialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Delete account" }));
}

describe("DeleteAccountButton", () => {
  it("shows a confirmation dialog before deleting anything", () => {
    vi.mocked(deleteAccount).mockResolvedValue({ ok: true });
    renderButton();

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete account" }));

    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(deleteAccount).not.toHaveBeenCalled();
  });

  it("deletes the account and signs out on confirm", async () => {
    vi.mocked(deleteAccount).mockResolvedValue({ ok: true });
    renderButton();

    openDialogAndConfirm();

    await waitFor(() => expect(deleteAccount).toHaveBeenCalledOnce());
    await waitFor(() => expect(signOutAction).toHaveBeenCalledOnce());
  });

  it("surfaces the real error and never signs out when deletion fails", async () => {
    vi.mocked(deleteAccount).mockResolvedValue({ ok: false, error: "Backend returned 500" });
    renderButton();

    openDialogAndConfirm();

    await waitFor(() => expect(screen.getByText("Couldn't delete your account")).toBeInTheDocument());
    expect(screen.getByText("Backend returned 500")).toBeInTheDocument();
    expect(signOutAction).not.toHaveBeenCalled();
  });

  it("cancel closes the dialog without calling deleteAccount", () => {
    renderButton();
    fireEvent.click(screen.getByRole("button", { name: "Delete account" }));

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(deleteAccount).not.toHaveBeenCalled();
  });
});
