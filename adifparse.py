#!/bin/python
# K1MU ADIF Parser
# Copyright (c) 2020,2022

from optparse import OptionParser
import os
import sys
from datetime import datetime

from adiftags import *

# States of the ADIF parsing machine
ADIF_STATE_BEGIN = 1
ADIF_STATE_GET_NAME = 2
ADIF_STATE_GET_SIZE = 3
ADIF_STATE_GET_TYPE = 4
ADIF_STATE_GET_DATA = 5
ADIF_STATE_GET_NEWLINE = 6
ADIF_STATE_CHECK = 7
ADIF_STATE_DONE = 8

def option_parsing():
	parser = OptionParser()

	parser.add_option('-f', '--file', dest='input_file', help='File to parse')
	parser.add_option('-a', '--compliance', dest='comp_file', help='Output file for compliance report')
	parser.add_option('-c', '--consistency', dest='cons_file', help='Output file for consistency report')
	parser.add_option('-w', '--html', dest='html', default=False, action="store_true", help='Output in HTML Format')

	(options, args) = parser.parse_args()

	return (options, args)

# Verify that the tag/value/type is sensible

def complianceError(msg, line):
	global compErrors
	global compFile
	global compString
	if not 'comp' in suppressions:
		if opts.html:	
			compFile.write("<h3>The following messages represent issues where the submitted ADIF file is not compliant with the ADIF standard.</h3>\n")
		else:
			compFile.write("The following messages represent issues where the submitted ADIF file is not compliant\nwith the ADIF standard.\n\n")
		suppressions['comp'] = True
	compString = compString + "ADIF Compliance error on line %d: %s" % (line, msg)
	if opts.html:
		compString = compString + "<br />"
	compString = compString + "\n"
	compErrors = compErrors + 1

def spewCompliance():
	global compString
	global qsoInfo
	global compFile

	if compString == "":
		return

	if qsoInfo != '':
		compFile.write (qsoInfo)
		if opts.html:
			compFile.write("<br />")
		compFile.write("\n")
	compFile.write(compString)
	compString = ""

def consistencyError(msg, line):
	global consErrors
	global consFile
	global qsoInfo
	if not 'cons' in suppressions:
		if opts.html:
			consFile.write("<h3>The following messages represent issues where the QSOs in the submitted ADIF file are compliant with the ADIF standard, but have inconsistent details such as invalid Country, Zones, etc. These findings do not indicate any structural issues with the submitted ADIF file, but they do indicate potentially incorrect records for the QSO being analyzed.</h3>\n")
		else:
			consFile.write("The following messages represent issues where the QSOs in the submitted ADIF file are compliant\nwith the ADIF standard, but have inconsistent details such as invalid Country, Zones, etc.\nThese findings do not indicate any structural issues with the submitted ADIF file,\nbut they do indicate potentially incorrect records for the QSO being analyzed.\n")
		suppressions['cons'] = True
	if qsoInfo != '':
		consFile.write (qsoInfo)
		if opts.html:
			consFile.write("<br />")
		consFile.write("\n")
	consFile.write("Consistency error on line %d: %s" % (line, msg))
	if opts.html:
		consFile.write("<br />")
	consFile.write("\n")
	qsoInfo = ''
	consErrors = consErrors + 1

def Info(msg):
	global infoMsg
	if opts.html:
		print("Informational: %s<br />" % msg)
	else:
		print("Informational: %s" % msg)
	infoMsg = infoMsg + 1

def hasValidCallSignChars(call):

	letters = 0
	numbers = 0
	for ch in call:
		if ch.isalpha():
			letters = letters + 1
		elif ch.isnumeric():
			numbers = numbers + 1
		elif ch != '/':
			return False
	# Need at least one letter
	if letters == 0:
		return False

	# Need at least one number
	if numbers == 0:
		return False
	# Invalid callsign patterns
	# Starting with 0, Q
	# 1x other than 1A, 1M, 1S
	first = call[0]
	second = call[1]
	if first == '0' or first == 'Q' or (first == 1 and second != 'A' and second != 'M' and second != 'S'):
		return False

	return True

def checkCallSign(call):
	if not hasValidCallSignChars(call):
		complianceError("'%s' is not an amateur callsign as it has unexpected characters" % (call), adifLine)
		return False
	if len(call) < 3:
		complianceError("'%s' is not an amateur callsign - it's too short" % (call) , adifLine)
		return False
	# No leading or trailing /
	if call[0] == '/' or call[-1:] == '/':
		complianceError("'%s' is not a plausible amateur callsign" % (call), adifLine)
		return False
	return True

