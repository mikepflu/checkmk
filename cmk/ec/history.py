#!/usr/bin/env python3
# -*- encoding: utf-8; py-indent-offset: 4 -*-
# +------------------------------------------------------------------+
# |             ____ _               _        __  __ _  __           |
# |            / ___| |__   ___  ___| | __   |  \/  | |/ /           |
# |           | |   | '_ \ / _ \/ __| |/ /   | |\/| | ' /            |
# |           | |___| | | |  __/ (__|   <    | |  | | . \            |
# |            \____|_| |_|\___|\___|_|\_\___|_|  |_|_|\_\           |
# |                                                                  |
# | Copyright Mathias Kettner 2018             mk@mathias-kettner.de |
# +------------------------------------------------------------------+
#
# This file is part of Check_MK.
# The official homepage is at http://mathias-kettner.de/check_mk.
#
# check_mk is free software;  you can redistribute it and/or modify it
# under the  terms of the  GNU General Public License  as published by
# the Free Software Foundation in version 2.  check_mk is  distributed
# in the hope that it will be useful, but WITHOUT ANY WARRANTY;  with-
# out even the implied warranty of  MERCHANTABILITY  or  FITNESS FOR A
# PARTICULAR PURPOSE. See the  GNU General Public License for more de-
# tails. You should have  received  a copy of the  GNU  General Public
# License along with GNU Make; see the file  COPYING.  If  not,  write
# to the Free Software Foundation, Inc., 51 Franklin St,  Fifth Floor,
# Boston, MA 02110-1301 USA.

import os
import struct
import subprocess
import threading
import time
from logging import Logger  # pylint: disable=unused-import
from pathlib import Path  # pylint: disable=unused-import
from typing import Any, AnyStr, Dict, List, Optional, Tuple  # pylint: disable=unused-import

from cmk.ec.settings import Settings  # pylint: disable=unused-import
import cmk.ec.actions
from cmk.utils.log import VERBOSE
import cmk.utils.render

# TODO: As one can see clearly below, we should really have a class hierarchy here...


class History:
    def __init__(self, settings, config, logger, event_columns, history_columns):
        # type: (Settings, Dict[str, Any], Logger, List[Tuple[str, Any]], List[Tuple[str, Any]]) -> None
        super().__init__()
        self._settings = settings
        self._config = config
        self._logger = logger
        self._event_columns = event_columns
        self._history_columns = history_columns
        self._lock = threading.Lock()
        self._mongodb = MongoDB()
        self._active_history_period = ActiveHistoryPeriod()
        self.reload_configuration(config)

    def reload_configuration(self, config):
        # type: (Any) -> None
        self._config = config
        if self._config['archive_mode'] == 'mongodb':
            _reload_configuration_mongodb(self)
        else:
            _reload_configuration_files(self)

    def flush(self):
        # type: () -> None
        if self._config['archive_mode'] == 'mongodb':
            _flush_mongodb(self)
        else:
            _flush_files(self)

    def add(self, event, what, who="", addinfo=""):
        # type: (Dict[str, Any], str, str, str) -> None
        if self._config['archive_mode'] == 'mongodb':
            _add_mongodb(self, event, what, who, addinfo)
        else:
            _add_files(self, event, what, who, addinfo)

    # TODO: We can't use Query in the type because of cyclic imports... :-/
    def get(self, query):
        # type: (Any) -> List[Any]
        if self._config['archive_mode'] == 'mongodb':
            return _get_mongodb(self, query)
        return _get_files(self, self._logger, query)

    def housekeeping(self):
        # type: () -> None
        if self._config['archive_mode'] == 'mongodb':
            _housekeeping_mongodb(self)
        else:
            _housekeeping_files(self)


