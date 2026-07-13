/**
 * Simulated email transport. This is the ONLY file a real integration
 * (SMTP, Microsoft Graph, SendGrid, Outlook) needs to replace — it must
 * keep the same `simulateSend({to, cc, subject, body}) -> Promise<record>`
 * shape so `emailService.js` and everything above it never changes.
 */
export async function simulateSend({ to, cc = [], subject, body }) {
  // Artificial latency so the UI's "Sending…" state reads as real network I/O.
  await new Promise((resolve) => setTimeout(resolve, 250));

  return {
    id: `email-${Date.now()}-${Math.round(Math.random() * 1e6)}`,
    to,
    cc,
    subject,
    body,
    sentAt: new Date().toISOString(),
    status: "Sent",
  };
}
