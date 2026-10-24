import crypto from "node:crypto";

export const BACKEND_URL = process.env.BIDS_API_URL || "http://127.0.0.1:8000";

const INTERNAL_SECRET =
  process.env.BIDS_INTERNAL_SECRET || "dev-only-bids-internal-signing-key-change-me";

/**
 * Sign the owner + timestamp exactly like backend/security.py does. These
 * headers live for one request and are only ever produced server-side.
 */
export function signedHeaders(ownerEmail: string): Record<string, string> {
  const owner = ownerEmail.trim().toLowerCase();
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const signature = crypto
    .createHmac("sha256", INTERNAL_SECRET)
    .update(`${owner}\n${timestamp}`)
    .digest("hex");

  return {
    "x-bids-user": owner,
    "x-bids-timestamp": timestamp,
    "x-bids-signature": signature,
  };
}
