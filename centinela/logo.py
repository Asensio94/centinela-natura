"""The robin, shared logo of the nine sibling projects (estilo-comun v1.1).

Copy this file verbatim next to common.css; change it in all repos at once, never in one.
The shape is the same everywhere and only the breast takes each project's accent: inline the
logo through LOGO_SVG (coloured by common.css) and the tab icon through favicon_link().
A fluffed-up winter robin is nearly a ball, which is what makes it readable at 16 px.
"""

from urllib.parse import quote

_BODY = ('<circle cx="34" cy="31" r="19"/><path d="M19 40 7 50.5l3.5 4L25 46z"/>'
         '<path d="M52 22l8 2.5-8 2.5z"/>')
_BREAST = "M34 12a19 19 0 0 1 15 30.8C42 41 37 34 37 26c0-6 1.5-10.5 4-12.6A19 19 0 0 0 34 12z"
_EYE = '<circle cx="45" cy="21.5" r="2.1"/>'
_LEGS = "M31 49.5V60m7-11v11m-10.5.2h6m1.5 0h6"
_EYE_FILL = "#221d1a"  # always dark: it sits on the breast, which is light in dark mode

LOGO_SVG = (
    '<svg class="logo" viewBox="0 0 64 64" aria-hidden="true" focusable="false">'
    f'<g fill="currentColor">{_BODY}</g><path class="logo-breast" d="{_BREAST}"/>'
    f'<g fill="{_EYE_FILL}">{_EYE}</g>'
    f'<path d="{_LEGS}" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>'
)


def favicon_link(accent: str, accent_dark: str) -> str:
    """<link rel=icon> with the robin in this project's colours, light and dark tab bars alike."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        f"<style>.b{{fill:#221d1a}}.p{{fill:{accent}}}.l{{stroke:#221d1a}}"
        f"@media (prefers-color-scheme:dark){{.b{{fill:#ede6e0}}.p{{fill:{accent_dark}}}.l{{stroke:#ede6e0}}}}</style>"
        f'<g class="b">{_BODY}</g><path class="p" d="{_BREAST}"/><g fill="{_EYE_FILL}">{_EYE}</g>'
        f'<path class="l" d="{_LEGS}" fill="none" stroke-width="3" stroke-linecap="round"/></svg>'
    )
    return f'<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,{quote(svg)}">'
