#!/usr/bin/env python
import argparse
import re
import logging
import json
import pathlib

from typing import Tuple, Any
from bs4 import BeautifulSoup

_logger = logging.getLogger(__name__)

_re_time = re.compile(r"^\s*(?P<raw_time>\d+\.\d+)(\+(?P<penalty>.+?))?\s*$")

def parse_time(raw_value: str | None) -> Tuple[float, int, str] | None:
    try:
        if raw_value is not None and (match := _re_time.match(raw_value)):
            raw_time = float(match.group("raw_time"))
            penalty = match.group("penalty")

            # penalty overrides cones
            if penalty in ("dnf", "dsq", "off", "out"):
                return (raw_time, 0, penalty)
            # penalty is just cones
            elif penalty:
                return (raw_time, int(penalty), "dirty")
            # clean run
            else:
                return (raw_time, 0, "clean")

        else:
            return None

    except Exception as e:
        _logger.error(f"Unable to parse result `{raw_value}` ({str(e)})")
        return None


def parse_axware_live_results(fpath: str) -> list[dict[str, Any]]:
    """Returns all results in the event"""

    with open(fpath, "r", encoding="utf-8") as fp:
        s = BeautifulSoup(fp, "html.parser")

    # get results table
    results_table = s.find_all("table")[-1]

    # filter out class line rules and get header/result rows
    filtered_rows = results_table.contents[0].find_all(lambda x: len(x.contents) > 3)
    header_row, result_rows = filtered_rows[0], filtered_rows[1:]

    # extract all headers
    headers = [t.string.strip() for t in header_row.find_all("th")]

    # check if results file is multirow formatted
    multirow = False
    for header in headers:
        if ".." in header:
            multirow = True
            break

    # extract results
    results = []

    # only used for multirow mode
    current_entry = None
    current_runs = None
    current_row = 0

    for result in result_rows:
        row_data = result.find_all("td")
        entry = {}
        row_runs = []

        for header, raw_value in zip(headers, row_data):

            text = raw_value.text.strip()

            # parse times
            if "Run" in header:
                value = parse_time(text)
            elif header == "Pax Time":
                if value := parse_time(text):
                    value = value[0]

            # parse integers
            elif header == "Pos":
                value = int(text.replace("T", ""))

            # all other values, just store raw string
            else:
                value = text

            if "Run" in header:

                # when parsing multirow results files, it's possible to have a case where an entry
                # in a "Run" column doesn't actually correspond to an actual run. This can be
                # detected by checking for a "valign" attribute in the raw tag
                # skip appending the run value if the cell is actually just a placeholder
                if "valign" not in raw_value.attrs:
                    continue

                # ignore empty runs
                if value is None:
                    continue

                row_runs.append(value)

            else:
                entry[header] = value

        # for multi-day events, multirow mode is guaranteed
        if multirow:
            # new entry, create new dictionary
            if row_data[0].text:

                # add previous entry to output results
                if current_entry:
                    current_entry["runs"].append(current_runs)
                    results.append(current_entry)

                current_entry = {}
                current_entry.update(entry)
                current_entry["Diff."] = None
                current_entry["runs"] = []
                current_runs = row_runs
                current_row = 0

            # next row for current entry, append runs to existing entry
            else:

                # in multiday-files, terminate day1 results when encountering 2nd day row
                if(
                    "Day" in entry
                    and entry["Day"] == "D2"
                ):
                    current_entry["runs"].append(current_runs)
                    current_runs = []

                # diff is stored in "Total" column in second row when in multirow
                if current_entry["Diff."] is None and current_row == 1:
                    current_entry["Diff."] = entry["Total"]

                for run in row_runs:
                    current_runs.append(run)

            current_row += 1

        else:
            entry["runs"] = [row_runs]
            results.append(entry)

    # append final entry to results in multirow mode
    if multirow:
        current_entry["runs"].append(current_runs)
        results.append(current_entry)

    return results


if __name__ == "__main__":
    argp = argparse.ArgumentParser(
        description="Simple parser to convert AxWare live results HTML file into JSON"
    )
    argp.add_argument("file", nargs="*", type=pathlib.Path)

    args = argp.parse_args()

    for fpath in args.file:
        fpath: pathlib.Path
        results = parse_axware_live_results(fpath)

        outpath = fpath.with_suffix(".json")

        with open(outpath, "w") as fp:
            json.dump(results, fp, indent=4)
