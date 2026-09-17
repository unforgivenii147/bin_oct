#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.etree.ElementTree import Element

from defusedxml.ElementTree import parse as _parse


def etree_to_dict(element: Element | None):
    d = {element.tag: {} if element.attrib else None}
    children = list(element)
    if children:
        dd = {}
        for dc in map(etree_to_dict, children):
            for k, v in dc.items():
                if k in dd:
                    if not isinstance(dd[k], list):
                        dd[k] = [dd[k]]
                    dd[k].append(v)
                else:
                    dd[k] = v
        d = {element.tag: dd}
    if element.attrib:
        d[element.tag].update({"@attributes": element.attrib})
    if element.text and element.text.strip():
        if d[element.tag] is None:
            d[element.tag] = element.text.strip()
        else:
            d[element.tag]["#text"] = element.text.strip()
    return d


def xml_to_json(xml_path: str) -> None:
    json_path = Path(xml_path).with_suffix(".json")
    try:
        tree = _parse(xml_path)
        root = tree.getroot()
        json_data = etree_to_dict(root)
        with json_path.open("w", encoding="utf-8") as json_file:
            json.dump(json_data, json_file, indent=2, ensure_ascii=False)
        print(f"Successfully converted '{xml_path}' to '{json_path}'")
    except:
        print("Error parsing XML file")


if __name__ == "__main__":
    input_xml_file = sys.argv[1]
    xml_to_json(input_xml_file)
