from __future__ import annotations

from copy import deepcopy
from threading import RLock

from comicflow.domain.models import JsonObject


class ProviderConfigStore:
    """Process-local, independent test/production profiles with redacted views."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._profiles: dict[str, dict[str, JsonObject]] = {}
        self._active = {capability: "production" for capability in ("text", "image", "video")}

    def active_slot(self, capability: str) -> str:
        with self._lock:
            return self._active[capability]

    def configure_profile(
        self, capability: str, slot: str, profile: JsonObject, api_key: str | None
    ) -> None:
        with self._lock:
            clean = deepcopy(profile)
            clean.pop("apiKey", None)
            clean.pop("api_key", None)
            old = self._profiles.setdefault(capability, {}).get(slot, {})
            clean["apiKey"] = old.get("apiKey", "") if api_key is None else api_key
            self._profiles[capability][slot] = clean

    def get_profile(self, capability: str, slot: str) -> JsonObject:
        with self._lock:
            return {"apiKey": "", **deepcopy(self._profiles.get(capability, {}).get(slot, {}))}

    def masked_profile(self, capability: str, slot: str) -> JsonObject:
        value = self.get_profile(capability, slot)
        configured = bool(value.pop("apiKey", ""))
        return {
            "enabled": False,
            **value,
            "configured": configured,
            "apiKeyMasked": "********" if configured else "",
        }

    def activate(self, capability: str, slot: str) -> None:
        with self._lock:
            self._active[capability] = slot

    def clear_profile(self, capability: str, slot: str) -> None:
        with self._lock:
            self._profiles.get(capability, {}).pop(slot, None)

    def profile_views(self) -> JsonObject:
        with self._lock:
            return {
                cap: {
                    "active": self._active[cap],
                    **{slot: self.masked_profile(cap, slot) for slot in ("test", "production")},
                }
                for cap in self._active
            }

    def configure_media(self, capability: str, profile: JsonObject, api_key: str | None) -> None:
        self.configure_profile(capability, self.active_slot(capability), profile, api_key)

    def get_media(self, capability: str) -> JsonObject:
        return self.get_profile(capability, self.active_slot(capability))

    def masked_media(self, capability: str) -> JsonObject:
        return self.masked_profile(capability, self.active_slot(capability))

    def clear_media(self, capability: str) -> None:
        self.clear_profile(capability, self.active_slot(capability))

    def configure_text(self, profile: JsonObject, api_key: str | None) -> None:
        self.configure_media("text", profile, api_key)

    def get_text(self) -> JsonObject:
        value = self.get_media("text")
        return value if value.get("provider") else {"configured": False, "enabled": False}

    def masked_text(self) -> JsonObject:
        return self.masked_media("text")

    def text_enabled(self) -> bool:
        value = self.get_text()
        return bool(value.get("enabled") and value.get("apiKey"))

    def clear_text(self) -> None:
        self.clear_media("text")
