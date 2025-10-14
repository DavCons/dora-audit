import { createClient } from "npm:@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const EDGE_FUNCTION_TOKEN = Deno.env.get("EDGE_FUNCTION_TOKEN")!;
const REDIRECT_BASE_URL = Deno.env.get("REDIRECT_BASE_URL") ?? "";

Deno.serve(async (req) => {
  if (req.method !== "POST") {
    return new Response("Method Not Allowed", { status: 405 });
  }

  const auth = req.headers.get("authorization") ?? "";
  const bare = auth.replace(/^Bearer\s+/i, "").trim();
  if (bare !== EDGE_FUNCTION_TOKEN) {
    return new Response("Unauthorized", { status: 401 });
  }

  const { email, redirect_to } = await req.json().catch(() => ({}));
  if (!email) return new Response("Missing email", { status: 400 });

  const supa = createClient(SUPABASE_URL, SERVICE_ROLE_KEY);

  // 1️⃣ Sprawdź whitelistę
  const { data: allowed } = await supa
    .from("allowed_emails")
    .select("email")
    .eq("email", email)
    .maybeSingle();

  if (!allowed) {
    return new Response(
      JSON.stringify({ error: "Email not whitelisted" }),
      { status: 403 }
    );
  }

  // 2️⃣ Wyślij magic link
  const redirectUrl = redirect_to ?? `${REDIRECT_BASE_URL}/#magiclink`;
  const { data, error } = await supa.auth.signInWithOtp({
    email,
    options: { emailRedirectTo: redirectUrl },
  });

  if (error) {
    console.error(error);
    return new Response(JSON.stringify({ error: error.message }), { status: 400 });
  }

  return new Response(JSON.stringify({ success: true, data }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
});
