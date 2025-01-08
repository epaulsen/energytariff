import datetime
from rx.subject.behaviorsubject import BehaviorSubject
from homeassistant.core import (
    HomeAssistant,
)


class EnergyData:
    """Class used to transmit sensor nofication via rx"""

    def __init__(self, energy: float, effect: float, timestamp: datetime):
        self.energy_consumed = energy
        self.current_effect = effect
        self.timestamp = timestamp


class TopHour:
    """Holds data for an hour of consumption"""

    def __init__(self, day: int, hour: int, energy: float):
        self.day = day
        self.hour = hour
        self.energy = energy


class GridThresholdData:
    """Class used to transmit changes of level threshold changes"""

    def __init__(self, name, level: float, price: float, top_three: any):
        self.name = name
        self.level = level
        self.price = price
        self.top_three = top_three


class GridCapacityCoordinator:
    """Coordinator entity that signals notifications for sensors"""

    def __init__(self, hass: HomeAssistant):
        self._hass = hass
        self.effectstate = BehaviorSubject(None)
        self.thresholddata = BehaviorSubject(None)