#.
#   .--MongoDB-------------------------------------------------------------.
#   |             __  __                         ____  ____                |
#   |            |  \/  | ___  _ __   __ _  ___ |  _ \| __ )               |
#   |            | |\/| |/ _ \| '_ \ / _` |/ _ \| | | |  _ \               |
#   |            | |  | | (_) | | | | (_| | (_) | |_| | |_) |              |
#   |            |_|  |_|\___/|_| |_|\__, |\___/|____/|____/               |
#   |                                |___/                                 |
#   +----------------------------------------------------------------------+
#   | The Event Log Archive can be stored in a MongoDB instead of files,   |
#   | this section contains MongoDB related code.                          |
#   '----------------------------------------------------------------------'

try:
    from pymongo.connection import Connection  # type: ignore[import]
    from pymongo import DESCENDING  # type: ignore[import]
    from pymongo.errors import OperationFailure  # type: ignore[import]
    import datetime
except ImportError:
    Connection = None


class MongoDB:
    def __init__(self):
        # type: () -> None
        super().__init__()
        self.connection = None  # type: Connection
        self.db = None  # type: Any


def _reload_configuration_mongodb(history):
    # type: (History) -> None
    # Configure the auto deleting indexes in the DB
    _update_mongodb_indexes(history._settings, history._mongodb)
    _update_mongodb_history_lifetime(history._settings, history._config, history._mongodb)


def _housekeeping_mongodb(history):
    # type: (History) -> None
    pass


def _connect_mongodb(settings, mongodb):
    # type: (Settings, MongoDB) -> None
    if Connection is None:
        raise Exception('Could not initialize MongoDB (Python-Modules are missing)')
    mongodb.connection = Connection(*_mongodb_local_connection_opts(settings))
    mongodb.db = mongodb.connection.__getitem__(os.environ['OMD_SITE'])


def _mongodb_local_connection_opts(settings):
    # type: (Settings) -> Tuple[Optional[str], Optional[int]]
    ip, port = None, None
    with settings.paths.mongodb_config_file.value.open(encoding='utf-8') as f:
        for l in f:
            if l.startswith('bind_ip'):
                ip = l.split('=')[1].strip()
            elif l.startswith('port'):
                port = int(l.split('=')[1].strip())
    return ip, port


def _flush_mongodb(history):
    # type: (History) -> None
    history._mongodb.db.ec_archive.drop()


def _get_mongodb_max_history_age(mongodb):
    # type: (MongoDB) -> int
    result = mongodb.db.ec_archive.index_information()
    if 'dt_-1' not in result or 'expireAfterSeconds' not in result['dt_-1']:
        return -1
    return result['dt_-1']['expireAfterSeconds']


def _update_mongodb_indexes(settings, mongodb):
    # type: (Settings, MongoDB) -> None
    if not mongodb.connection:
        _connect_mongodb(settings, mongodb)
    result = mongodb.db.ec_archive.index_information()

    if 'time_-1' not in result:
        mongodb.db.ec_archive.ensure_index([('time', DESCENDING)])


def _update_mongodb_history_lifetime(settings, config, mongodb):
    # type: (Settings, Dict[str, Any], MongoDB) -> None
    if not mongodb.connection:
        _connect_mongodb(settings, mongodb)

    if _get_mongodb_max_history_age(mongodb) == config['history_lifetime'] * 86400:
        return  # do not update already correct index

    try:
        mongodb.db.ec_archive.drop_index("dt_-1")
    except OperationFailure:
        pass  # Ignore not existing index

    # Delete messages after x days
    mongodb.db.ec_archive.ensure_index([('dt', DESCENDING)],
                                       expireAfterSeconds=config['history_lifetime'] * 86400,
                                       unique=False)


def _mongodb_next_id(mongodb, name, first_id=0):
    # type: (MongoDB, str, int) -> int
    ret = mongodb.db.counters.find_and_modify(query={'_id': name},
                                              update={'$inc': {
                                                  'seq': 1
                                              }},
                                              new=True)

    if not ret:
        # Initialize the index!
        mongodb.db.counters.insert({'_id': name, 'seq': first_id})
        return first_id
    return ret['seq']


