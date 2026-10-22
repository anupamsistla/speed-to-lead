"""Zip to office routing and round-robin rep assignment, from routing.yaml."""

from __future__ import annotations

from leadagent.config.schemas import Office, Rep, RoutingConfig


class Router:
    def __init__(self, routing: RoutingConfig):
        self.routing = routing
        self._by_zip = {z: o for o in routing.offices for z in o.zips}
        self._offices = {o.id: o for o in routing.offices}
        self._pointer: dict[str, int] = {o.id: 0 for o in routing.offices}

    def office_for_zip(self, zip_code: str) -> Office | None:
        office = self._by_zip.get(zip_code)
        if office is None and self.routing.default_office:
            office = self._offices[self.routing.default_office]
        return office

    def office(self, office_id: str) -> Office:
        return self._offices[office_id]

    def rep(self, rep_id: str) -> tuple[Rep, Office]:
        for o in self.routing.offices:
            for r in o.reps:
                if r.id == rep_id:
                    return r, o
        raise KeyError(rep_id)

    def assign_rep(self, office_id: str) -> Rep:
        office = self._offices[office_id]
        i = self._pointer[office_id] % len(office.reps)
        self._pointer[office_id] = i + 1
        return office.reps[i]

    def rep_order(self, office_id: str, first: str | None = None) -> list[Rep]:
        """Office reps with `first` (the assigned rep) moved to the front."""
        reps = list(self._offices[office_id].reps)
        reps.sort(key=lambda r: r.id != first)
        return reps
