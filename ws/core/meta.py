#! /usr/bin/env python3

import datetime

class Meta:
    """
    Meta-class for ``siteinfo`` and ``userinfo`` functionality.

    Subclasses must configure the :py:attr:`module` and :py:attr:`properties`
    attributes.
    """

    module = ""
    properties = set()
    volatile_properties = set()
    timeout = 0
    volatile_timeout = 0

    def __init__(self, api):
        self._api = api
        self._values = {}
        self._timestamps = {}

    # TODO: expand, move somewhere more suitable
    @classmethod
    def _abbreviation(klass):
        abbreviations = {
            "siteinfo": "si",
            "userinfo": "ui",
        }
        if klass.module not in abbreviations:
            raise NotImplementedError("The abbreviation of '{}' module is not known.".format(klass.module))
        return abbreviations[klass.module]

    def fetch(self, prop=None):
        """
        Auxiliary method for querying properties.
        """
        utcnow = datetime.datetime.utcnow()

        data = {
            "action": "query",
            "meta": self.module,
            }
        if isinstance(prop, list):
            data[self._abbreviation() + "prop"] = "|".join(prop)
        # TODO: name and id are for userinfo, other modules might have their own 'special' properties
        elif prop in self.properties - {"name", "id"}:
            data[self._abbreviation() + "prop"] = prop
        result = self._api.call_api(data)

        # FIXME: WTF is siteinfo different than userinfo?
        if self.module in result:
            result = result[self.module]

        self._values.update(result)
        for p in result:
            self._timestamps[p] = utcnow

        if isinstance(prop, str):
            return result[prop]
        return result

    def __getattr__(self, attr):
        if attr not in self.properties:
            raise AttributeError("Invalid attribute: '{}'. Valid attributes are: {}".format(attr, sorted(self.properties)))

        utcnow = datetime.datetime.utcnow()
        if attr in self.volatile_properties:
            delta = datetime.timedelta(seconds=self.volatile_timeout)
        else:
            delta = datetime.timedelta(seconds=self.timeout)

        # don't fetch if delta is 0
        if attr not in self._values or (delta and self._timestamps.get(attr, utcnow) < utcnow - delta):
            self.fetch(attr)
        return self._values[attr]
