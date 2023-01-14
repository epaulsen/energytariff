import rx
from homeassistant.helpers.typing import (
    HomeAssistantType,
)


class EffectData:
    def __init__(self, energy, effect):
        self.energy_consumed = energy
        self.current_effect = effect


class GridCapacityCoordinator:
    """Coordinator entity that signals notifications for sensors"""
    def __init__(self, hass: HomeAssistantType):
        self._hass = hass
        self.effectstate = rx.subject.BehaviorSubject(None)
        