def verifyTag(tag, value, len, type):
	value = value.upper()

	if len == '':
		len = 0
	else:
		if len.isnumeric():
			len = int(len)
		else:
			complianceError("length field '%s' is not numeric" % (len), adifLine)

	if not tag in qsoTags:			# Tag does not exist
		return
	tagType = qsoTags[tag]

	if type != '' and type != tagType:
		complianceError("tag '%s' specifies type '%s' but is expected to be '%s'" % (tag, type, tagType), adifLine)
	if tagType == 'B':			# Boolean
		if value != 'Y' and value != 'N':
			complianceError ("tag '%s' should be 'Y' or ''N but is '%s'" % (tag, value), adifLine)
		return
	if tagType == 'N' or tagType == 'P':			# Number
		if not value.isnumeric():
			try:
				number = float(value)
			except ValueError:
				complianceError ("tag '%s' should be a number but is '%s'" % (tag, value), adifLine)
				return
		else:
			number = int(value)
		if tag in ranges:
			low = ranges[tag][0]
			high = ranges[tag][1]
			if int(number) < low or int(number) > high:
				complianceError("tag '%s' should be in the range %d to %d but is %s" % (tag, low, high, value), adifLine)
				return
		if tagType == 'P':
			if not int(number) > 0:
				complianceError("tag '%s' should be a positive number but has '%s'" % (tag, value), adifLine)
				return
			nbr = int(value)
			if not nbr > 0:
				complianceErrror("[ERROR] Line %d: tag '%s' should be a positive number but has '%s'" % (adifLine, tag, value))
				return
		return

	if tagType == 'D':			# Date
		if len != 8:
			complianceError ("'%s' should be a date but is %d characters long, not 8" % (tag, len), adifLine)
		if value[:4] < '1900' or value[:4] > '2100':
			complianceError ("tag '%s' should be a date but '%s' has an invalid year" % (tag, value), adifLine)
		if value[4:6] < '01' or value [4:6] > '12':
			complianceError ("tag '%s' value '%s' should be a date but has an invalid month '%s'" % (tag, value, value[4:5]), adifLine)
		if value[6:8] < '01' or value [6:8] > '31':
			complianceError ("tag '%s' value '%s' should be a date but has invalid day" % (tag, value), adifLine)
		return

	if tagType == 'T':			# Time
		if not value.isnumeric():
			complianceError ("tag '%s' should be a time but'%s' is not numeric" % (tag, value), tagLine)

		if len != 4 and len != 6:
			complianceError ("tag '%s' should be a time but it is %d characters long not 4 or 6" % (tag, len), adifLine)
		return

	if tagType == 'S' or tagType == 'M':
		return

	if tagType == 'L':			# Location "XDDD MM.MMM format"
		if len != 11:
			complianceError ("tag '%s' should be 11 characters long but is %d" % (tag, len), adifLine)
		nsew = value[:1]
		if nsew not in [ 'N', 'S', 'E', 'W' ]:
			complianceError("Location '%s' value '%s' does not start with N,S,E, or W." % (tag, value), adifLine)
		deg = value[1:4]
		if not deg.isnumeric():
			complianceError ("Location '%s' value '%s' degrees is not numeric" % (tag, value), adifLine)
		else:
			intdeg = int(deg)
			if intdeg < 0 or intdeg > 180:
				complianceError ("Location '%s' value '%s' degrees is not in range 0 through 180" % (tag, value), adifLine)
		mins = value[5:7]
		if not mins.isnumeric():
			complianceError("Location '%s' value '%s' minutes is not numeric" % (tag, value), adifLine)
		else:
			intmins = int(mins)
			if intmins < 0 or intmins > 59:
				complianceError ("Location '%s' value '%s' minutes is not in range 0 through 59" % (tag, value), adifLine)
		secs = value[8:11]
		if not secs.isnumeric():
			complianceError ("Location '%s' value '%s' seconds is not numeric" % (tag, value), adifLine)
		else:
			intsecs = int(secs)
			if intsecs < 0 or intsecs > 999:
				complianceError ("Location '%s' value '%s' seconds is not in range 0 through 999" % (tag, value), adifLine)
		return

	if tagType == 'E':		# enumeration
		if not enumerations[tag]:
			complianceError("tag '%s' does not have any enumerations - internal error!" % (tag), adifLine)
			return

		if len > 0 and value not in enumerations[tag]:
			complianceError("The tag '%s' has an invalid value '%s' - not in the enumerations" % (tag, value), adifLine)
		return

	if len > 0 and tagType == 'R':		# Internal IOTA
		if len != 6:
			complianceError ("'%s' value '%s' is not 6 characters" % (tag, value), adifLine)
		cont = value[0:2]
		if cont not in [ 'NA', 'SA', 'EU', 'AF', 'OC', 'AS', 'AN' ]:
			complianceError ("'%s' value '%s' isn't a valid continent" % (tag, value), adifLine)
		if value[2:3] != '-':
			complianceError ("'%s' value '%s' does not have a hyphen" % (tag, value), adifLine)
		if not value[3:7].isnumeric():
			complianceError ("'%s' value '%s' does not have a number after the hyphen" % (tag, value), adifLine)
		return

	if tagType == 'R':		# empty
		return

	if tagType == 'C':		# Internal Callsign
		checkCallSign(value)
		return

	complianceError("Internal failure to handle tag '%s' type '%s'" % (tag, tagType), adifLine)
	return

