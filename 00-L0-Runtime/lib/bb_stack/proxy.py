"""Proxy environment for stack-launched work.

One module decides what the proxy variables are, because three call sites need
the same answer: the generated ``env.sh`` (so a shell carries it), the workspace
settings handed to a launched agent, and recon's per-provider command lines.
Drift between them is exactly how a scan goes out over the operator's real
address while the shell claims otherwise.

Modes:

- ``direct`` -- every proxy variable is cleared. Explicitly empty, not merely
  absent: a child inherits its parent's ``HTTP_PROXY``, and the point of `direct`
  is to override what was inherited.
- ``http`` -- ``HTTP_PROXY``/``HTTPS_PROXY`` only, from ``BB_HTTP_PROXY``.
- ``socks`` -- ``ALL_PROXY`` only, from ``BB_SOCKS_PROXY``. Most clients honour
  ``ALL_PROXY``; those that do not are listed in ``ALL_PROXY_BLIND`` below.
- ``mihomo`` -- both, the historical name for "an http proxy and a socks proxy,
  as a local mihomo/Clash instance provides".

Variables are set in both cases (``HTTP_PROXY`` and ``http_proxy``): some tools
read only one spelling, and a proxy that is silently ignored is worse than no
proxy, because it looks configured.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any

from .errors import ValidationError

PROXY_MODES = ("direct", "http", "socks", "mihomo")
DEFAULT_MODE = "direct"

# mode -> {variable stem: which configured URL feeds it}
MODE_SOURCES: dict[str, dict[str, str]] = {
    "direct": {},
    "http": {"HTTP_PROXY": "http", "HTTPS_PROXY": "http"},
    "socks": {"ALL_PROXY": "socks"},
    "mihomo": {"HTTP_PROXY": "http", "HTTPS_PROXY": "http", "ALL_PROXY": "socks"},
}

# Every spelling any client is known to read. `apply` clears all of them so an
# inherited value cannot survive; only the uppercase ones are ever set.
UPPERCASE_VARIABLES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
PROXY_VARIABLES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)

# Tools whose traffic cannot be routed by an HTTP/SOCKS proxy at all, with what
# an operator needs instead. Verified against each tool's `-h`; the list is the
# gap an operator must plan around, not a detail to discover mid-scan.
PROXY_BLIND_TOOLS = {
    "amass": "no proxy option; route the whole host (VPN) instead",
    "arjun": "no proxy option",
    "alterx": "offline permutation only -- it sends nothing",
    "jsluice": "offline JavaScript parsing -- it sends nothing",
    "massdns": "raw DNS; needs a VPN, or a resolver-level tunnel",
    "nmap": "raw packets; needs a VPN, or proxychains with a SOCKS proxy",
    "puredns": "wraps massdns, so raw DNS",
    "trufflehog": "no proxy option",
    "waybackurls": "no proxy option",
}

# provider -> (flag, which configured URL it wants). Verified against each tool's
# own `-h`: several accept only one kind, so passing the other silently does
# nothing. `kind` is a preference; `resolver` falls back to whatever is
# configured when the preferred one is absent.
PROVIDER_FLAGS: dict[str, tuple[str, str]] = {
    "asnmap": ("-proxy", "http"),
    "bbot": ("--proxy", "http"),
    "dnsx": ("-proxy", "socks"),
    "ffuf": ("-x", "http"),
    "gau": ("--proxy", "http"),
    "httpx": ("-http-proxy", "http"),
    "katana": ("-proxy", "http"),
    "naabu": ("-proxy", "socks"),
    "nuclei": ("-proxy", "http"),
    "subfinder": ("-proxy", "http"),
}


def provider_args(provider: str, machine: dict[str, Any]) -> list[str]:
    """Explicit ``-proxy`` argument for *provider*, or nothing.

    Environment variables cover most clients, but relying on them is a bet: a
    tool that ignores `HTTP_PROXY` goes direct and says nothing. Passing the flag
    makes the routing a property of the command line instead of a property of the
    environment it happened to inherit. Providers with no flag at all are in
    `PROXY_BLIND_TOOLS`, so the gap is named rather than silent.
    """
    spec = PROVIDER_FLAGS.get(provider)
    if spec is None:
        return []
    flag, kind = spec
    url = active_url(machine, kind)
    if not url:
        # Fall back to the other kind: most of these accept both, and a socks
        # proxy is better than none for the ones that only want http.
        url = active_url(machine, "socks" if kind == "http" else "http")
    return [flag, url] if url else []


def validate_mode(value: Any) -> str:
    """A declared proxy mode, rejected unless it is one we implement."""
    mode = value if isinstance(value, str) and value else DEFAULT_MODE
    if mode not in PROXY_MODES:
        raise ValidationError(
            f"unknown proxy mode {value!r}; known: " + ", ".join(PROXY_MODES)
        )
    return mode


def configured_urls(machine: dict[str, Any]) -> dict[str, str]:
    """The proxy URLs the machine declares, by kind."""
    return {
        "http": str(machine.get("BB_HTTP_PROXY") or "").strip(),
        "socks": str(machine.get("BB_SOCKS_PROXY") or "").strip(),
    }


def environment(machine: dict[str, Any]) -> dict[str, str]:
    """The uppercase proxy variables this machine's mode sets.

    Uppercase only. Every client checked -- curl, urllib, the Go tools, npm --
    reads the uppercase spelling too, and the lowercase one is precisely where a
    stale inherited value hides. `apply` therefore removes both spellings before
    setting these, so the configuration is the only source.
    """
    mode = validate_mode(machine.get("BB_PROXY_MODE"))
    urls = configured_urls(machine)
    wanted = MODE_SOURCES[mode]
    return {
        name: urls[kind]
        for name in UPPERCASE_VARIABLES
        if (kind := wanted.get(name))
    }


def apply(target: dict[str, str], machine: dict[str, Any]) -> dict[str, str]:
    """Overwrite *target* in place with this machine's proxy decision.

    Both spellings are **removed** first, then only the uppercase ones are set.
    Removal rather than emptying matters: a key holding ``""`` is read as "no
    proxy" by most clients but as "unset" by some, and either way the inherited
    value is gone. Setting only the uppercase spelling is the contract the rest
    of the repository already relies on, and every client checked honours it.
    """
    for name in PROXY_VARIABLES:
        target.pop(name, None)
    target.update(environment(machine))
    return target


def active_url(machine: dict[str, Any], kind: str = "http") -> str:
    """The URL this machine would actually use for *kind*, or empty.

    ``direct`` uses none; ``socks`` uses none for http. Used by recon to decide
    whether a provider can be pointed at a proxy at all.
    """
    mode = validate_mode(machine.get("BB_PROXY_MODE"))
    wanted = MODE_SOURCES[mode]
    if kind == "http" and "HTTP_PROXY" not in wanted:
        return ""
    if kind == "socks" and "ALL_PROXY" not in wanted:
        return ""
    return configured_urls(machine).get(kind, "")


def describe(machine: dict[str, Any]) -> dict[str, Any]:
    """What this machine's proxy setting means, for `proxy check` to report."""
    mode = validate_mode(machine.get("BB_PROXY_MODE"))
    urls = configured_urls(machine)
    return {
        "mode": mode,
        "http_url": active_url(machine, "http"),
        "socks_url": active_url(machine, "socks"),
        "configured": {kind: url for kind, url in urls.items() if url},
        "proxied": sorted({name for name in ("http", "socks") if active_url(machine, name)}),
        "blind_tools": dict(sorted(PROXY_BLIND_TOOLS.items())),
    }


