from datetime import timedelta
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .const import DEFAULT_SCAN_SECS
import aiohttp

class DomovraCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, base_url: str):
        self._session = hass.helpers.aiohttp_client.async_get_clientsession()
        self.base_url = base_url.rstrip("/")
        super().__init__(
            hass,
            logger=hass.logger,
            name="DomovraCoordinator",
            update_interval=timedelta(seconds=DEFAULT_SCAN_SECS),
        )

    async def _async_update_data(self):
        url = f"{self.base_url}/api/ha/summary"
        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                resp.raise_for_status()
                return await resp.json()
        except Exception as e:
            raise UpdateFailed(f"Domovra API error: {e}")