def verifyGrid(adifLine, grid):
	grid = grid.upper()
	if len(grid) < 4:
		complianceError("'%s' is an invalid gridsquare" % (grid), adifLine)
		return False
	if grid[1] < 'A' or grid[1] > 'R':
		complianceError("'%s' is an invalid gridsquare" % (grid), adifLine)
		return False
	if grid[2] < '0' or grid[2] > '9':
		complianceError("'%s' is an invalid gridsquare" % (grid), adifLine)
		return False
	if grid[3] < '0' or grid[3] > '9':
		complianceError("'%s' is an invalid gridsquare" % (grid), adifLine)
		return False
	if len(grid) > 4 and (grid[4] < 'Z' and grid[4] > 'X'):
		complianceError("'%s' is an invalid gridsquare (subsquare)" % (grid), adifLine)
		return False
	if len(grid) > 5 and (grid[5] < 'Z' and grid[4] > 'X'):
		complianceError("'%s' is an invalid gridsquare (subsquare)" % (grid), adifLine)
		return False
	if len(grid) == 4 or len(grid) >= 6:
		return True
	else:
		return False

def getTag(tagName):
	if tagName in tagLines:
		tagLine = tagLines[tagName]
	else:
		tagLine = adifLine
	if tagName in qso:
		val = qso[tagName].strip().upper().strip()
		if val != '':
			return (True, val, tagLine)
	return (False, '', adifLine)

def entityName(ent):
	if ent not in enumerations['DXCC']:
		return "INVALID ENTITY NUMBER"
	return enumerations['DXCC'][ent]['name']

def getDate(isodate):
	dt = datetime.strptime(isodate, "%Y-%m-%d %H:%M:%S")
	return datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)

def fixCounty(cnty):
# Normalize the county
	cnty = cnty.upper().strip()
	# remove spaces
	cnty = cnty.replace(' ', '')
	# remove hyphens
	cnty = cnty.replace('-', '')
	# change "St." and "Ste." to full spelling
	cnty = cnty.replace('ST.', 'SAINT')
	cnty = cnty.replace('STE.', 'SAINTE')
	# Remove LoTW cruft
	cnty = cnty.replace('BOROUGH', '')
	cnty = cnty.replace('CENSUSAREA', '')
	cnty = cnty.replace('MUNICIPALITY', '')
	cnty = cnty.replace('CITYANDBOROUGH', '')
	return cnty

def verifyCounty(tag, adifLine, dxcc, state, cnty):
	origcnty = cnty
	cnty = fixCounty(cnty)
	# 
	# US CNTY is "ST,COUNTY" form - check that
	#
	try:
		(st, ct) = cnty.split(',')
	except ValueError:		# No comma
		st = ''
		ct = cnty
	cnty = ct

	if st != '' and st != state:
		consistencyError("%s value of '%s' specifies state '%s' but the STATE is set to '%s'" % (tag, origcnty, st, state), adifLine)
	#
	# Now, try a lookup
	#
	if not state in sas or not cnty in sas[state]:
		consistencyError("%s value of '%s' is not valid for DXCC %s (%s) and STATE '%s'" % (tag, cnty, dxcc, entityName(dxcc), state), adifLine)
	return

def makeQSOinfo():
	global qsoInfo
	qsoInfo = ''
	(ok, call, tl) = getTag('CALL')
	if ok:
		if opts.html:
			qsoInfo = '\n<br /><b>For the QSO with ' + call
		else:
			qsoInfo = '\nFor the QSO with ' + call

	(ok, qso_date, tl) = getTag('QSO_DATE')
	if ok:
		if len(qso_date) == 8:
			qso_date = qso_date[:4] + '-' + qso_date[4:6] + '-' + qso_date[6:8]

		if qsoInfo != '':
			qsoInfo = qsoInfo + ' on '
		else:
			if opts.html:
				qsoInfo = '\n<br /><b>For the qso on '
			else:
				qsoInfo = '\nFor the qso on '
		qsoInfo = qsoInfo + qso_date

	(ok, band, tl) = getTag('BAND')
	if ok:
		if qsoInfo != '':
			qsoInfo = qsoInfo + ' '
		qsoInfo = qsoInfo + band
	else:
		(ok, freq, tl) = getTag('FREQ')
		if ok:
			if qsoInfo != '':
				qsoInfo = qsoInfo + ' '
			qsoInfo = qsoInfo + freq

	(ok, mode, tl) = getTag('MODE')
	if ok:
		if qsoInfo != '':
			qsoInfo = qsoInfo + ' '
		qsoInfo = qsoInfo + mode
	qsoInfo = qsoInfo + ':'
	if opts.html:
		qsoInfo = qsoInfo + "</b>"
	return