def _add_mongodb(history, event, what, who, addinfo):
    # type: (History, Dict[str, Any], str, str, str) -> None
    _log_event(history._config, history._logger, event, what, who, addinfo)
    if not history._mongodb.connection:
        _connect_mongodb(history._settings, history._mongodb)
    # We converted _id to be an auto incrementing integer. This makes the unique
    # index compatible to history_line of the file (which is handled as integer)
    # within mkeventd. It might be better to use the ObjectId() of MongoDB, but
    # for the first step, we use the integer index for simplicity
    now = time.time()
    history._mongodb.db.ec_archive.insert({
        '_id': _mongodb_next_id(history._mongodb, 'ec_archive_id'),
        'dt': datetime.datetime.fromtimestamp(now),
        'time': now,
        'event': event,
        'what': what,
        'who': who,
        'addinfo': addinfo,
    })


def _log_event(config, logger, event, what, who, addinfo):
    # type: (Dict[str, Any], Logger, Dict[str, Any], str, str, str) -> None
    if config['debug_rules']:
        logger.info("Event %d: %s/%s/%s - %s" % (event["id"], what, who, addinfo, event["text"]))


def _get_mongodb(history, query):
    # type: (History, Any) -> List[Any]
    filters, limit = query.filters, query.limit

    history_entries = []

    if not history._mongodb.connection:
        _connect_mongodb(history._settings, history._mongodb)

    # Construct the mongodb filtering specification. We could fetch all information
    # and do filtering on this data, but this would be way too inefficient.
    query = {}
    for column_name, operator_name, _predicate, argument in filters:

        if operator_name == '=':
            mongo_filter = argument
        elif operator_name == '>':
            mongo_filter = {'$gt': argument}
        elif operator_name == '<':
            mongo_filter = {'$lt': argument}
        elif operator_name == '>=':
            mongo_filter = {'$gte': argument}
        elif operator_name == '<=':
            mongo_filter = {'$lte': argument}
        elif operator_name == '~':  # case sensitive regex, find pattern in string
            mongo_filter = {'$regex': argument, '$options': ''}
        elif operator_name == '=~':  # case insensitive, match whole string
            mongo_filter = {'$regex': argument, '$options': 'mi'}
        elif operator_name == '~~':  # case insensitive regex, find pattern in string
            mongo_filter = {'$regex': argument, '$options': 'i'}
        elif operator_name == 'in':
            mongo_filter = {'$in': argument}
        else:
            raise Exception('Filter operator of filter %s not implemented for MongoDB archive' %
                            column_name)

        if column_name[:6] == 'event_':
            query['event.' + column_name[6:]] = mongo_filter
        elif column_name[:8] == 'history_':
            key = column_name[8:]
            if key == 'line':
                key = '_id'
            query[key] = mongo_filter
        else:
            raise Exception('Filter %s not implemented for MongoDB' % column_name)

    result = history._mongodb.db.ec_archive.find(query).sort('time', -1)

    # Might be used for debugging / profiling
    #open(cmk.utils.paths.omd_root + '/var/log/check_mk/ec_history_debug.log', 'a').write(
    #    pprint.pformat(filters) + '\n' + pprint.pformat(result.explain()) + '\n')

    if limit:
        result = result.limit(limit + 1)

    # now convert the MongoDB data structure to the eventd internal one
    for entry in result:
        item = [
            entry['_id'],
            entry['time'],
            entry['what'],
            entry['who'],
            entry['addinfo'],
        ]
        for colname, defval in history._event_columns:
            key = colname[6:]  # drop "event_"
            item.append(entry['event'].get(key, defval))
        history_entries.append(item)

    return history_entries


#.
#   .--History-------------------------------------------------------------.
#   |                   _   _ _     _                                      |
#   |                  | | | (_)___| |_ ___  _ __ _   _                    |
#   |                  | |_| | / __| __/ _ \| '__| | | |                   |
#   |                  |  _  | \__ \ || (_) | |  | |_| |                   |
#   |                  |_| |_|_|___/\__\___/|_|   \__, |                   |
#   |                                             |___/                    |
#   +----------------------------------------------------------------------+
#   | Functions for logging the history of events                          |
#   '----------------------------------------------------------------------'


