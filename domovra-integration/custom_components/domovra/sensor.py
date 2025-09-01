from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN
from .coordinator import DomovraCoordinator

SENSORS = [
    ("Produits", "products_count", "mdi:package-variant"),
    ("Lots", "lots_count", "mdi:archive"),
    ("Bientôt", "soon_count", "mdi:timer-sand"),
    ("Urgents", "urgent_count", "mdi:alert-circle"),
]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add_entities: AddEntitiesCallback):
    coord: DomovraCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [DomovraCountSensor(coord, name, key, icon) for name, key, icon in SENSORS]
    add_entities(entities)

class DomovraCountSensor(SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: DomovraCoordinator, name: str, key: str, icon: str):
        self.coordinator = coordinator
        self._key = key
        self._attr_name = f"Domovra {name}"
        self._attr_unique_id = f"domovra_{key}"
        self._attr_icon = icon

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return data.get(self._key)

    async def async_update(self):
        await self.coordinator.async_request_refresh()