#
# Check the QSO for validity.
#
def verifyQSO():

	makeQSOinfo()
	spewCompliance()
	err = 0
#
# Grids look good?
#
	(ok, grid, tl) = getTag('GRIDSQUARE')

	if ok:
		if not verifyGrid(tl, grid):
			err + err + 1

	(ok, my_gridsquare, tl) = getTag('MYGRIDSQUARE')
	if ok:
		if not verifyGrid(tl, my_gridsquare):
			err + err + 1

	(ok, vucc_grids, tl) = getTag('VUCC_GRIDS')
	if ok:
		grids = vucc_grids.split(',')
		for grid in grids:
			if not verifyGrid(tl, grid):
				err = err + 1

	(ok, my_vucc_grids, tl) = getTag('MY_VUCC_GRIDS')
	if ok:
		grids = my_vucc_grids.split(',')
		for grid in grids:
			if not verifyGrid(tl, grid):
				err = err + 1
#
# Band was already checked to be "correct" so don't need to re-report
#
	freqs = []
	(bandok, band, band_tl) = getTag('BAND')
	if band not in enumerations['BAND']:
		bandok = False
	if bandok:
		freqs = enumerations['BAND'][band.upper()]
		low = float(freqs[0])
		high = float(freqs[1])

	(freqok, freq, freq_tl) = getTag('FREQ')
	if freqok:
		if not freq.isnumeric():
			try:
				mhz = float(freq)
			except ValueError:
				freqok = False
		else:
			mhz = int(freq)
		if bandok and freqok and (mhz < low or mhz > high):		# the list has low/hign range
			consistencyError("Frequency '%s' is out of range for band '%s'" % (freq, band), freq_tl)
			freq_ok = False

	if not bandok and not freqok:
		consistencyError("QSO does not have a band or a frequency specified", adifLine)

	(band_rx_ok, band_rx, band_tl) = getTag('BAND_RX')
	if band_rx_ok:
		freqs_rx = enumerations['BAND_RX'][band.upper()]
		low_rx = float(freqs_rx[0])
		high_rx = float(freqs_rx[1])
	(freq_rx_ok, freq_rx, freq_tl) = getTag('FREQ_RX')
	if freq_rx_ok:
		if not freq_rx.isnumeric():
			try:
				mhz_rx = float(freq_rx)
			except ValueError:
				freq_rx_ok = False
		else:
			mhz_rx = int(freq_rx)
		if freq_rx_ok and band_rx_ok and (mhz_rx < low_rx or mhz_rx > high_rx):		# the list has low/hign range
			consistencyError("RX Frequency '%s' is out of range for band '%s'" % (freq, band), freq_tl)
#
# Is the DXCC and Country OK?
#
	(dxccok, dxcc, dxcc_tl) = getTag('DXCC')
	(countryok, country, cty_tl) = getTag('COUNTRY')
	if countryok:
		country = country.upper()
		if country in entityMap:
			countrydxcc = entityMap[country]
		else:
			countryok = False

	if dxccok and countryok:
		if countrydxcc != dxcc:
			consistencyError("The COUNTRY is for DXCC entity %s (%s) but the DXCC tag has %s (%s)" % (countrydxcc, entityName(countrydxcc), dxcc, entityName(dxcc)), cty_Tl)

	if dxccok and dxcc not in enumerations['DXCC']:
		dxccok = False
#
# Use DXCC entity from the country if not already set
#
	if countryok and not dxccok:
		dxcc = countrydxcc
		dxccok = True

# 
# Repeat for MY_DXCC
#
	(my_dxccok, my_dxcc, my_dxcc_tl) = getTag('MY_DXCC')
	(my_countryok, my_country, my_cty_tl) = getTag('MY_COUNTRY')
	if my_countryok:
		my_country = my_country.upper()
		if my_country in entityMap:
			my_countrydxcc = entityMap[my_country]
		else:
			my_countryok = False

	if my_dxccok and my_dxcc not in enumerations['DXCC']:
		my_dxccok = False

	if my_dxccok and my_countryok:
		if my_countrydxcc != my_dxcc:
			consistencyError ("The MY_COUNTRY is for DXCC entity %s (%s) but the DXCC tag says %s (%s)" % (my_countrydxcc, entityName(my_countrydxcc), dxcc, entityName(my_dxcc)), my_cty_tl)
