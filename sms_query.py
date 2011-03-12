#!/usr/bin/env python2
#
# Query the Nokia N900 SMS message (sqlite) database, extracting SMS
# conversations to/from a given phone number.
#
# This file was written in 2011 by Johan Herland (johan@herland.net).
# It is licensed under the GNU General Public License v3 (or later).
#
# Structure of SMS message database table:
# CREATE TABLE Events (
#	id             INTEGER PRIMARY KEY,
#	service_id     INTEGER NOT NULL,
#	event_type_id  INTEGER NOT NULL,
#	storage_time   INTEGER NOT NULL,
#	start_time     INTEGER NOT NULL,
#	end_time       INTEGER,
#	is_read        INTEGER DEFAULT 0,
#	flags          INTEGER DEFAULT 0,
#	bytes_sent     INTEGER DEFAULT 0,
#	bytes_received INTEGER DEFAULT 0,
#	local_uid      TEXT,
#	local_name     TEXT,
#	remote_uid     TEXT,
#	channel        TEXT,
#	free_text      TEXT,
#	group_uid      TEXT,
#	outgoing       BOOL DEFAULT 0,
#	mc_profile     BOOL DEFAULT 0
#);
#
# Inspection of an instance of this table reveals the following insights:
#
# - "outgoing" is 0 for incoming messages, 1 for outgoing messages.
#
# - "remote_uid" holds the phone number of the remote end. For Norwegian phone
#   numbers, the format is either "+4712345678" or "12345678" (i.e. with or
#   without country prefix).
#
# - "free_text" contains the SMS message contents.
#
# - "storage_time", "start_time" and "end_time" all hold Unix-style integer
#   timestamps. All of them seem to be in UTC time.
#
# - "end_time" is 0 for outgoing messages. For incoming messages it is either
#   equal to, or slightly precedes "storage_time" (0 - 2 seconds).
#
# - "start_time" is identical to "storage_time" for outgoing messages. For
#   incoming messages, it seems to be within ~150 seconds of "storage_time",
#   most often _preceding_ ("start_time" < "storage_time").
#
# - "storage_time" is consistent with the ordering of the "id" field, and
#   therefore probably produces the most accurate sequencing of messages.
#   Informal inspection of message content reveals that ordering by
#   "start_time" produces out-of-order messages/conversations.
#
# More information deduced from reading the rtcom-eventlogger header files at
# <URL: http://maemo.gitorious.org/maemo-rtcom/rtcom-eventlogger/trees/master>
# and browsing the SQLite database:
#
# - "service_id" identifies which service is associated with an entry. The
#   available values are "id"s into the "Service" table, where each service
#   is described. Relevant values:
#   - 1: RTCOM_EL_SERVICE_CALL (i.e. voice call)
#   - 3: RTCOM_EL_SERVICE_SMS  (i.e. SMS message)
#
# - "event_type_id" identifies the type of an event entry. The available values
#   are "id"s into the "EventTypes" table, where each event type is described.
#   Relevant values:
#   - 1: RTCOM_EL_EVENTTYPE_CALL        (i.e. voice call)
#   - 3: RTCOM_EL_EVENTTYPE_CALL_MISSED (i.e. missed voice call)
#   - 7: RTCOM_EL_EVENTTYPE_SMS_MESSAGE (i.e. SMS message)
#
# - "remote_uid" can be cross-referenced with the "Remotes" table to get more
#   information from its "remote_name" field. (I guess that the "abook_uid"
#   field can also be useful, although I don't yet know what table/database
#   it references).
#
# - "flags" can probably be looked up in the "Flags" table to deduce their
#   meaning.

import sys
import sqlite3
import time
import re


DbFilename = "sms.db" # On Nokia N900: /home/user/.rtcom-eventlogger/el-v1.db

AnsiColors = {
	"red":     "\033[91m",
	"green":   "\033[92m",
	"yellow":  "\033[93m",
	"blue":    "\033[94m",
	"magenta": "\033[95m",
	"stop":    "\033[0m",
}


def colorize (color, s):
	return AnsiColors[color] + s + AnsiColors["stop"]


