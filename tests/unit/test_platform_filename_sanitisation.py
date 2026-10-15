"""Pure-function pins for the stored-filename sanitiser (PLT-005).

These are unit tests on purpose, and for a specific reason: Django's multipart
parser already runs an ``isprintable()`` filter over an uploaded name, so an
integration test of the same property passes even when this module's own
sanitiser lets the character through. The end-to-end case is pinned in
``tests/integration/test_platform_files.py``; this file is what pins the
sanitiser as a control in its own right, which matters because the same name is
used for rows written by routes the API does not expose.

The properties asserted here are the ones the stored *path* depends on: a
filename is one path component, it holds nothing a validator would read as
harmless while the filesystem resolves it differently, and it cannot display
differently from how it is stored.
"""
import pytest

from apps.platform.views import MAX_FILENAME_LENGTH, _sanitise_filename

pytestmark = [pytest.mark.unit]

#: Unicode *format* characters: invisible in a header, order-changing on screen.
BIDI_AND_FORMAT = "".join(chr(code) for code in (0x202A, 0x202B, 0x202C, 0x202D, 0x202E))


class TestNonPrintableCharactersAreDropped:
    @pytest.mark.parametrize("character", list(BIDI_AND_FORMAT))
    def test_a_format_character_is_removed(self, character):
        """U+202E and friends reorder how a name *reads* in a save dialog.

        ``report.exe.pdf`` written with a right-to-left override at the front is
        shown as ``report.pdf`` with the extension reversed, which is how a
        caller is talked into opening a document as something it is not. Django's
        header guard already refuses CR/LF, so this is the display-spoofing half
        that no header check can see.
        """
        sanitised = _sanitise_filename(f"{character}report.pdf")

        assert character not in sanitised
        assert sanitised == "report.pdf"

    def test_control_characters_are_removed(self):
        assert _sanitise_filename("re\x07port.pdf") == "report.pdf"
        assert _sanitise_filename("a\x00b.pdf") == "ab.pdf"

    def test_nothing_non_printable_survives_a_hostile_name(self):
        """The filter is a category rule, not an enumeration.

        A deny-list of the characters that have been seen before is how the next
        one gets through; ``isprintable`` rejects every code point Unicode calls
        "Other" or "Separator", which is the whole class.
        """
        sanitised = _sanitise_filename("a\u200bb\u00a0c\ufeffd.pdf")

        assert all(character.isprintable() for character in sanitised)
        # The extension survives, so the allow-list still sees what it saw before.
        assert sanitised.endswith(".pdf")


class TestOneComponent:
    @pytest.mark.parametrize(
        "hostile",
        [
            "../../etc/passwd.pdf",
            "..%2F..%2Fevil.pdf",
            "/etc/passwd.pdf",
            "..\\..\\evil.pdf",
            "C:some_file.pdf",
        ],
    )
    def test_no_separator_or_parent_reference_survives(self, hostile):
        sanitised = _sanitise_filename(hostile)

        assert "/" not in sanitised
        assert "\\" not in sanitised
        assert ".." not in sanitised
        assert sanitised.endswith(".pdf")

    def test_a_name_reduced_to_nothing_still_produces_one(self):
        """An empty filename would leave the row's column blank."""
        assert _sanitise_filename("...") == "upload"
        assert _sanitise_filename("") == "upload"


class TestTheLengthCap:
    def test_the_stored_name_stays_inside_its_budget_plus_the_extension(self):
        """The cap is a budget, and the measured bound is one over it.

        The truncation caps the *stem* at ``80 - len(extension)`` so the dot and
        the extension survive the truncation, and they are then added on top: the
        longest name that can come out is 81 characters, not 80. That is the
        number the ``file_url`` column arithmetic in the view and the model
        depends on, so it is pinned here rather than left to a comment.
        """
        longest = _sanitise_filename("a" * 400 + ".pdf")

        assert len(longest) == MAX_FILENAME_LENGTH + 1
        assert longest.endswith(".pdf")

    def test_a_short_name_is_never_grown(self):
        assert _sanitise_filename("scan.pdf") == "scan.pdf"

    def test_only_dots_is_not_an_extension(self):
        """``rpartition`` would otherwise read ``.pdf``-shaped input as an
        extension with no stem to truncate, losing the name."""
        assert _sanitise_filename(".pdf") == ".pdf"