#
# Use DXCC entity from the country if not already set
#
	if my_countryok and not my_dxccok:
		my_dxcc = my_countrydxcc
		my_dxccok = True
#
# Check the state
#
	(stateok, state, state_tl) = getTag('STATE')
	if stateok:
		if not dxccok:
			if state == 'HI':	# OK, it's Hawaii
				consistencyError ("The QSO contains STATE '%s' but the QSO record has no valid DXCC entity - assuming HAWAII"  % (state), state_tl)
				dxccok = True
				dxcc = "110"
			elif state == 'AK':	# Or Alaska
				consistencyError ("The QSO contains STATE '%s' but the QSO record has no valid DXCC entity - assuming ALASKA"  % (state), state_tl)
				dxccok = True
				dxcc = "6"
			else:
				consistencyError ("The QSO contains STATE '%s' but the QSO record has no valid DXCC entity"  % (state), state_tl)
		elif not dxcc in pas:		# Does this DXCC entity have a primary admin subdivision?
			consistencyError ("DXCC Entity %s (%s) does not have a primary adminstrative subdivision but the QSO contains STATE '%s'" % (dxcc, entityName(dxcc), state), state_tl)
			stateok = False
		else:
			if state not in pas[dxcc]:
				consistencyError ("State '%s' is not valid for DXCC %s (%s)" % (state, dxcc, entityName(dxcc)), state_tl)
				stateok = False

	(my_stateok, my_state, my_state_tl) = getTag('MY_STATE')
	if my_stateok:
		if not my_dxccok:
			if my_state == 'HI':	# OK, it's Hawaii
				consistencyError ("The QSO contains MY_STATE '%s' but the QSO record has no valid DXCC entity - assuming HAWAII"  % (my_state), my_state_tl)
				my_dxccok = True
				my_dxcc = "110"
			elif my_state == 'AK':	# Or Alaska
				consistencyError("The QSO contains MY_STATE '%s' but the QSO record has no valid DXCC entity - assuming ALASKA"  % (my_state), my_state_tl)
				my_dxccok = True
				my_dxcc = "6"
			else:
				consistencyError("The QSO contains MY_STATE '%s' but the QSO record has no valid DXCC entity"  % (my_state), my_state_tl)
		elif not my_dxcc in pas:		# Does this DXCC entity have a primary admin subdivision?
			consistencyError ("DXCC Entity %s (%s) does not have a primary adminstrative subdivision but the QSO contains MY_STATE '%s'" % (my_dxcc, entityName(my_dxcc), my_state), my_state_tl)
			my_stateok = False
		else:
			if my_state not in pas[my_dxcc]:
				consistencyError ("MY_STATE '%s' is not valid for DXCC %s (%s)" % (my_state, my_dxcc, entityName(my_dxcc)), my_state_tl)
				my_stateok = False

	(mode_ok, mode, mode_tl) = getTag('MODE')

	submodes = []
	if not mode_ok:
		consistencyError("QSO does not have a MODE" % (qsoInfo), mode_tl)
	else:
		if mode not in enumerations['MODE']:
			complianceError("'%s' is not a valid MODE" % (mode), mode_tl)
			mode_ok = False
		else:
			submodes = enumerations['MODE'][mode]

	(ok, submode, tl) = getTag('SUBMODE')
	if ok:
		if not mode_ok:
			complianceError("SUBMODE '%s' without a valid MODE" % (submode), tl)
		else:
			if submode not in submodes:
				complianceError("'%s' is not a valid SUBMODE for MODE '%s'" % (submode, mode), tl)
#
# Try to validate COUNTY
#
	(ok, cnty, tl) = getTag('CNTY')

	if ok and stateok:
		verifyCounty('CNTY', tl, dxcc, state, cnty)
#
# Try to validate MY_COUNTY
#
	(ok, my_cnty, tl) = getTag('MY_CNTY')

	if ok and my_stateok:
		verifyCounty('MY_CNTY', tl, my_dxcc, my_state, my_cnty)
#
# Validate USACA_COUNTIES
#
	(ok, usaca, tl) = getTag('USACA_COUNTIES')

	if ok and stateok:
		for cnty in usaca.split(':'):
			verifyCounty('USACA_COUNTIES', tl, dxcc, state, cnty)

	(ok, my_usaca, tl) = getTag('MY_USACA_COUNTIES')

	if ok and my_stateok:
		for my_cnty in my_usaca.split(':'):
			verifyCounty('MY_USACA_COUNTIES', tl, my_dxcc, my_state, my_cnty)
