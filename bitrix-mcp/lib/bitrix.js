export function normalizeBase(value) {
  if (!value) return null;
  return value.endsWith('/') ? value : `${value}/`;
}

export function createBitrixClient(baseUrl) {
  const base = normalizeBase(baseUrl);
  if (!base) throw new Error('BITRIX_BASE is not set');

  return async function bitrix(method, params = {}) {
    const response = await fetch(`${base}${method}.json`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(params)
    });

    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error(`Bitrix returned non-JSON for ${method} (HTTP ${response.status})`);
    }

    if (!response.ok || data?.error) {
      throw new Error(data?.error_description || data?.error || `Bitrix HTTP ${response.status}`);
    }
    return data;
  };
}

export function textResult(value) {
  return { content: [{ type: 'text', text: JSON.stringify(value, null, 2) }] };
}
