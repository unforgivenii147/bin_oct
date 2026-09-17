#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import contextlib
import datetime
import json
import sys
from argparse import ArgumentParser
from pathlib import Path

import requests
from pygments import highlight
from pygments.formatters import TerminalFormatter
from pygments.lexers import JsonLexer

IDN = True
try:
    import idna
except:
    IDN = False
VERSION = "0.1.0"
MYNAME = sys.argv[0].replace("./", "")
RC_FILE_LOCS = [
    ".bestwhoisrc",
    Path("~/.bestwhoisrc").expanduser(),
    "data/data/com.termux/files/usr/etc/bestwhois/bestwhoisrc",
]


def valid_date(s):
    try:
        _ = datetime.datetime.strptime(s, "%Y-%m-%d")
        return s
    except ValueError:
        msg = f"Not a valid date: '{s}'."
        raise argparse.ArgumentTypeError(msg)


def dictstr(structure, ntabs: int) -> None:
    global raw_str
    for field in structure:
        tabs = ""
        for _ in range(ntabs):
            tabs += "\t"
        if isinstance(structure[field], list):
            raw_str += f"{tabs}{field}: "
            comma = ""
            for item in structure[field]:
                raw_str += f"{comma}{item}"
                comma = ", "
            raw_str += "\n"
        elif isinstance(structure[field], dict):
            raw_str += f"{tabs}{field}: \n"
            dictstr(structure[field], ntabs + 1)
        else:
            raw_str += f"{tabs}{field}: {structure[field]}\n"


def is_empty_field(field):
    return field is None or field == "" or field == {} or field == []


def purge_empty_fields(structure):
    for field in structure.copy():
        if isinstance(structure[field], dict):
            structure[field] = purge_empty_fields(structure[field])
        if is_empty_field(structure[field]):
            structure.pop(field)
    return structure


ARGS_PARSER = ArgumentParser(
    description="Command-line utility to query domains in the WhoisXML API WHOIS service similarly to the whois command.",
    prog=MYNAME,
)
ARGS_PARSER.add_argument(
    "domainName",
    type=str,
    help="The domain to be queried. Domains with national characters can be Unicode or IDN.",
)
ARGS_PARSER.add_argument(
    "--version",
    help="Print version information and exit.",
    action="version",
    version=MYNAME
    + " ver. "
    + VERSION
    + """
(c) WhoisXML API Inc.""",
)
ARGS_PARSER.add_argument(
    "--rcfile",
    type=str,
    help="Use this rc file. Will override all default ini locations.",
)
ARGS_PARSER.add_argument(
    "--apikey", type=str, help="Directly specify the API key. Overrides any ini file."
)
ARGS_PARSER.add_argument(
    "--nocolor",
    action="store_true",
    help="Do not colorize output. Useful in scripts. Colors are not supported on Windows, so there it is default.",
)
ARGS_PARSER.add_argument(
    "--text",
    action="store_true",
    help="Print a textual output instead of a JSON-style format.  Results in a behavior similar to the whois command.",
)
ARGS_PARSER.add_argument(
    "--fullrawtext",
    action="store_true",
    help="Print all raw text field contents. The default is to suppress raw texts fully.",
)
ARGS_PARSER.add_argument(
    "--strippedrawtext",
    action="store_true",
    help="Print the first 128 characters of raw text fields. The default is to suppress raw texts fully.",
)
ARGS_PARSER.add_argument(
    "--keep-empty",
    action="store_true",
    help="Keep and display fields with empty and null values",
)
ARGS_PARSER.add_argument(
    "--history",
    action="store_true",
    help="Get historic records from the history API. The following option imply this automatically.",
)
ARGS_PARSER.add_argument(
    "--since-date",
    help="(history) If present, search through activities discovered since the given date. Sometimes there is a latency between the actual added/renewal/expired date and the date when our system detected this change. We recommend using this field in your monitoring tools for filtering daily changes.",
    metavar="YYYY-MM-DD",
    type=valid_date,
)
ARGS_PARSER.add_argument(
    "--created-date-from",
    help="(history) If present, search through domains created after the given date.",
    metavar="YYYY-MM-DD",
    type=valid_date,
)
ARGS_PARSER.add_argument(
    "--created-date-to",
    help="(history) If present, search through domains created before the given date.",
    metavar="YYYY-MM-DD",
    type=valid_date,
)
ARGS_PARSER.add_argument(
    "--updated-date-from",
    help="(history) If present, search through domains updated after the given date.",
    metavar="YYYY-MM-DD",
    type=valid_date,
)
ARGS_PARSER.add_argument(
    "--updated-date-to",
    help="(history) If present, search through domains updated before the given date.",
    metavar="YYYY-MM-DD",
    type=valid_date,
)
ARGS_PARSER.add_argument(
    "--expired-date-from",
    help="(history) If present, search through domains expired after the given date. ",
    metavar="YYYY-MM-DD",
    type=valid_date,
)
ARGS_PARSER.add_argument(
    "--expired-date-to",
    help="(history) If present, search through domains expired before the given date.",
    metavar="YYYY-MM-DD",
    type=valid_date,
)
ARGS = ARGS_PARSER.parse_args()
if ARGS.rcfile is not None:
    RC_FILE_LOCS = [ARGS.rcfile] + RC_FILE_LOCS
