import { createClient } from "npm:@supabase/supabase-js@2";

const SUPABASE_URL    = Deno.env.get('SUPABASE_URL')!;
const SERVICE_KEY     = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;
const EDGE_TOKEN      = Deno.env.get('EDGE_FUNCTION_TOKEN') ?? "";
const DEFAULT_REDIRECT= Deno.env.get('REDIRECT_BASE_URL') ?? "";

const RESEND_API_KEY  = Deno.env.get('RESEND_API_KEY')!;
const RESEND_FROM     = Deno.env.get('RESEND_FROM')!;
const RESEND_REPLY_TO = Deno.env.get('RESEND_REPLY_TO') ?? "";
const MAIL_SUBJECT    = Deno.env.get('RESEND_SUBJECT') ?? "Your magic link to DORA Audit";

const emailRx = /^[^@\s]+@[^@\s]+\.[^@\s]+$/i;
const cors = (req: Request) => ({
  'Access-Control-Allow-Origin': req.headers.get('origin') ?? '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'content-type, authorization',
  'Access-Control-Allow-Credentials': 'true',
  'Content-Type': 'application/json',
});

const html = (link: string) => `
  <div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#0f172a">
    <h2>DORA Audit — sign in</h2>
    <p>Click to sign in securely:</p>
    <p style="margin:24px 0">
      <a href="${link}" style="background:#7c3aed;color:#fff;padding:12px 16px;border-radius:10px;text-decoration:none;display:inline-block">
        Open DORA Audit
      </a>
    </p>
    <p style="word-break:break-all;"><a href="${link}">${link}</a></p>
  </div>`.trim();
const text = (link: string) => `Sign in to DORA Audit\n${link}\n`;

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors(req) });
  if (req.method !== 'POST')   return new Response('Method Not Allowed', { status: 405, headers: cors(req) });

  const auth = req.headers.get('authorization') ?? "";
  const bare = EDGE_TOKEN.replace(/^Bearer\s+/i, "");
  if (EDGE_TOKEN && auth !== `Bearer ${bare}` && auth !== bare) {
    return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: cors(req) });
  }

  let body: any = {};
  try { body = await req.json(); } catch {}
  const email = (body?.email ?? "").trim();
  const redirect_to = (body?.redirect_to ?? DEFAULT_REDIRECT)?.toString().trim();

  if (!emailRx.test(email)) return new Response(JSON.stringify({ error: 'Invalid email' }), { status: 400, headers: cors(req) });

  const supa = createClient(SUPABASE_URL, SERVICE_KEY, { auth: { autoRefreshToken: false, persistSession: false } });

  // weryfikacja whitelisty
  const { data: allowed, error: allowErr } = await supa
    .from('allowed_emails')
    .select('email')
    .eq('email', email)
    .maybeSingle();

  if (allowErr) return new Response(JSON.stringify({ error: `DB read: ${allowErr.message}` }), { status: 500, headers: cors(req) });
  if (!allowed)  return new Response(JSON.stringify({ error: 'Email not allowed' }), { status: 403, headers: cors(req) });

  // generuj magic link
  const { data, error } = await supa.auth.admin.generateLink({
    type: 'magiclink',
    email,
    options: { redirectTo: redirect_to || undefined },
  });
  if (error) return new Response(JSON.stringify({ error: `generateLink: ${error.message}` }), { status: 500, headers: cors(req) });

  const link = data?.properties?.action_link;
  if (!link) return new Response(JSON.stringify({ error: 'No action_link generated' }), { status: 500, headers: cors(req) });

  // wyślij przez Resend
  const payload: any = { from: RESEND_FROM, to: [email], subject: MAIL_SUBJECT, html: html(link), text: text(link) };
  if (RESEND_REPLY_TO) payload.reply_to = RESEND_REPLY_TO;

  const r = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${RESEND_API_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!r.ok) {
    const details = await r.text().catch(() => '');
    return new Response(JSON.stringify({ error: `Resend ${r.status}`, details }), { status: 502, headers: cors(req) });
  }

  return new Response(JSON.stringify({ ok: true }), { status: 200, headers: cors(req) });
});
