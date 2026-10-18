import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const upstreamBase = (process.env.FORGE_API_UPSTREAM ?? "http://127.0.0.1:8000").replace(/\/$/, "");
const apiKey = process.env.FORGE_API_KEY ?? "";

function targetUrl(request: NextRequest, path: string[]): string {
  const suffix = path.map(encodeURIComponent).join("/");
  const search = request.nextUrl.search;
  return `${upstreamBase}/${suffix}${search}`;
}

function forwardHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const accept = request.headers.get("accept");
  if (accept) headers.set("accept", accept);
  // Prefer the browser session JWT; fall back to server-side service key.
  const incoming = request.headers.get("authorization");
  if (incoming) headers.set("authorization", incoming);
  else if (apiKey) headers.set("authorization", `Bearer ${apiKey}`);
  return headers;
}

async function proxy(request: NextRequest, path: string[]): Promise<Response> {
  const url = targetUrl(request, path);
  const method = request.method.toUpperCase();
  const init: RequestInit = {
    method,
    headers: forwardHeaders(request),
    cache: "no-store",
  };

  if (method !== "GET" && method !== "HEAD") {
    const body = await request.arrayBuffer();
    if (body.byteLength > 0) init.body = body;
  }

  let upstream: Response;
  try {
    upstream = await fetch(url, init);
  } catch {
    return NextResponse.json({ detail: "Upstream API unreachable" }, { status: 502 });
  }

  const responseHeaders = new Headers();
  const passThrough = ["content-type", "cache-control"];
  for (const name of passThrough) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }

  // SSE and other streams: pipe the body through without buffering.
  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

type RouteContext = { params: Promise<{ path: string[] }> };

async function handle(request: NextRequest, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  if (!path?.length) {
    return NextResponse.json({ detail: "Missing upstream path" }, { status: 400 });
  }
  return proxy(request, path);
}

export const GET = handle;
export const POST = handle;
export const PATCH = handle;
export const PUT = handle;
export const DELETE = handle;
export const OPTIONS = handle;
