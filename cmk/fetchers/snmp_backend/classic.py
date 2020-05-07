#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2019 tribe29 GmbH - License: GNU General Public License v2
# This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
# conditions defined in the file COPYING, which is part of this source code package.

import os
import signal
from typing import List, Optional

import six

import cmk.base.snmp_utils as snmp_utils  # pylint: disable=cmk-module-layer-violation
import cmk.utils.cmk_subprocess as subprocess
import cmk.utils.tty as tty
from cmk.utils.exceptions import MKGeneralException, MKSNMPError, MKTimeout
from cmk.utils.log import console
from cmk.utils.type_defs import (
    OID,
    ContextName,
    RawValue,
    SNMPHostConfig,
    SNMPRowInfo,
)

from ._base import ABCSNMPBackend
from ._utils import strip_snmp_value

__all__ = ["ClassicSNMPBackend"]


class ClassicSNMPBackend(ABCSNMPBackend):
    def get(self, snmp_config, oid, context_name=None):
        # type: (SNMPHostConfig, OID, Optional[ContextName]) -> Optional[RawValue]
        if oid.endswith(".*"):
            oid_prefix = oid[:-2]
            commandtype = "getnext"
        else:
            oid_prefix = oid
            commandtype = "get"

        protospec = self._snmp_proto_spec(snmp_config)
        ipaddress = snmp_config.ipaddress
        if snmp_config.is_ipv6_primary:
            ipaddress = "[" + ipaddress + "]"
        portspec = self._snmp_port_spec(snmp_config)
        command = (
            self._snmp_base_command(commandtype, snmp_config, context_name) +
            ["-On", "-OQ", "-Oe", "-Ot",
             "%s%s%s" % (protospec, ipaddress, portspec), oid_prefix])

        console.vverbose("Running '%s'\n" % subprocess.list2cmdline(command))

        snmp_process = subprocess.Popen(
            command,
            close_fds=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
        )
        exitstatus = snmp_process.wait()
        if snmp_process.stderr is None or snmp_process.stdout is None:
            raise TypeError()
        if exitstatus:
            console.verbose(tty.red + tty.bold + "ERROR: " + tty.normal + "SNMP error\n")
            console.verbose(snmp_process.stderr.read() + "\n")
            return None

        line = snmp_process.stdout.readline().strip()
        if not line:
            console.verbose("Error in response to snmpget.\n")
            return None

        parts = line.split("=", 1)
        if len(parts) != 2:
            return None
        item = parts[0]
        value = parts[1].strip()
        console.vverbose("SNMP answer: ==> [%s]\n" % value)
        if value.startswith('No more variables') or \
           value.startswith('End of MIB') or \
           value.startswith('No Such Object available') or \
           value.startswith('No Such Instance currently exists'):
            return None

        # In case of .*, check if prefix is the one we are looking for
        if commandtype == "getnext" and not item.startswith(oid_prefix + "."):
            return None

        return strip_snmp_value(value)

    def walk(self,
             snmp_config,
             oid,
             check_plugin_name=None,
             table_base_oid=None,
             context_name=None):
        # type: (SNMPHostConfig, str, Optional[str], Optional[str], Optional[str]) -> SNMPRowInfo
        protospec = self._snmp_proto_spec(snmp_config)

        ipaddress = snmp_config.ipaddress
        if snmp_config.is_ipv6_primary:
            ipaddress = "[" + ipaddress + "]"

        portspec = self._snmp_port_spec(snmp_config)
        command = self._snmp_walk_command(snmp_config, context_name)
        command += ["-OQ", "-OU", "-On", "-Ot", "%s%s%s" % (protospec, ipaddress, portspec), oid]
        console.vverbose("Running '%s'\n" % subprocess.list2cmdline(command))

        snmp_process = None
        exitstatus = None
        rowinfo = []  # type: SNMPRowInfo
        try:
            snmp_process = subprocess.Popen(command,
                                            close_fds=True,
                                            stdin=open(os.devnull),
                                            stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE,
                                            encoding="utf-8")

            rowinfo = self._get_rowinfo_from_snmp_process(snmp_process)

        except MKTimeout:
            # On timeout exception try to stop the process to prevent child process "leakage"
            if snmp_process:
                os.kill(snmp_process.pid, signal.SIGTERM)
                snmp_process.wait()
            raise

        finally:
            # The stdout and stderr pipe are not closed correctly on a MKTimeout
            # Normally these pipes getting closed after p.communicate finishes
            # Closing them a second time in a OK scenario won't hurt neither..
            if snmp_process:
                exitstatus = snmp_process.wait()
                if snmp_process.stderr:
                    error = snmp_process.stderr.read()
                    snmp_process.stderr.close()
                if snmp_process.stdout:
                    snmp_process.stdout.close()

        if exitstatus:
            console.verbose(tty.red + tty.bold + "ERROR: " + tty.normal +
                            "SNMP error: %s\n" % six.ensure_str(error).strip())
            raise MKSNMPError("SNMP Error on %s: %s (Exit-Code: %d)" %
                              (ipaddress, six.ensure_str(error).strip(), exitstatus))
        return rowinfo

    def _get_rowinfo_from_snmp_process(self, snmp_process):
        # type: (subprocess.Popen) -> SNMPRowInfo
        if snmp_process.stdout is None:
            raise TypeError()

        line_iter = snmp_process.stdout
        # Ugly(1): in some cases snmpwalk inserts line feed within one
        # dataset. This happens for example on hexdump outputs longer
        # than a few bytes. Those dumps are enclosed in double quotes.
        # So if the value begins with a double quote, but the line
        # does not end with a double quote, we take the next line(s) as
        # a continuation line.
        rowinfo = []
        while True:
            try:
                line = next(line_iter).strip()
            except StopIteration:
                break

            parts = line.split('=', 1)
            if len(parts) < 2:
                continue  # broken line, must contain =
            oid = parts[0].strip()
            value = parts[1].strip()
            # Filter out silly error messages from snmpwalk >:-P
            if value.startswith('No more variables') or value.startswith('End of MIB') \
               or value.startswith('No Such Object available') \
               or value.startswith('No Such Instance currently exists'):
                continue

            if value == '"' or (len(value) > 1 and value[0] == '"' and
                                (value[-1] != '"')):  # to be continued
                while True:  # scan for end of this dataset
                    nextline = next(line_iter).strip()
                    value += " " + nextline
                    if value[-1] == '"':
                        break
            rowinfo.append((oid, strip_snmp_value(value)))
        return rowinfo

    def _snmp_proto_spec(self, snmp_config):
        # type: (SNMPHostConfig) -> str
        if snmp_config.is_ipv6_primary:
            return "udp6:"

        return ""

    def _snmp_port_spec(self, snmp_config):
        # type: (SNMPHostConfig) -> str
        if snmp_config.port == 161:
            return ""
        return ":%d" % snmp_config.port

    def _snmp_walk_command(self, snmp_config, context_name):
        # type: (SNMPHostConfig, Optional[ContextName]) -> List[str]
        """Returns command lines for snmpwalk and snmpget

        Including options for authentication. This handles communities and
        authentication for SNMP V3. Also bulkwalk hosts"""
        return self._snmp_base_command('walk', snmp_config, context_name) + ["-Cc"]

    # if the credentials are a string, we use that as community,
    # if it is a four-tuple, we use it as V3 auth parameters:
    # (1) security level (-l)
    # (2) auth protocol (-a, e.g. 'md5')
    # (3) security name (-u)
    # (4) auth password (-A)
    # And if it is a six-tuple, it has the following additional arguments:
    # (5) privacy protocol (DES|AES) (-x)
    # (6) privacy protocol pass phrase (-X)
    def _snmp_base_command(self, what, snmp_config, context_name):
        # type: (str, SNMPHostConfig, Optional[ContextName]) -> List[str]
        options = []

        if what == 'get':
            command = ['snmpget']
        elif what == 'getnext':
            command = ['snmpgetnext', '-Cf']
        elif snmp_config.is_bulkwalk_host:
            command = ['snmpbulkwalk']

            options.append("-Cr%d" % snmp_config.bulk_walk_size_of)
        else:
            command = ['snmpwalk']

        if not snmp_utils.is_snmpv3_host(snmp_config):
            # Handle V1 and V2C
            if snmp_config.is_bulkwalk_host:
                options.append('-v2c')
            else:
                if what == 'walk':
                    command = ['snmpwalk']
                if snmp_config.is_snmpv2or3_without_bulkwalk_host:
                    options.append('-v2c')
                else:
                    options.append('-v1')

            if not isinstance(snmp_config.credentials, str):
                raise TypeError()
            options += ["-c", snmp_config.credentials]

        else:
            # Handle V3
            if len(snmp_config.credentials) == 6:
                options += [
                    "-v3", "-l", snmp_config.credentials[0], "-a", snmp_config.credentials[1], "-u",
                    snmp_config.credentials[2], "-A", snmp_config.credentials[3], "-x",
                    snmp_config.credentials[4], "-X", snmp_config.credentials[5]
                ]
            elif len(snmp_config.credentials) == 4:
                options += [
                    "-v3", "-l", snmp_config.credentials[0], "-a", snmp_config.credentials[1], "-u",
                    snmp_config.credentials[2], "-A", snmp_config.credentials[3]
                ]
            elif len(snmp_config.credentials) == 2:
                options += [
                    "-v3", "-l", snmp_config.credentials[0], "-u", snmp_config.credentials[1]
                ]
            else:
                raise MKGeneralException("Invalid SNMP credentials '%r' for host %s: must be "
                                         "string, 2-tuple, 4-tuple or 6-tuple" %
                                         (snmp_config.credentials, snmp_config.hostname))

        # Do not load *any* MIB files. This save lot's of CPU.
        options += ["-m", "", "-M", ""]

        # Configuration of timing and retries
        settings = snmp_config.timing
        if "timeout" in settings:
            options += ["-t", "%0.2f" % settings["timeout"]]
        if "retries" in settings:
            options += ["-r", "%d" % settings["retries"]]

        if context_name is not None:
            options += ["-n", context_name]

        return command + options