#
# Verify zones
#
	if dxccok and int(dxcc) > 0:
		(cqok, cqz, cqz_tl) = getTag('CQZ')
		(ituok, ituz, ituz_tl) = getTag('ITUZ')
		if ituok:
			ituz = int(ituz)
			zmapsrc = 'DXCC entity'
			zonemap = enumerations['DXCC'][dxcc]['zonemap']
			zmapkey = entityName(dxcc)
			if stateok:
				if pas[dxcc][state]:
					zonemap = pas[dxcc][state]
					zmapsrc = 'STATE'
					zmapkey = state
			ok = False
			for ent in zonemap:
				(itu, cq) = ent.split(':')
				if int(itu) == ituz:
					ok = True
					break
			if not ok:
				consistencyError("ITU Zone '%s' is not correct for the %s '%s'" % (ituz, zmapsrc, zmapkey), ituz_tl)	

		if cqok:
			cqz = int(cqz)
			zmapsrc = 'DXCC entity'
			zonemap = enumerations['DXCC'][dxcc]['zonemap']
			zmapkey = entityName(dxcc)
			if stateok:
				if pas[dxcc][state]:
					zonemap = pas[dxcc][state]
					zmapsrc = 'STATE'
					zmapkey = state
			ok = False
			for ent in zonemap:
				(itu, cq) = ent.split(':')
				if int(cq) == cqz:
					ok = True
					break
			if not ok:
				consistencyError("CQ Zone '%s' is not correct for the %s '%s'" % (cqz, zmapsrc, zmapkey), cqz_tl)

	if my_dxccok and int(my_dxcc) > 0:
		(cqok, cqz, cqz_tl) = getTag('MY_CQZ')
		(ituok, ituz, ituz_tl) = getTag('MY_ITUZ')
		if ituok:
			zmapsrc = 'DXCC entity'
			zonemap = enumerations['DXCC'][my_dxcc]['zonemap']
			zmapkey = entityName(my_dxcc)
			if my_stateok:
				if pas[my_dxcc][my_state]:
					zonemap = pas[my_dxcc][my_state]
					zmapsrc = 'STATE'
					zmapkey = my_state
			ok = False
			for ent in zonemap:
				(itu, cq) = ent.split(':')
				if itu == ituz:
					ok = True
					break
			if not ok:
				consistencyError("MY_ITUZ Zone '%s' is not correct for the %s '%s'" % (ituz, zmapsrc, zmapkey), ituz_tl)
		if cqok:
			zmapsrc = 'DXCC entity'
			zonemap = enumerations['DXCC'][my_dxcc]['zonemap']
			if my_stateok:
				if pas[my_dxcc][my_state]:
					zonemap = pas[my_dxcc][my_state]
					zmapsrc = 'STATE'
			ok = False
			for ent in zonemap:
				(itu, cq) = ent.split(':')
				if cq == cqz:
					ok = True
					break
			if not ok:
				consistencyError("MY_CQZ Zone '%s' is not correct for the %s '%s'" % (cqz, zmapsrc, zmapkey), cqz_tl)	
#
# Do we have the basics for a valid QSO? Date, time, mode? (Band/freq already checked)
#
	(date_ok, qso_date, tl) = getTag('QSO_DATE')
	if date_ok:
		if len(qso_date) != 8 or not qso_date.isnumeric():
			date_ok = False

	if not date_ok:
		consistencyError("QSO does not have a valid date", tl)

	(time_ok, qso_time, tl) = getTag('TIME_ON')
	if not time_ok:
		consistencyError("QSO does not have a valid time", tl)
#
# TIME_ON after TIME_OFF?
#
	(date_off_ok, qso_date_off, tl) = getTag('QSO_DATE_OFF')
	if not date_off_ok:
		if date_ok:
			qso_date_off = qso_date
		else:
			qso_date = ''
			qso_date_off = ''
	(time_off_ok, qso_time_off, tl) = getTag('TIME_OFF')

	if time_off_ok:
		if not time_ok:
			consistencyError("QSO has a TIME_OFF but no TIME_ON", tl)
		qstart = qso_date + qso_time
		qend = qso_date_off + qso_time_off
		if qstart > qend:	# Started after it began?
			consistencyError("QSO TIME_OFF is %s/%s, which is before the QSO TIME_ON of %s/%s" % (qso_date_off, qso_time_off, qso_date, qso_time), tl)

	if not mode_ok:
		consistencyError("QSO does not have a valid mode", tl)
