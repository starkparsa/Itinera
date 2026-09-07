import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ToastProvider, useToast } from "./toast";

function Trigger({ variant }: { variant?: "default" | "destructive" }) {
  const { toast } = useToast();
  return (
    <button onClick={() => toast({ title: "Trip created", description: "Your itinerary is ready.", variant })}>
      Fire
    </button>
  );
}

describe("ToastProvider", () => {
  it("shows a toast with title and description on demand", () => {
    render(
      <ToastProvider>
        <Trigger />
      </ToastProvider>
    );
    expect(screen.queryByText("Trip created")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Fire"));
    expect(screen.getByText("Trip created")).toBeInTheDocument();
    expect(screen.getByText("Your itinerary is ready.")).toBeInTheDocument();
  });

  it("is announced via role=status so screen readers pick it up without interrupting", () => {
    render(
      <ToastProvider>
        <Trigger />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText("Fire"));
    expect(screen.getByRole("status")).toHaveTextContent("Trip created");
  });

  it("can be dismissed manually", () => {
    render(
      <ToastProvider>
        <Trigger />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText("Fire"));
    fireEvent.click(screen.getByLabelText("Dismiss notification"));
    expect(screen.queryByText("Trip created")).not.toBeInTheDocument();
  });

  it("useToast throws outside of a ToastProvider", () => {
    function Broken() {
      useToast();
      return null;
    }
    // Suppress the expected React error-boundary console noise for this one assertion.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Broken />)).toThrow("useToast must be used within <ToastProvider>");
    spy.mockRestore();
  });
});