def _reload_configuration_files(history):
    # type: (History) -> None
    pass


def _flush_files(history):
    # type: (History) -> None
    _expire_logfiles(history._settings, history._config, history._logger, history._lock, True)


def _housekeeping_files(history):
    # type: (History) -> None
    _expire_logfiles(history._settings, history._config, history._logger, history._lock, False)


# Make a new entry in the event history. Each entry is tab-separated line
# with the following columns:
# 0: time of log entry
# 1: type of entry (keyword)
# 2: user who initiated the action (for GUI actions)
# 3: additional information about the action
# 4-oo: StatusTableEvents.columns
def _add_files(history, event, what, who, addinfo):
    # type: (History, Dict[str, Any], str, str, str) -> None
    _log_event(history._config, history._logger, event, what, who, addinfo)
    with history._lock:
        columns = [
            quote_tab(str(time.time())),
            quote_tab(scrub_string(what)),
            quote_tab(scrub_string(who)),
            quote_tab(scrub_string(addinfo))
        ]
        columns += [
            quote_tab(event.get(colname[6:], defval))  # drop "event_"
            for colname, defval in history._event_columns
        ]

        with get_logfile(history._config, history._settings.paths.history_dir.value,
                         history._active_history_period).open(mode='ab') as f:
            f.write(b"\t".join(columns) + b"\n")


def quote_tab(col):
    # type: (Any) -> bytes
    ty = type(col)
    if ty in [float, int]:
        return str(col).encode("utf-8")
    if ty is bool:
        return b'1' if col else b'0'
    if ty in [tuple, list]:
        col = b"\1" + b"\1".join([quote_tab(e) for e in col])
    elif col is None:
        col = b"\2"
    elif ty is str:
        col = col.encode("utf-8")

    return col.replace(b"\t", b" ")


class ActiveHistoryPeriod:
    def __init__(self):
        # type: () -> None
        super().__init__()
        self.value = None  # type: Optional[int]


# Get file object to current log file, handle also
# history and lifetime limit.
def get_logfile(config, log_dir, active_history_period):
    # type: (Dict[str, Any], Path, ActiveHistoryPeriod) -> Path
    log_dir.mkdir(parents=True, exist_ok=True)
    # Log into file starting at current history period,
    # but: if a newer logfile exists, use that one. This
    # can happen if you switch the period from daily to
    # weekly.
    timestamp = _current_history_period(config)

    # Log period has changed or we have not computed a filename yet ->
    # compute currently active period
    if active_history_period.value is None or timestamp > active_history_period.value:

        # Look if newer files exist
        timestamps = sorted(int(str(path.name)[:-4]) for path in log_dir.glob('*.log'))
        if len(timestamps) > 0:
            timestamp = max(timestamps[-1], timestamp)

        active_history_period.value = timestamp

    return log_dir / ("%d.log" % timestamp)


# Return timestamp of the beginning of the current history
# period.
def _current_history_period(config):
    # type: (Dict[str, Any]) -> int
    lt = time.localtime()
    ts = time.mktime(
        time.struct_time((
            lt.tm_year,
            lt.tm_mon,
            lt.tm_mday,
            0,  # tm_hour
            0,  # tm_min
            0,  # tm_sec
            lt.tm_wday,
            lt.tm_yday,
            lt.tm_isdst,
            lt.tm_zone,
            lt.tm_gmtoff)))
    offset = lt.tm_wday * 86400 if config["history_rotation"] == "weekly" else 0
    return int(ts) - offset


# Delete old log files
def _expire_logfiles(settings, config, logger, lock_history, flush):
    # type: (Settings, Dict[str, Any], Logger, threading.Lock, bool) -> None
    with lock_history:
        try:
            days = config["history_lifetime"]
            min_mtime = time.time() - days * 86400
            logger.log(VERBOSE, "Expiring logfiles (Horizon: %d days -> %s)", days,
                       cmk.utils.render.date_and_time(min_mtime))
            for path in settings.paths.history_dir.value.glob('*.log'):
                if flush or path.stat().st_mtime < min_mtime:
                    logger.info("Deleting log file %s (age %s)" %
                                (path, cmk.utils.render.date_and_time(path.stat().st_mtime)))
                    path.unlink()
        except Exception as e:
            if settings.options.debug:
                raise
            logger.exception("Error expiring log files: %s" % e)


