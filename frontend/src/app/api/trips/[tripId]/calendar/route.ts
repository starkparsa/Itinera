// Proxies GET /trips/{id}/calendar.ics from the backend so the browser can
// download it with a normal <a href> -- avoids a Server Action's
// JSON-serializable-only return shape for what's actually a binary file
// download. The backend already does all the real work (backend/app/
// calendar_export.py); this route does nothing but forward the response.
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { backendAuthHeader } from "@/lib/authHeader";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function GET(_request: NextRequest, { params }: { params: Promise<{ tripId: string }> }) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const { tripId } = await params;

  const backendRes = await fetch(`${BACKEND_URL}/trips/${tripId}/calendar.ics`, {
    cache: "no-store",
    headers: await backendAuthHeader(),
  });

  if (!backendRes.ok) {
    const detail = await backendRes.json().catch(() => ({}));
    return NextResponse.json({ detail: detail.detail ?? "Export failed" }, { status: backendRes.status });
  }

  const bytes = await backendRes.arrayBuffer();
  return new NextResponse(bytes, {
    status: 200,
    headers: {
      "Content-Type": "text/calendar",
      "Content-Disposition": backendRes.headers.get("content-disposition") ?? "attachment; filename=trip.ics",
    },
  });
}
