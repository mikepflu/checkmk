#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2019 tribe29 GmbH - License: GNU General Public License v2
# This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
# conditions defined in the file COPYING, which is part of this source code package.

import abc
from typing import Any, Dict, List, Optional, Tuple, TypeVar, Union

from cmk.utils.check_utils import section_name_of
from cmk.utils.type_defs import CheckPluginName, HostName, Item, RawAgentData, SectionName

from cmk.snmplib.type_defs import (
    SNMPPersistedSections,
    SNMPRawData,
    SNMPSectionContent,
    SNMPSections,
)

from cmk.base.caching import runtime_cache as _runtime_cache
from cmk.base.discovered_labels import DiscoveredServiceLabels

LegacyCheckParameters = Union[None, Dict, Tuple, List, str]
RulesetName = str

SectionCacheInfo = Dict[SectionName, Tuple[int, int]]

AgentSectionContent = List[List[str]]
PersistedAgentSection = Tuple[int, int, AgentSectionContent]
PersistedAgentSections = Dict[SectionName, PersistedAgentSection]
AgentSections = Dict[SectionName, AgentSectionContent]

PiggybackRawData = Dict[HostName, List[bytes]]
ParsedSectionContent = Any
FinalSectionContent = Union[None, ParsedSectionContent, List[ParsedSectionContent]]

AbstractSectionContent = Union[AgentSectionContent, SNMPSectionContent]
AbstractRawData = Union[RawAgentData, SNMPRawData]
AbstractSections = Union[AgentSections, SNMPSections]
AbstractPersistedSections = Union[PersistedAgentSections, SNMPPersistedSections]

BoundedAbstractRawData = TypeVar("BoundedAbstractRawData", bound=AbstractRawData)
BoundedAbstractSectionContent = TypeVar("BoundedAbstractSectionContent",
                                        bound=AbstractSectionContent)
BoundedAbstractSections = TypeVar("BoundedAbstractSections", bound=AbstractSections)
BoundedAbstractPersistedSections = TypeVar("BoundedAbstractPersistedSections",
                                           bound=AbstractPersistedSections)


class ABCService(abc.ABC):
    __slots__ = ["_check_plugin_name", "_item", "_description", "_service_labels"]

    def __init__(
        self,
        check_plugin_name: CheckPluginName,
        item: Item,
        description: str,
        service_labels: DiscoveredServiceLabels = None,
    ) -> None:
        self._check_plugin_name = check_plugin_name
        self._item = item
        self._description = description
        self._service_labels = service_labels or DiscoveredServiceLabels()

    @property
    def check_plugin_name(self) -> CheckPluginName:
        return self._check_plugin_name

    @property
    def item(self) -> Item:
        return self._item

    @property
    def description(self) -> str:
        return self._description

    @property
    def service_labels(self):
        # type: () -> DiscoveredServiceLabels
        return self._service_labels

    def _service_id(self) -> Tuple[CheckPluginName, Item]:
        return self.check_plugin_name, self.item

    def __eq__(self, other: Any) -> bool:
        """Is used during service discovery list computation to detect and replace duplicates
        For this the parameters and similar need to be ignored."""
        if not isinstance(other, ABCService):
            raise TypeError("Can only be compared with other Service objects")
        return self._service_id() == other._service_id()

    def __hash__(self) -> int:
        """Is used during service discovery list computation to detect and replace duplicates
        For this the parameters and similar need to be ignored."""
        return hash(self._service_id())

    @abc.abstractmethod
    def __repr__(self) -> str:
        raise NotImplementedError()

    @abc.abstractmethod
    def dump_autocheck(self) -> str:
        raise NotImplementedError()


class Service(ABCService):
    __slots__ = ["_parameters"]

    def __init__(
        self,
        check_plugin_name: CheckPluginName,
        item: Item,
        description: str,
        parameters: LegacyCheckParameters,
        service_labels: DiscoveredServiceLabels = None,
    ) -> None:
        super(Service, self).__init__(check_plugin_name, item, description, service_labels)
        self._parameters = parameters

    @property
    def parameters(self) -> LegacyCheckParameters:
        return self._parameters

    def __repr__(self) -> str:
        return "Service(check_plugin_name=%r, item=%r, description=%r, parameters=%r, service_lables=%r)" % (
            self._check_plugin_name, self._item, self._description, self._parameters,
            self._service_labels)

    def dump_autocheck(self) -> str:
        return "{'check_plugin_name': %r, 'item': %r, 'parameters': %r, 'service_labels': %r}" % (
            self.check_plugin_name,
            self.item,
            self.parameters,
            self.service_labels.to_dict(),
        )


CheckTable = Dict[Tuple[CheckPluginName, Item], Service]


class DiscoveredService(ABCService):
    """Special form of Service() which holds the unresolved textual representation of the check parameters"""

    __slots__ = ["_parameters_unresolved"]

    def __init__(
        self,
        check_plugin_name: CheckPluginName,
        item: Item,
        description: str,
        parameters_unresolved: str,
        service_labels: DiscoveredServiceLabels = None,
    ) -> None:
        super(DiscoveredService, self).__init__(check_plugin_name, item, description,
                                                service_labels)
        self._parameters_unresolved = parameters_unresolved

    @property
    def parameters_unresolved(self) -> str:
        """Returns the unresolved check parameters discovered for this service

        The reason for this hack is some old check API behaviour: A check may return the name of
        a default levels variable (as string), for example "cpu_utilization_default_levels".
        The user is allowed to override the value of this variable in his configuration and
        the check needs to evaluate this variable after config loading or during check
        execution. The parameter must not be resolved during discovery.
        """
        return self._parameters_unresolved

    def __repr__(self) -> str:
        return ("DiscoveredService(check_plugin_name=%r, item=%r, description=%r, "
                "parameters_unresolved=%r, service_lables=%r)") % (
                    self._check_plugin_name, self._item, self._description,
                    self._parameters_unresolved, self._service_labels)

    def dump_autocheck(self) -> str:
        return "{'check_plugin_name': %r, 'item': %r, 'parameters': %s, 'service_labels': %r}" % (
            self.check_plugin_name,
            self.item,
            self.parameters_unresolved,
            self.service_labels.to_dict(),
        )


DiscoveredCheckTable = Dict[Tuple[CheckPluginName, Item], DiscoveredService]


def is_snmp_check(check_plugin_name):
    # type: (str) -> bool
    cache = _runtime_cache.get_dict("is_snmp_check")
    try:
        return cache[check_plugin_name]
    except KeyError:
        snmp_checks = _runtime_cache.get_set("check_type_snmp")
        result = section_name_of(check_plugin_name) in snmp_checks
        cache[check_plugin_name] = result
        return result


# TODO (mo): *consider* using the type aliases.
def get_default_parameters(
    check_info_dict: Dict[str, Any],
    factory_settings: Dict[str, Dict[str, Any]],
    check_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """compute default parameters"""
    params_variable_name = check_info_dict.get("default_levels_variable")
    if not params_variable_name:
        return None

    # factory_settings
    fs_parameters = factory_settings.get(params_variable_name, {})

    # global scope of check context
    gs_parameters = check_context.get(params_variable_name)

    return {
        **fs_parameters,
        **gs_parameters,
    } if isinstance(gs_parameters, dict) else fs_parameters