#
# Is the QSO in range of valid dates for the entity?
#
	isodate = qso_date[:4] + '-' + qso_date[4:6] + '-' + qso_date [6:8] + ' 00:00:00'
	qdate = getDate(isodate)
	if dxccok and 'valid' in enumerations['DXCC'][dxcc]:
		start = getDate(enumerations['DXCC'][dxcc]['valid'])
		if qdate < start:
			consistencyError("QSO Date of '%s' is before the valid dates for dxcc %s (%s)" % (qso_date, dxcc, entityName(dxcc)), tl)
	if dxccok and 'invalid' in enumerations['DXCC'][dxcc]:
		end = getDate(enumerations['DXCC'][dxcc]['invalid'])
		if qdate > end:
			consistencyError("QSO Date of '%s' is after the valid dates for dxcc %s (%s)" % (qso_date, dxcc, entityName(dxcc)), tl)
	if my_dxccok and (my_dxcc != dxcc):
		if 'valid' in enumerations['DXCC'][my_dxcc]:
			start = getDate(enumerations['DXCC'][my_dxcc]['valid'])
			if qdate < start:
				consistencyError("QSO Date of '%s' is before the valid dates for dxcc %s (%s)" % (qso_date, my_dxcc, entityName(my_dxcc)),  tl)
		if 'invalid' in enumerations['DXCC'][my_dxcc]:
			end = getDate(enumerations['DXCC'][my_dxcc]['invalid'])
			if qdate > end:
				consistencyError("QSO Date of '%s' is after the valid dates for dxcc %s (%s)" % (qso_date, my_dxcc, entityName(my_dxcc)), tl)

#
# that's all, folks.
#
	return

def getByte(file, adifState, adifTag):
	global nonASCII

	byte = file.read(1)
	if not byte:
		return None
	try:
		inChar = byte.decode('utf-8')
	except UnicodeDecodeError:
		if adifState != ADIF_STATE_BEGIN:
			if nonASCII != adifLine:
				if adifTag != '':
					complianceError("Non-ASCII character in input file, tag %s" %adifTag, adifLine)
				else:
					complianceError("Non-ASCII character in input file", adifLine)
				nonASCII = adifLine
		inChar = ' '
	if ord(inChar) > 128:
		if adifState != ADIF_STATE_BEGIN:
			if nonASCII != adifLine:
				if adifTag != '':
					complianceError("Non-ASCII character %s in input file, tag %s" % (inChar, adifTag), adifLine)
				else:
					complianceError ("Non-ASCII character '%s' in input file" % (inChar), adifLine)
			nonASCII = adifLine
	return inChar

def setTagInQSO(qso, tag, value, line, hdr):
	if tag in qso:
		if hdr:
			complianceError("tag '%s' appears more than once in the header, replacing old value %s with new value %s" % (tag, qso[tag], value), line)
		else:
			complianceError("tag '%s' appears more than once in a record, replacing old value %s with new value %s" % (tag, qso[tag], value), line)
	qso[tag] = value