def _get_files(history, logger, query):
    # type: (History, Logger, Any) -> List[Any]
    filters, limit = query.filters, query.limit
    history_entries = []  # type: List[Any]
    if not history._settings.paths.history_dir.value.exists():
        return []

    logger.debug("Filters: %r", filters)
    logger.debug("Limit: %r", limit)

    # Be aware: The order here is important. It must match the order of the fields
    # in the history file entries (See get_event_history_from_file). The fields in
    # the file are currectly in the same order as StatusTableHistory.columns.
    #
    # Please note: Keep this in sync with livestatus/src/TableEventConsole.cc.
    grepping_filters = [
        'event_id',
        'event_text',
        'event_comment',
        'event_host',
        'event_host_regex',
        'event_contact',
        'event_application',
        'event_rule_id',
        'event_owner',
        'event_ipaddress',
        'event_core_host',
    ]

    # Optimization: use grep in order to reduce amount of read lines based on
    # some frequently used filters.
    #
    # It's ok if the filters don't match 100% accurately on the right lines. If in
    # doubt, you can output more lines than necessary. This is only a kind of
    # prefiltering.
    grep_pairs = []  # type: List[Tuple[int, str]]
    for column_name, operator_name, _predicate, argument in filters:
        # Make sure that the greptexts are in the same order as in the
        # actual logfiles. They will be joined with ".*"!
        try:
            nr = grepping_filters.index(column_name)
            if operator_name in ['=', '~~']:
                grep_pairs.append((nr, str(argument)))
        except Exception:
            pass

    grep_pairs.sort()
    greptexts = [x[1] for x in grep_pairs]
    logger.debug("Texts for grep: %r", greptexts)

    time_filters = [f for f in filters if f[0].split("_")[-1] == "time"]
    logger.debug("Time filters: %r", time_filters)

    # We do not want to open all files. So our strategy is:
    # look for "time" filters and first apply the filter to
    # the first entry and modification time of the file. Only
    # if at least one of both timestamps is accepted then we
    # take that file into account.
    # Use the later logfiles first, to get the newer log entries
    # first. When a limit is reached, the newer entries should
    # be processed in most cases. We assume that now.
    # To keep a consistent order of log entries, we should care
    # about sorting the log lines in reverse, but that seems to
    # already be done by the GUI, so we don't do that twice. Skipping
    # this # will lead into some lines of a single file to be limited in
    # wrong order. But this should be better than before.
    for ts, path in sorted(((int(str(path.name)[:-4]), path)
                            for path in history._settings.paths.history_dir.value.glob('*.log')),
                           reverse=True):
        if limit is not None and limit <= 0:
            break
        first_entry, last_entry = _get_logfile_timespan(path)
        for _column_name, _operator_name, predicate, _argument in time_filters:
            if predicate(first_entry):
                break
            if predicate(last_entry):
                break
        else:
            # If no filter matches but we *have* filters
            # then we skip this file. It cannot contain
            # any useful entry for us.
            if len(time_filters):
                if history._settings.options.debug:
                    history._logger.info("Skipping logfile %s.log because of time filter" % ts)
                continue  # skip this file

        new_entries = _parse_history_file(history, path, query, greptexts, limit, history._logger)
        history_entries += new_entries
        if limit is not None:
            limit -= len(new_entries)

    return history_entries


