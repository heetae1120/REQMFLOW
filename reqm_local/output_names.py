"""WeKeep upload names use item names, without the REQM brand prefix."""
import re


def without_brand_prefix(name):
    name = str(name or '').strip()
    return re.sub(r'^(?:(?:\[리큐엠\]|【리큐엠】)\s*|리큐엠\s*[-_:]\s*)+', '', name).strip()
