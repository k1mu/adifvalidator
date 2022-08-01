# adifvalidator
Amateur Data Interchange Format (ADIF) validator

This parser (adifparse.py) takes an ADIF file as input, validates the internal structure and validity, and exports a report for any errors in the input file. It can export reports for ADIF compliance (cases where the input file does not conform to proper ADIF) and ADIF consistency (cases where the file contains conflicting data - for example, US State and County not being in the same county.)

The default report contains a line-by-line report of each issue (compliance or consistency). You can also direct the compilance and consistency reports to separate files so they can be independently displayed.

For an example of how this works, see https://www.rickmurphy.net/adifvalidator.html


Command line arguments:
* '-f', '--file'		Required. Input File.
* '-a', '--compliance'		Output file for compliance report  (default:stdout)
* '-c', '--consistency'		Output file for consistency report (defaault:stdout)
* '-w', '--html'		If specified, output file is HTML-formatted