def _parse_history_file(history, path, query, greptexts, limit, logger):
    # type: (History, Path, Any, List[str], Optional[int], Logger) -> List[Any]
    entries = []  # type: List[Any]
    line_no = 0
    # If we have greptexts we pre-filter the file using the extremely
    # fast GNU Grep
    # Revert lines from the log file to have the newer lines processed first
    cmd = 'tac %s' % cmk.ec.actions.quote_shell_string(str(path))
    if greptexts:
        cmd += " | egrep -i -e %s" % cmk.ec.actions.quote_shell_string(".*".join(greptexts))
    grep = subprocess.Popen(cmd, shell=True, close_fds=True, stdout=subprocess.PIPE)  # nosec

    for line in grep.stdout:
        line_no += 1
        if limit is not None and len(entries) > limit:
            grep.kill()
            grep.wait()
            break

        try:
            parts = line.decode('utf-8').rstrip('\n').split('\t')  # type: List[Any]
            _convert_history_line(history, parts)
            values = [line_no] + parts
            if query.filter_row(values):
                entries.append(values)
        except Exception as e:
            logger.exception("Invalid line '%r' in history file %s: %s" % (line, path, e))

    return entries


# Speed-critical function for converting string representation
# of log line back to Python values
def _convert_history_line(history, values):
    # type: (History, List[Any]) -> None
    # NOTE: history_line column is missing here, so indices are off by 1! :-P
    values[0] = float(values[0])  # history_time
    values[4] = int(values[4])  # event_id
    values[5] = int(values[5])  # event_count
    values[7] = float(values[7])  # event_first
    values[8] = float(values[8])  # event_last
    values[10] = int(values[10])  # event_sl
    values[14] = int(values[14])  # event_pid
    values[15] = int(values[15])  # event_priority
    values[16] = int(values[16])  # event_facility
    values[18] = int(values[18])  # event_state
    values[21] = _unsplit(values[21])  # event_match_groups
    num_values = len(values)
    if num_values <= 22:  # event_contact_groups
        values.append(None)
    else:
        values[22] = _unsplit(values[22])
    if num_values <= 23:  # event_ipaddress
        values.append(history._history_columns[24][1])
    if num_values <= 24:  # event_orig_host
        values.append(history._history_columns[25][1])
    if num_values <= 25:  # event_contact_groups_precedence
        values.append(history._history_columns[26][1])
    if num_values <= 26:  # event_core_host
        values.append(history._history_columns[27][1])
    if num_values <= 27:  # event_host_in_downtime
        values.append(history._history_columns[28][1])
    else:
        values[27] = values[27] == "1"
    if num_values <= 28:  # event_match_groups_syslog_application
        values.append(history._history_columns[29][1])
    else:
        values[28] = _unsplit(values[28])


def _unsplit(s):
    # type: (Any) -> Any
    if not isinstance(s, str):
        return s

    if s.startswith('\2'):
        return None  # \2 is the designator for None

    if s.startswith('\1'):
        if len(s) == 1:
            return ()
        return tuple(s[1:].split('\1'))
    return s


def _get_logfile_timespan(path):
    # type: (Path) -> Tuple[float, float]
    try:
        with path.open(encoding="utf-8") as f:
            first_entry = float(f.readline().split('\t', 1)[0])
    except Exception:
        first_entry = 0.0
    try:
        last_entry = path.stat().st_mtime
    except Exception:
        last_entry = 0.0
    return first_entry, last_entry


# Rip out/replace any characters which have a special meaning in the UTF-8
# encoded history files, see e.g. quote_tab. In theory this shouldn't be
# necessary, because there are a bunch of bytes which are not contained in any
# valid UTF-8 string, but following Murphy's Law, those are not used in
# Check_MK. To keep backwards compatibility with old history files, we have no
# choice and continue to do it wrong... :-/
def scrub_string(s):
    # type: (AnyStr) -> AnyStr
    if isinstance(s, bytes):
        return s.translate(_scrub_string_str_table, b"\0\1\2\n")
    if isinstance(s, str):
        return s.translate(_scrub_string_unicode_table)
    raise TypeError("scrub_string expects a string argument")


_scrub_string_str_table = b''.join(
    b' ' if x == ord(b'\t') else struct.Struct(">B").pack(x) for x in range(256))
_scrub_string_unicode_table = {0: None, 1: None, 2: None, ord("\n"): None, ord("\t"): ord(" ")}
