// 공용 유틸 — 의존성 없이 Node 20+ 내장 fetch만 사용합니다.
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname } from 'node:path';

export async function getJSON(url, init = {}) {
  return (await get(url, init)).json();
}

export async function getText(url, init = {}) {
  return (await get(url, init)).text();
}

async function get(url, init = {}, tries = 3) {
  let lastErr;
  for (let i = 0; i < tries; i++) {
    try {
      const res = await fetch(url, {
        ...init,
        headers: {
          'user-agent': 'Mozilla/5.0 (compatible; koreagiftcard-bot/1.0)',
          ...(init.headers || {}),
        },
        signal: AbortSignal.timeout(20000),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status} ${url}`);
      return res;
    } catch (err) {
      lastErr = err;
      await new Promise((r) => setTimeout(r, 1000 * (i + 1)));
    }
  }
  throw lastErr;
}

export async function readJSON(path, fallback) {
  try {
    return JSON.parse(await readFile(path, 'utf8'));
  } catch {
    return fallback;
  }
}

export async function writeJSON(path, data) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, JSON.stringify(data, null, 2) + '\n', 'utf8');
  console.log(`wrote ${path}`);
}

/** 한국 시간 기준 ISO 문자열 */
export function nowKST() {
  return new Date().toLocaleString('sv-SE', { timeZone: 'Asia/Seoul' }).replace(' ', 'T') + '+09:00';
}

/** 한국 시간 "YYYY-MM-DD HH:MM" (화면 표시용) */
export function nowKSTLabel() {
  return new Date().toLocaleString('sv-SE', { timeZone: 'Asia/Seoul' }).slice(0, 16);
}
