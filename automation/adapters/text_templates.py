"""Text templates: `<name>.txt` files in config/text_templates/, edited on the
website's "Vorlagen" page and used by every action that takes a template -
send_email (`template`), format_text and add_comment (`text_template`).

A template is just text with $placeholders. An optional first paragraph
`Subject: ...` (followed by a blank line) is the subject when the template is
sent as an e-mail; anywhere else the text after it is used and the subject
line is ignored.

Templates created before this folder existed live in config/email_templates/;
they are still found there (and moved over by the website on its next visit).

The names come from workflows, so they are checked strictly: nothing that
could leave the template folder (no slash, no dot) is ever turned into a path.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from automation.config.settings import REPO_ROOT

# Same rule as TemplateStore::NAME_PATTERN in website/src/TemplateStore.php.
NAME_PATTERN = re.compile(r"^[^\W][\w\- ]{0,59}$")

TEMPLATES_DIR = REPO_ROOT / "config" / "text_templates"
LEGACY_DIR = REPO_ROOT / "config" / "email_templates"


def template_path(directory: Path, name: str) -> Path:
    if not isinstance(name, str) or NAME_PATTERN.fullmatch(name) is None or name != name.strip():
        raise ValueError(f"Invalid template name {name!r} (letters, digits, space, _ and - only)")
    return directory / f"{name}.txt"


def split_subject(text: str) -> tuple[Optional[str], str]:
    """The optional first line `Subject: ...` followed by a blank line is the
    subject, everything after it the body: (subject_or_None, body)."""

    header, separator, rest = text.partition("\n\n")
    if separator and header.startswith("Subject:"):
        return header[len("Subject:"):].strip(), rest
    return None, text


def read_template(name: str, directory: Optional[Path] = None) -> str:
    """The raw text of a template file. Looks in config/text_templates/ and,
    for a template that wasn't moved over yet, in config/email_templates/."""

    directories = [directory] if directory is not None else [TEMPLATES_DIR, LEGACY_DIR]
    for folder in directories:
        path = template_path(folder, name)
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Unknown template '{name}' (expected {template_path(directories[0], name)})")


def load_template(name: str, directory: Optional[Path] = None) -> tuple[Optional[str], str]:
    """(subject_or_None, body) of a template."""

    return split_subject(read_template(name, directory))


def load_template_text(name: str) -> str:
    """Just the text of a template, for actions that aren't e-mails (a
    `Subject:` line, if there is one, is dropped)."""

    return load_template(name)[1]
