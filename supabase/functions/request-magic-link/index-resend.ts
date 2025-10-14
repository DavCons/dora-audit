import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
const SUPABASE_URL = Deno.env.get("SUPABASE_URL");
const SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
const APP_BASE_URL = Deno.env.get("APP_BASE_URL") || "http://localhost:8501";
serve(async (req)=>{
  if (req.method !== "POST") return new Response("Method not allowed", {
    status: 405
  });
  const auth = req.headers.get('authorization') || '';
  const expected = Deno.env.get('EDGE_FUNCTION_TOKEN') || '';
  const provided = auth.startsWith('Bearer ') ? auth.slice(7) : '';
  console.log(auth);
  console.log(provided);
  console.log(expected);
  if (!expected || provided !== expected) return new Response('Unauthorized', {
    status: 401
  });
  try {
    const { email, redirect_to } = await req.json();
    if (!email) return new Response("Email required", {
      status: 400
    });
    // Upsert whitelist
    const up = await fetch(`${SUPABASE_URL}/rest/v1/allowed_emails`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "apikey": SERVICE_ROLE_KEY,
        "Authorization": `Bearer ${SERVICE_ROLE_KEY}`,
        "Prefer": "resolution=merge-duplicates"
      },
      body: JSON.stringify([
        {
          email,
          source: "checkout"
        }
      ])
    });
    if (!up.ok) return new Response("Upsert failed: " + await up.text(), {
      status: 500
    });
    // Send magic link via admin API
    const gen = await fetch(`${SUPABASE_URL}/auth/v1/admin/generate_link`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "apikey": SERVICE_ROLE_KEY,
        "Authorization": `Bearer ${SERVICE_ROLE_KEY}`
      },
      body: JSON.stringify({
        type: "magiclink",
        email,
        options: {
          email_redirect_to: redirect_to || APP_BASE_URL
        }
      })
    });
    if (!gen.ok) return new Response("Generate link failed: " + await gen.text(), {
      status: 500
    });
    return new Response(JSON.stringify({
      ok: true
    }), {
      status: 200
    });
  } catch (e) {
    return new Response("Error: " + (e?.message || String(e)), {
      status: 500
    });
  }
});
