/**
 * Client-Side URL and Metadata Sanitizer (M2-07, M2-17).
 * Recursively filters prohibited fields, redacts tokens, and cleans referrers.
 */

const SENSITIVE_QUERY_PARAMS = new Set([
  'token',
  'auth',
  'password',
  'key',
  'secret',
  'ssn',
  'code',
  'access_token',
  'refresh_token',
  'api_key',
  'credential',
  'jwt',
  'email',
  'phone',
  'vin',
  'session_id',
  'id_token',
  'magic_link',
]);

const PROHIBITED_METADATA_KEYS = new Set([
  'vin',
  'ssn',
  'password',
  'token',
  'chat_message',
  'credit_card',
  'secret',
  'secret_key',
  'auth',
  'api_key',
  'access_token',
  'refresh_token',
  'email',
  'contact_email',
  'phone',
  'gps',
  'latitude',
  'longitude',
  'id_token',
  'magic_link',
  'credential',
  'message',
  'msg',
  'user_message',
]);

export function sanitizeUrlPath(rawUrl: string): string {
  if (!rawUrl || typeof rawUrl !== 'string') return '/';

  try {
    const url = rawUrl.startsWith('http://') || rawUrl.startsWith('https://') || rawUrl.startsWith('//')
      ? new URL(rawUrl, 'http://localhost')
      : new URL(rawUrl, 'http://localhost');

    const params = new URLSearchParams(url.search);

    for (const key of Array.from(params.keys())) {
      const lowerKey = key.toLowerCase().trim();
      if (SENSITIVE_QUERY_PARAMS.has(lowerKey)) {
        params.set(key, '[REDACTED]');
      }
    }

    const path = url.pathname || '/';
    const cleanSearch = params.toString();

    // Sanitize hash fragment query parameters (M2-07, M2-17)
    let cleanHash = '';
    if (url.hash) {
      if (url.hash.includes('?')) {
        const [hashPath, hashQuery] = url.hash.split('?');
        const hashParams = new URLSearchParams(hashQuery);
        for (const key of Array.from(hashParams.keys())) {
          if (SENSITIVE_QUERY_PARAMS.has(key.toLowerCase().trim())) {
            hashParams.set(key, '[REDACTED]');
          }
        }
        const cleanHashQuery = hashParams.toString();
        cleanHash = cleanHashQuery ? `${hashPath}?${cleanHashQuery}` : hashPath;
      } else {
        cleanHash = url.hash;
      }
    }

    return cleanSearch ? `${path}?${cleanSearch}${cleanHash}` : `${path}${cleanHash}`;
  } catch {
    return rawUrl.replace(/([?&#](token|auth|password|key|secret|code|vin|email)=)[^&#]+/gi, '$1[REDACTED]');
  }
}

export function sanitizeReferrer(referrer: string | null | undefined): string | null {
  if (!referrer || typeof referrer !== 'string' || !referrer.trim()) return null;

  let ref = referrer.trim();
  if (ref.startsWith('//')) {
    ref = 'https:' + ref;
  } else if (!ref.startsWith('http://') && !ref.startsWith('https://')) {
    ref = 'https://' + ref;
  }

  try {
    const url = new URL(ref);
    const host = url.hostname.toLowerCase();
    return host || null;
  } catch {
    return null;
  }
}

function isProhibitedKey(key: string): boolean {
  const lower = key.toLowerCase().trim();
  if (PROHIBITED_METADATA_KEYS.has(lower)) return true;
  if (lower.includes('secret') || lower.includes('password') || lower.includes('credential')) {
    return true;
  }
  return false;
}

function cleanObjectRecursive(obj: any, depth = 0): any {
  if (depth > 5) return undefined;
  if (obj === null || typeof obj !== 'object') return obj;

  if (Array.isArray(obj)) {
    return obj
      .map((item) => cleanObjectRecursive(item, depth + 1))
      .filter((item) => item !== undefined);
  }

  const result: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    if (typeof k !== 'string') continue;
    if (isProhibitedKey(k)) {
      // Bar prohibited PII, chat message, or credential field
      continue;
    }
    const cleaned = cleanObjectRecursive(v, depth + 1);
    if (cleaned !== undefined) {
      result[k] = cleaned;
    }
  }
  return result;
}

export function sanitizeMetadata(metadata?: Record<string, unknown>): Record<string, unknown> {
  if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata)) return {};
  return cleanObjectRecursive(metadata, 0) || {};
}