class Filter (object):
	"""Base class for filters that result in an SQL WHEN clause."""

	# Regular expression used to identify suitable command-line arguments
	# for this filter. If it matches, the argument can be passed to .add().
	ArgRe = re.compile(".*")

	def __str__ (self):
		"""Return a human-readable description of what is filtered."""
		return "(no-op filter)"

	def sql (self):
		"""Return a SQL WHERE clause implementing this filter.

		The returned clause if joined together with other filters'
		clauses (using " AND " as a separator), and then embedded into
		the final SQL statement that is then executed.

		Any '?' placeholders in the returned clause will be replaced by
		coresponding elements from the list returned by .args().
		"""
		return "(1 = ?)"

	def args (self):
		"""Return list of arguments to resolve placeholders in .sql().

		The returned list MUST have exactly the same length as the
		number of "?" arguments returned from .sql().
		"""
		return (1,)

	def add (self, arg):
		"""Parse a command-line argument intended for this filter."""
		raise NotImplementedError


class PhoneNumberFilter (Filter):
	"""Filter on the given phone numbers."""

	ArgRe = re.compile("\+?\d+$")

	def __init__ (self):
		self.nums = []

	def __str__ (self):
		return "phone# in (%s)" % (", ".join(self.nums))

	def sql (self):
		if not self.nums:
			return Filter.sql(self)
		return "(%s)" % (" OR ".join(["Events.remote_uid = ?" for n in self.nums]))

	def args (self):
		return self.nums

	def add (self, phonenum):
		self.nums.append(phonenum)
		if phonenum.startswith("+47"):
			self.nums.append(phonenum[3:])
		else:
			self.nums.append("+47" + phonenum)


def main (args = []):
	# All command-line arguments are filters on the displayed events.
	# Arguments are interpreted as follows (case-insensitively):
	#
	# - "<num>" or "+<num>": Limit to given phone number

	FilterClasses = (PhoneNumberFilter,)
	filters = {} # dict: Filter class name -> Filter instance

	for arg in args[1:]:
		for Class in FilterClasses:
			if Class.ArgRe.match(arg):
				f = filters.setdefault(Class.__name__, Class())
				f.add(arg)

	filter_descs = [] # Human-readable description of applied filters
	filter_clauses = [] # SQL clauses of applied filters
	filter_args = [] # List of SQL statement arguments from applied filters
	for f in filters.itervalues():
		filter_descs.append(str(f))
		filter_clauses.append(f.sql())
		filter_args.extend(f.args())

	conn = sqlite3.connect(DbFilename)
	c = conn.cursor()
	c.execute("""\
SELECT	EventTypes.name,
	Events.storage_time,
	Events.outgoing,
	Events.remote_uid,
	Events.free_text
FROM EventTypes, Events
WHERE Events.event_type_id = EventTypes.id
%s
ORDER BY Events.id
""" % ("".join([" AND " + f for f in filter_clauses])), filter_args)

	print "* Voice/SMS activity filtered by %s:" % (", ".join(filter_descs))
	print "Date & Time (UTC)  Dir Phone #     Contents"
	print "-------------------------------------------"
	numcolors = ("red", "yellow", "green", "blue", "magenta")
	num2color = {} # dict: phone # -> color
	for event_type, timestamp, outgoing, phonenum, text in c:
		if event_type == "RTCOM_EL_EVENTTYPE_CALL":
			assert not text, "%s: '%s'" % (event_type, text)
			text = colorize("green", "<Voice call>")
		elif event_type == "RTCOM_EL_EVENTTYPE_CALL_MISSED":
			assert not text
			text = colorize("yellow", "<Missed voice call>")
		elif event_type == "RTCOM_EL_EVENTTYPE_SMS_MESSAGE":
			assert text
		else:
			text = colorize("red", "<Unknown event type: %s>" % (event_type) + (text or ""))
		t = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(timestamp))
		arrow = outgoing and colorize("green", "->") or colorize("red", "<-")
		numcolor = num2color.setdefault(phonenum, numcolors[len(num2color) % len(numcolors)])
		pnum = colorize(numcolor, phonenum.rjust(11))
		print "%19s %s %s %s" % (t, arrow, pnum, text)
	c.close()


if __name__ == '__main__':
	sys.exit(main(sys.argv))
