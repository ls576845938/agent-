const BASE = '';  // vite proxy handles routing

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path);
  if (!res.ok) throw new ApiError(res.status, `GET ${path}: ${res.status}`);
  return res.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new ApiError(res.status, `POST ${path}: ${res.status}`);
  return res.json() as Promise<T>;
}

export async function apiPostRaw(path: string, body?: unknown): Promise<Response> {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: body ? JSON.stringify(body) : undefined,
  });
  return res;  // caller checks .ok
}