IP_ECHO_URL = "https://api.ipify.org"
ECHO_TIMEOUT = 15


def _fetch_ip(routing: dict[str, str], timeout: int) -> dict[str, Any]:
    """The address an HTTP request with *routing* applied appears to come from.

    The routing is applied explicitly rather than through `os.environ`, because
    urllib caches the proxy settings it reads from the environment at first use:
    mutating `os.environ` would report the previous call's routing.
    """
    http = routing.get("HTTP_PROXY") or routing.get("http_proxy") or ""
    https = routing.get("HTTPS_PROXY") or routing.get("https_proxy") or ""
    all_proxy = routing.get("ALL_PROXY") or routing.get("all_proxy") or ""
    handlers = [
        urllib.request.ProxyHandler(
            {
                name: value
                for name, value in (
                    ("http", http), ("https", https), ("all", all_proxy)
                )
                if value
            }
        )
    ]
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(IP_ECHO_URL, headers={"Accept": "text/plain"})
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace").strip()
    except (urllib.error.URLError, OSError, ValueError) as error:
        return {"ip": None, "error": f"{error.__class__.__name__}: {error}"}
    return {"ip": body or None, "error": None}


def check(
    paths: Any,
    *,
    timeout: int = ECHO_TIMEOUT,
    fetch: Any = None,
) -> dict[str, Any]:
    """Compare the address a direct request and a proxied request come from.

    A proxied probe that completes without an error is the primary evidence: the
    request left through the configured proxy. The addresses are the second
    piece -- when they differ the exit really is the proxy's, but a shared NAT
    makes them identical even though the proxy was used, so a match must not be
    read as "not routed". A proxy that is configured but not applied, or one
    that cannot be reached, makes the proxied probe fail instead. The blind-tool
    list is reported alongside, because those providers go direct no matter how
    the comparison turns out.
    """
    from .configuration import ConfigurationManager

    machine = ConfigurationManager(paths).effective()
    described = describe(machine)
    probe = fetch or _fetch_ip
    direct = probe({name: "" for name in PROXY_VARIABLES}, timeout)
    proxied: dict[str, Any] | None = None
    if described["proxied"]:
        proxied = probe(environment(machine), timeout)
    in_path = bool(proxied and proxied.get("ip") and not proxied.get("error"))
    differs = bool(
        in_path
        and direct.get("ip")
        and direct["ip"] != proxied["ip"]
    )
    return {
        "mode": described["mode"],
        "configured": described["configured"],
        "direct": direct,
        "proxied": proxied,
        "in_path": in_path,
        "differs": differs,
        "blind_tools": described["blind_tools"],
        "routed_tools": sorted(PROVIDER_FLAGS),
    }
