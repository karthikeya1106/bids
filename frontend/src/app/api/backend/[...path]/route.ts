import { NextRequest, NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { BACKEND_URL, signedHeaders } from "@/lib/backend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MUTATING = new Set(["POST", "PUT", "PATCH", "DELETE"]);

async function forward(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const session = await getServerSession(authOptions);
  const email = session?.user?.email?.trim().toLowerCase();

  if (!email) {
    return NextResponse.json({ detail: "Sign in to access this resource." }, { status: 401 });
  }

  // Block cross-site writes that reuse the session cookie.
  if (MUTATING.has(request.method)) {
    const origin = request.headers.get("origin");
    if (origin && origin !== request.nextUrl.origin) {
      return NextResponse.json({ detail: "Cross-origin request rejected." }, { status: 403 });
    }
  }

  const { path } = await context.params;
  if (!path?.length) {
    return NextResponse.json({ detail: "Missing API path." }, { status: 400 });
  }

  // Client calls already carry the /api prefix (e.g. /api/backend/api/dashboard).
  const target = `${BACKEND_URL}/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`;

  const headers: Record<string, string> = {
    ...signedHeaders(email),
    accept: request.headers.get("accept") || "application/json",
  };
  const contentType = request.headers.get("content-type");
  if (contentType) headers["content-type"] = contentType;

  let body: ArrayBuffer | undefined;
  if (!["GET", "HEAD"].includes(request.method)) {
    body = await request.arrayBuffer();
  }

  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual",
    });

    const payload = await upstream.arrayBuffer();
    return new NextResponse(payload, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") || "application/json",
        "cache-control": "no-store, private",
      },
    });
  } catch {
    return NextResponse.json(
      { detail: "The BIDS API is not reachable. Start the backend and try again." },
      { status: 502 },
    );
  }
}

export {
  forward as GET,
  forward as POST,
  forward as PUT,
  forward as PATCH,
  forward as DELETE,
};
