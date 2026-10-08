"""Klien HTTP 'sopan': satu koneksi, jeda antar request, retry, berhenti saat diblokir."""
import time

import httpx

USER_AGENT = "pantau-rup/0.1 (riset pribadi, data publik; https://github.com/razifaisal-design/webscrapperrazi)"


class DiblokirError(RuntimeError):
    """Server menolak (403/429). Berhenti, jangan dilawan."""


class SopanClient:
    def __init__(self, jeda=1.5, timeout=30, retry=3):
        self.jeda = jeda
        self.retry = retry
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True
        )
        self._terakhir = 0.0

    def get_json(self, url, params=None):
        return self._get(url, params).json()

    def get_text(self, url, params=None):
        return self._get(url, params).text

    def _get(self, url, params=None):
        for percobaan in range(1, self.retry + 1):
            tunggu = self.jeda - (time.monotonic() - self._terakhir)
            if tunggu > 0:
                time.sleep(tunggu)
            try:
                resp = self._client.get(url, params=params)
            except httpx.TransportError:
                self._terakhir = time.monotonic()
                if percobaan == self.retry:
                    raise
                time.sleep(2 ** percobaan)
                continue
            self._terakhir = time.monotonic()
            if resp.status_code in (403, 429):
                raise DiblokirError(f"HTTP {resp.status_code} dari {url} - berhenti.")
            if resp.status_code >= 500 and percobaan < self.retry:
                time.sleep(2 ** percobaan)
                continue
            resp.raise_for_status()
            return resp

    def close(self):
        self._client.close()