def main():
	global opts
	global entityMap
	global tagLines
	global qso
	global adifLine
	global compErrors
	global compString
	global consErrors
	global infoMsg
	global suppressions

	opts,args = option_parsing()

	inHeader = True
	qso = {}
	tagLines = {}
	userTags = {}
	qsos = 0
	compErrors = 0
	consErrors = 0
	compString = ""
	infoMsg = 0
	suppressions = {}

	entityMap = {}
	for key in enumerations['DXCC']:
		entity = enumerations['DXCC'][key]
		entityMap[entity['name']] = key

	#
	# Add some common mistakes
	#
	entityMap['UNITED STATES'] = '291'
	entityMap['GERMANY'] = '230'

	if not opts.input_file:
		print ("[ERROR] you must specify an input file with -f")
		sys.exit(1)

	global compFile
	global consFile
	if opts.comp_file:
		compFile = open(opts.comp_file, 'w')
	else:
		compFile = sys.stdout

	if opts.cons_file:
		consFile  = open(opts.cons_file, 'w')
	else:
		consFile = sys.stdout


	with open(opts.input_file, 'rb') as adif:
		inChar = getByte(adif, ADIF_STATE_BEGIN, '')
		if not inChar:
			print("[ERROR] empty file?")
			sys.exit(1)

		# if there's a '<' in the first byte, there is no header
		if inChar == '<':
			adif.seek(-1, os.SEEK_CUR) # push that back
			Info("This ADIF file has no header")
			inHeader = False

		# Reset everything
		adifTag = ''
		adifValue = ''
		adifLen = 0
		adifSize = '' 
		adifType = ''
		adifState = ADIF_STATE_BEGIN
		adifLine = 1
		badLen = 0

		while adifState != ADIF_STATE_DONE:
			if adifState == ADIF_STATE_CHECK:
				# Ignore app-specific tags
				if adifTag[:4] == 'APP_':
					# reset for next round
					adifTag = ''
					adifValue = ''
					adifLen = 0
					adifSize = '' 
					adifType = ''
					adifState = ADIF_STATE_BEGIN
					continue

				# Handle userdefs

				if adifTag[:7] == 'USERDEF':
                                    userNum = adifTag[7:]
                                    if userNum.isnumeric():
                                        adifTag = "USERDEF"
                                        userTags[adifValue] = adifType

				if adifTag != 'EOH':
					verifyTag(adifTag, adifValue, adifSize, adifType)

				if not adifTag in qso:
					setTagInQSO(qso, adifTag, adifValue, adifLine, inHeader)

				tagLines[adifTag] = adifLine
				if inHeader:
					if adifTag == 'EOH':
						inHeader = False
						qso = {}
						tagLines = {}
					if not adifTag in headerTags:
						complianceError("tag '%s' is not a valid tag in the header" % (adifTag), adifLine)
					if adifTag == 'EOR':
						complianceError("Got <EOR> tag while processing header", adifLine)
				else:
					if not adifTag in qsoTags and not adifTag in userTags:
						complianceError ("tag '%s' (%s) is not a valid tag in a QSO record" % (adifTag, adifValue), adifLine)

					if adifTag == 'EOH':
						complianceError ("Got  EOH tag while not in the header", adifLine)
				if adifTag == 'EOR':
					# handle QSO here
					verifyQSO()
					qso = {}
					qsos = qsos + 1
				# reset for next round
				adifTag = ''
				adifValue = ''
				adifLen = 0
				adifSize = '' 
				adifType = ''
				adifState = ADIF_STATE_BEGIN
				continue

			inChar = getByte(adif, adifState, adifTag)
			if not inChar:			# EOF
				break

			if adifState != ADIF_STATE_GET_DATA and adifState != ADIF_STATE_GET_NEWLINE:
				if inChar == '\n':
					global nonASCII
					nonASCII = -1
					adifLine = adifLine + 1
					continue
				if inChar == '\r':		# ignore CR
					continue
			# Begin state - just keep reading until you get a '<'.
			if adifState == ADIF_STATE_BEGIN:
				if '<' == inChar:		# start of a tag
					adifState = ADIF_STATE_GET_NAME
				continue

			# Get the tag name - add chars until '>' or ':' found
			elif adifState == ADIF_STATE_GET_NAME:
				if ':' == inChar or '>' == inChar:		# end of tag
					adifState = ADIF_STATE_GET_SIZE
					if inChar == '>':			# end of tag, no size
						adifState = ADIF_STATE_CHECK
						continue
				else:
					adifTag = adifTag + inChar.upper()
					adifLen = 0
				continue

			elif adifState == ADIF_STATE_GET_SIZE:
				if ':' == inChar or '>' == inChar:		# end of size
					if ':' == inChar:
						adifState = ADIF_STATE_GET_TYPE
					else:
						adifState = ADIF_STATE_GET_DATA
				else:
					adifSize = adifSize + inChar
					if adifSize.isnumeric():
						adifLen = int(adifSize)
						badLen = 0
					else:
						complianceError("Length field '%s' is not numeric" % (adifSize), adifLine)
						badLen = badLen + 1
						if badLen > 500:
							sys.exit(1)
				continue

			elif adifState == ADIF_STATE_GET_TYPE:
				if '>' == inChar:						# no explicit type
					adifState = ADIF_STATE_GET_DATA
					if adifType != '' and adifType not in dataTypes:
						complianceError("Data Type '%s' is not valid" % (adifType), adifLine)
				else:
					adifType = adifType + inChar.upper()
				continue

			elif adifState == ADIF_STATE_GET_DATA:
				if adifLen == 0:
					setTagInQSO(qso, adifTag, adifValue, adifLine, inHeader)
					tagLines[adifTag] = adifLine
					adifState = ADIF_STATE_CHECK
				else:
					adifValue = adifValue + inChar
					adifLen = adifLen - 1
					if inChar == '\n':
						nonASCII = -1
						adifLine = adifLine + 1
						complianceError("Newline in data string for %s did not have preceding Return" % (adifTag), adifLine);
					if inChar == '\r':
						adifState = ADIF_STATE_GET_NEWLINE
					if adifLen == 0:
						setTagInQSO(qso, adifTag, adifValue, adifLine, inHeader)
						tagLines[adifTag] = adifLine
						adifState = ADIF_STATE_CHECK
				continue

			elif adifState == ADIF_STATE_GET_NEWLINE:
				adifValue = adifValue + inChar
				adifLen = adifLen - 1
				if inChar != '\n':
					complianceError("Return in data string for %s did not have following Newline" % (adifTag), adifLine);
				nonASCII = -1
				adifLine = adifLine + 1
				if adifLen == 0:
					setTagInQSO(qso, adifTag, adifValue, adifLine, inHeader)
					tagLines[adifTag] = adifLine
					adifState = ADIF_STATE_CHECK
				else:
					adifState = ADIF_STATE_GET_DATA
				continue

	adif.close()
	if opts.cons_file:
		consFile.close()
	if opts.comp_file:
		compFile.close()
	Info ("Handled %d lines, %d QSOs, Errors: %d " % (adifLine, qsos, compErrors + consErrors))


if __name__ == '__main__':
	main()
