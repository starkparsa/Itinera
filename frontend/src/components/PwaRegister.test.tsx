import { afterEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import { PwaRegister } from "./PwaRegister";

function withServiceWorker(register: ReturnType<typeof vi.fn>) {
  Object.defineProperty(navigator, "serviceWorker", {
    value: { register },
    configurable: true,
  });
}

afterEach(() => {
  // @ts-expect-error -- test-only cleanup of a property this suite defines
  delete navigator.serviceWorker;
  vi.restoreAllMocks();
});

describe("PwaRegister", () => {
  it("registers public/sw.js once the page has already finished loading", () => {
    const register = vi.fn().mockResolvedValue(undefined);
    withServiceWorker(register);
    Object.defineProperty(document, "readyState", { value: "complete", configurable: true });

    render(<PwaRegister />);

    expect(register).toHaveBeenCalledWith("/sw.js");
  });

  it("waits for the load event before registering when the page is still loading", () => {
    const register = vi.fn().mockResolvedValue(undefined);
    withServiceWorker(register);
    Object.defineProperty(document, "readyState", { value: "loading", configurable: true });

    render(<PwaRegister />);
    expect(register).not.toHaveBeenCalled();

    window.dispatchEvent(new Event("load"));
    expect(register).toHaveBeenCalledWith("/sw.js");
  });

  it("renders nothing and never throws when the browser has no serviceWorker support", () => {
    // @ts-expect-error -- deliberately absent, matching an unsupported browser
    delete navigator.serviceWorker;

    const { container } = render(<PwaRegister />);

    expect(container).toBeEmptyDOMElement();
  });

  it("swallows a registration failure instead of surfacing an error", () => {
    const register = vi.fn().mockRejectedValue(new Error("registration blocked"));
    withServiceWorker(register);
    Object.defineProperty(document, "readyState", { value: "complete", configurable: true });

    expect(() => render(<PwaRegister />)).not.toThrow();
  });
});
