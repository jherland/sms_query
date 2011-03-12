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

import sys
import sqlite3
import time


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


def processPhoneNum (phonenum):
	ret = [phonenum]
	if phonenum.startswith("+47"):
		ret.append(phonenum[3:])
	else:
		ret.append("+47" + phonenum)
	return ret


def main (args = []):
	phonenum = args[1]
	phonenums = processPhoneNum(phonenum)
	conn = sqlite3.connect(DbFilename)
	c = conn.cursor()
	c.execute("SELECT storage_time, outgoing, free_text FROM Events WHERE %s ORDER BY id" % (" OR ".join(["remote_uid=?" for n in phonenums])), phonenums)
	print "* SMS messages to/from phone number %s:" % (phonenum)
	print "Date & Time (UTC)  Dir Contents"
	print "-------------------------------"
	for timestamp, outgoing, text in c:
		t = time.gmtime(timestamp)
		color = outgoing and "green" or "red"
		output = "%-19s %2s %s" % (time.strftime("%Y-%m-%d %H:%M:%S", t), outgoing and "->" or "<-", text)
		print colorize(color, output)
	c.close()


if __name__ == '__main__':
	sys.exit(main(sys.argv))