apiKey = None
if ARGS.apikey is None:
    for rc_file_name in RC_FILE_LOCS:
        try:
            rc_file = open(rc_file_name)
            apiKey = rc_file.read().strip()
            rc_file.close()
            break
        except:
            pass
else:
    apiKey = ARGS.apikey
if apiKey is None:
    raise ValueError("No API key found. Check rc files or specify directly.")
if IDN:
    domain_name = idna.encode(ARGS.domainName).decode("utf-8")
elif not all(ord(char) < 128 for char in ARGS.domainName):
    sys.stderr.write("""Please install the "idna" Python package to query non-ASCII unicode domain names.
Exiting.
""")
    sys.exit(3)
else:
    domain_name = ARGS.domainName
if ARGS.history or (
    ARGS.since_date is not None
    or ARGS.created_date_from is not None
    or ARGS.created_date_to is not None
    or ARGS.updated_date_from is not None
    or ARGS.updated_date_to is not None
    or ARGS.expired_date_from is not None
    or ARGS.expired_date_to is not None
):
    API = (
        "https://whois-history-api.whoisxmlapi.com/api/v1?"
        + "apiKey="
        + apiKey
        + "&outputformat=JSON&mode=purchase"
    )
    ARGS.history = True
else:
    API = (
        "https://www.whoisxmlapi.com/whoisserver/WhoisService?"
        + "apiKey="
        + apiKey
        + "&outputformat=JSON&ip=1"
    )
URL = API + "&domainName=" + domain_name
if ARGS.history:
    if ARGS.since_date is not None:
        URL += f"&sinceDate={ARGS.since_date}"
    if ARGS.created_date_from is not None:
        URL += f"&createdDateFrom={ARGS.created_date_from}"
    if ARGS.created_date_to is not None:
        URL += f"&createdDateTo={ARGS.created_date_to}"
    if ARGS.updated_date_from is not None:
        URL += f"&updatedDateFrom={ARGS.updated_date_from}"
    if ARGS.updated_date_to is not None:
        URL += f"&updatedDateTo={ARGS.updated_date_to}"
    if ARGS.expired_date_from is not None:
        URL += f"&expiredDateFrom={ARGS.expired_date_from}"
    if ARGS.expired_date_to is not None:
        URL += f"&expiredDateTo={ARGS.expired_date_to}"
try:
    result = requests.get(URL).json()
except Exception as e:
    sys.stderr.write(
        "Error invoking API. The API key or the domain name is probably invalid.\n"
    )
    sys.stderr.write(f"Error text: {e!s}\n")
    sys.exit(1)
if ARGS.history:
    try:
        recordCount = result["recordsCount"]
    except:
        recordCount = 0
    if recordCount == 0:
        print("No records found. The output of the API was:")
        print(json.dumps(result, indent=1, sort_keys=False))
        sys.exit(2)
else:
    try:
        theRecord = result["WhoisRecord"]
    except:
        print("No records found. The output of the API was:")
        print(json.dumps(result, indent=1, sort_keys=False))
        sys.exit(2)
    result["records"] = [theRecord.copy()]
recordno = 0
for whoisRecord in result["records"]:
    recordno += 1
    if not ARGS.keep_empty:
        whoisRecord = purge_empty_fields(whoisRecord)
    if ARGS.strippedrawtext:
        for textfield in ["rawText", "strippedText", "cleanText", "header", "footer"]:
            with contextlib.suppress(BaseException):
                whoisRecord[textfield] = whoisRecord[textfield][0:64] + "..."
        for subfield in whoisRecord:
            for textfield in [
                "rawText",
                "strippedText",
                "cleanText",
                "header",
                "footer",
            ]:
                with contextlib.suppress(BaseException):
                    whoisRecord[subfield][textfield] = (
                        whoisRecord[subfield][textfield][0:64] + "..."
                    )
    elif not ARGS.fullrawtext:
        for textfield in ["rawText", "strippedText", "cleanText", "header", "footer"]:
            with contextlib.suppress(BaseException):
                whoisRecord.pop(textfield)
        for subfield in whoisRecord:
            for textfield in [
                "rawText",
                "strippedText",
                "cleanText",
                "header",
                "footer",
            ]:
                with contextlib.suppress(BaseException):
                    whoisRecord[subfield].pop(textfield)
    json_str = json.dumps(whoisRecord, indent=1, sort_keys=False)
    if ARGS.history:
        print(
            "Historic record no. %d of %d for %s:\n------------\n"
            % (recordno, recordCount, ARGS.domainName)
        )
    if ARGS.text:
        raw_str = ""
        dictstr(whoisRecord, 0)
        print(raw_str)
    elif ARGS.nocolor or sys.platform in {"win32", "win64"}:
        print(json_str)
    else:
        print(highlight(json_str, JsonLexer(), TerminalFormatter()))
sys.exit(0)
