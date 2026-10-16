"""The published OpenAPI document generates cleanly, and says what it claims (INT-001, INT-011).

INT-001 asks for a published OpenAPI specification. INT-011 asks for that
specification to be generated and checked rather than maintained by hand. A
green "the command ran" is not either of those, and the reason is specific:
**drf-spectacular exits 0 while emitting diagnostics, and an endpoint it
cannot resolve is silently dropped from the document.** A viewset with no
``serializer_class`` produces a schema that validates against the OpenAPI 3
JSON Schema, passes ``--validate``, returns an exit status of 0, and is simply
missing from ``paths``. Nothing downstream notices, because the only evidence
was a line on stderr that nobody reads.

So this module asserts the diagnostics, not the exit status. Every run captures
stderr and asserts it is empty of severity-prefixed lines, and
:class:`TestTheGateIsNotVacuous` proves that detector is armed by generating a
deliberately broken viewset and requiring the same capture to report it. That
positive control is the whole reason to trust the passing cases: without it,
"zero warnings" and "the assertion never looks" are indistinguishable.

Two things are asserted that are not about drf-spectacular at all, because
INT-001's deliverable is a document a client is expected to trust:

* The three routes the brief names are present, so the published specification
  is not a document that silently dropped authentication or the registry.
* The document **shows the deny-by-default posture**. ``IsAuthenticated`` is
  ``DEFAULT_PERMISSION_CLASSES``, and that is invisible in a schema which
  documents every operation as anonymous. Asserting that data operations carry a
  security requirement while the health probe and the ABDM callback do not means
  a future change to a permission class that widened the API by accident fails
  here rather than in a security review.

**No suppression, anywhere.** There is no ``EXCLUDE``, no
``DISABLE_ERRORS_AND_WARNINGS``, no ``warnings.filterwarnings``, no filtering of
the captured text, and no endpoint removed from the document to make a count
come out right. INT-001 is met only when generation is clean without any of
them, which is why the CI step in ``.github/workflows/ci.yml`` runs
``--fail-on-warn``.

**JSON, not YAML.** The document is parsed with the stdlib ``json`` module from
``--format openapi-json``. ``PyYAML`` is installed — ``drf-spectacular`` requires
it directly — but it is not declared in ``backend/requirements*.txt``, so a test
that imported it would be relying on a transitive dependency, and declaring it
would trigger AGENTS.md section 3's documentation-sync obligation for a change
this task does not need. The YAML path is still exercised end to end, by running
the exact command AGENTS.md section 8 documents and asserting the file it writes
is non-empty — the format is the manager's, and its correctness is not what these
assertions are about.

**The repository stays clean.** Generation writes only into pytest's
``tmp_path``; :class:`TestTheCommandWritesItsFile` pins that.
"""
import io
import json
import re
import sys
import types
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import path
from drf_spectacular.drainage import GENERATOR_STATS
from drf_spectacular.generators import SchemaGenerator
from rest_framework import viewsets
from rest_framework.test import APIClient

pytestmark = [pytest.mark.integration]

#: Repository root, used only to prove the suite never writes inside it.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: The routes the brief names, and the reason each is named. Not an exhaustive
#: path inventory — that is the transport-split suite's job. These three are the
#: ones whose absence from the document would mean the published specification
#: cannot describe how to authenticate, how to register a patient, or how the
#: gateway reaches us.
TOKEN_PATH = "/api/v1/auth/token/"
PATIENTS_PATH = "/api/v1/patients/"
ABDM_CALLBACK_PATH = "/api/v1/abdm-callbacks/"

#: The health probes, and with :data:`ABDM_CALLBACK_PATH` below, the whole of
#: the anonymous surface. Enumerated rather than described, because the previous
#: revision listed only the two probes the container uses and therefore read as
#: exhaustive while three of the seven anonymous operations went unasserted —
#: which is how ``/api/v1/abdm-callbacks/health/`` came to be published
#: anonymously with nothing in this module noticing. Seven of the 331 documented
#: operations carry no security requirement, and all seven are here:
#:
#: * ``/api/v1/health/`` and ``/api/v1/health/ready/`` — the container probes.
#:   There is no tenant to bind and no caller to authenticate, and the CI smoke
#:   test polls them with no credential; AGENTS.md section 4 names the probe as
#:   one of only two endpoints permitted to opt out of ``IsAuthenticated``.
#: * ``/api/v1/abdm-callbacks/health/`` — the gateway adapter's own probe, on
#:   the same reasoning. It lives on an ``AllowAny`` viewset, so it is anonymous
#:   in fact as well as in the document.
#: * ``/api/v1/abdm-callbacks/`` POST, asserted alongside these via
#:   :data:`ABDM_CALLBACK_PATH` — the gateway presents an HMAC over the raw body
#:   rather than a user JWT, so ``IsAuthenticated`` is not what guards it.
#: * ``/api/v1/auth/token/``, ``/token/refresh/`` and ``/token/blacklist/`` —
#:   the credential-issuing endpoints themselves. A client cannot present a
#:   credential to obtain one.
#:
#: ``TOKEN_PATH`` is asserted anonymously by its own test rather than through
#: this tuple; ``refresh`` and ``blacklist`` are published anonymous by
#: SimpleJWT's own views and have no dedicated assertion. The document is where
#: this posture is stated rather than merely implied.
HEALTH_PATHS = (
    "/api/v1/health/",
    "/api/v1/health/ready/",
    "/api/v1/abdm-callbacks/health/",
)

#: The documentation surface itself, which is served without a credential on
#: purpose: an integrator has to be able to read the API contract before they
#: have one. Named here because the paths are asserted anonymously below.
SCHEMA_PATH = "/api/schema/"
DOCS_PATH = "/api/docs/"

#: A drf-spectacular diagnostic. ``GeneratorStats.emit`` prints
#: ``"<source>: <Severity> [<breadcrumbs>]: <message>"`` and ``emit_summary``
#: prints a ``Schema generation summary:`` block, both to ``sys.stderr``. The
#: severity is capitalised, which is what the pattern keys on — matching the
#: bare word "error" would fire on a message that merely mentions one.
DIAGNOSTIC_LINE = re.compile(r"^\S.*?:\s*(?:Warning|Error)\s*(?:\[|:)", re.MULTILINE)
SUMMARY_MARKER = "Schema generation summary"

#: The security scheme the JWT issuer is expected to produce.
EXPECTED_BEARER_SCHEME = {"jwtAuth": {"type": "http", "scheme": "bearer",
                                      "bearerFormat": "JWT"}}

#: The HTTP methods an OpenAPI path item may carry, used when walking every
#: operation under a path. Mirrors the spec rather than DRF's ``http_method_names``.
HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head",
                          "patch", "trace"})


def _diagnostics(text):
    """The severity-prefixed lines in a captured stderr, de-duplicated.

    De-duplicated because ``GeneratorStats.emit`` prints an identical string for
    every repeat of a warning, and an endpoint imported under several names can
    therefore produce the same line many times over. The count is reported
    separately where it matters.
    """
    found = [match.group(0).strip() for match in DIAGNOSTIC_LINE.finditer(text)]
    return sorted(set(found))


def _run_spectacular(*flags, stdout=None):
    """Run ``manage.py spectacular`` in-process and capture what it says.

    ``redirect_stderr`` is not incidental. ``GeneratorStats.emit`` and
    ``emit_summary`` write with ``print(..., file=sys.stderr)`` — they bypass the
    management framework's own ``self.stderr`` wrapper entirely — so a buffer
    passed as ``call_command(stderr=...)`` would come back empty and the gate
    would pass for the wrong reason. The redirect is what actually captures a
    diagnostic, which is why the positive control below is the evidence that it
    works.

    Returns the captured stdout and stderr as text.
    """
    err = io.StringIO()
    out = stdout if stdout is not None else io.StringIO()
    with redirect_stderr(err), redirect_stdout(out):
        call_command("spectacular", *flags)
    return out.getvalue(), err.getvalue()


def _require_clean(stderr, what):
    """Fail with the diagnostics attached, or return.

    The captured text is put in the assertion message because the whole value of
    this gate is the line somebody has to read: a bare "expected no warnings"
    sends the next person to re-run the command by hand to find out which
    endpoint is unresolved.
    """
    diagnostics = _diagnostics(stderr)
    assert SUMMARY_MARKER not in stderr, (
        f"{what} emitted a schema generation summary, so it warned:\n{stderr}"
    )
    assert not diagnostics, (
        f"{what} emitted drf-spectacular diagnostics:\n"
        + "\n".join(diagnostics)
        + f"\n--- full stderr ---\n{stderr}"
    )


def _operations(document, path_name):
    """Every operation under one path, as ``(method, operation)`` pairs."""
    item = document["paths"].get(path_name) or {}
    return sorted(
        (method, item[method])
        for method in HTTP_METHODS
        if isinstance(item.get(method), dict)
    )


def _requires_authentication(operation):
    """Whether an operation demands a credential.

    OpenAPI spells anonymity two different ways, and both must count as
    anonymous: an operation may omit ``security`` altogether (and there is no
    document-level ``security`` to inherit — asserted separately), or it may
    carry an explicit empty requirement, ``security: [{}]``, which is how
    drf-spectacular renders ``AllowAny``. Treating only one of the two as
    anonymous would either fail on a correctly anonymous endpoint or pass on a
    data endpoint that had been made anonymous by accident.
    """
    security = operation.get("security")
    if security is None:
        return False
    return any(requirement for requirement in security)


@pytest.fixture(scope="module")
def generated_document():
    """The project's real schema, generated once, with its stderr captured.

    Module-scoped because generation walks all 159 paths and instantiates a view
    per operation; running it per test would make this the slowest file in the
    suite for no added coverage. The stderr is captured once and asserted on
    repeatedly, which is legitimate — the claim is a property of the generation,
    not of each assertion.
    """
    out, err = _run_spectacular("--format", "openapi-json")

    # Asserted here, at the point the capture is made, rather than in a test:
    # GENERATOR_STATS is process-global and the positive control below
    # deliberately makes it truthy, so a test that read it later would be
    # order-dependent. This is also the exact condition
    # ``manage.py spectacular --fail-on-warn`` tests.
    assert not GENERATOR_STATS, (
        "generation left drf-spectacular diagnostics behind, which is what "
        f"--fail-on-warn would fail the CI step on:\n{err}"
    )
    _require_clean(err, "the project's schema generation")

    document = json.loads(out)

    # Not a fixture assertion: an unparseable document makes every later
    # assertion's failure message noise, and the interesting fact is the
    # json.JSONDecodeError text.
    assert isinstance(document, dict), type(document)

    return document


@pytest.fixture(scope="module")
def written_schema_file(tmp_path_factory):
    """The AGENTS.md section 8 command, writing into pytest's temporary tree."""
    target = tmp_path_factory.mktemp("openapi") / "schema.yml"

    out, err = _run_spectacular("--file", str(target), "--validate")

    _require_clean(err, "the documented --file command")
    assert target.is_file(), (
        "manage.py spectacular --file reported success without writing a file"
    )
    assert target.stat().st_size > 0, "the written schema is empty"
    # YAML is what `--file` writes, so the document must open with the version
    # key rather than being some other payload under the right filename.
    assert target.read_text(encoding="utf-8").startswith("openapi:"), (
        "the file written by --file is not a YAML OpenAPI document"
    )
    # --validate ran inside the command and did not raise, which is the check
    # that the document satisfies the OpenAPI 3 JSON Schema.
    #
    # Silence on success is the contract: the file went to `--file`, so stdout
    # carrying the document would mean the flag was ignored.
    assert out == "", f"--file wrote to stdout as well: {out[:200]!r}"
    return target


class TestTheDocumentIsPublished:
    def test_generation_is_clean(self, generated_document):
        """The zero-diagnostics claim, restated so a failure names itself.

        ``generated_document`` already asserted it while capturing; the value of
        repeating it here is that the requirement INT-001 turns on is stated as a
        named test rather than living in a fixture body. It cannot go vacuous —
        the fixture raises before returning if the capture was dirty.
        """
        assert generated_document

    def test_the_document_is_an_openapi_mapping(self, generated_document):
        """It parses, and carries the four roots a client actually reads.

        The assertion is on the *shape* of ``info``. The *values* are asserted by
        :meth:`test_the_document_is_identified_as_this_api` directly below, which
        is the assertion that makes the declared title and version enforced
        rather than coincidental.
        """
        assert isinstance(generated_document, dict)
        assert set(generated_document) >= {"openapi", "info", "paths", "components"}
        assert generated_document["openapi"].startswith("3.")
        # ``info`` is what a client, a docs site and a code generator read first;
        # an OpenAPI 3 document without it does not validate, so its absence
        # would already fail ``--validate``, but --validate is asserted by the
        # command that writes the file, not by this fixture.
        info = generated_document["info"]
        assert set(info) >= {"title", "version"}, info
        assert isinstance(info["title"], str)
        assert isinstance(info["version"], str)
        # A document with no paths is a valid OpenAPI document describing
        # nothing, which is the shape a generation failure degrades into.
        assert generated_document["paths"], "the document describes no paths"

    def test_the_document_is_identified_as_this_api(self, generated_document):
        """``info.title`` and ``info.version`` are the ones the settings declare.

        The expected values are read from ``settings.SPECTACULAR_SETTINGS`` rather
        than repeated here as literals, so that renaming a version is a one-line
        change in ``config/settings/base.py`` rather than a coordinated edit
        between a setting and its echo. The setting is the single source of truth
        for what the document should say; this assertion's job is to prove the
        value *reached* the document.

        It is the assertion that was previously impossible to write. drf-spectacular
        reads its configuration from ``SPECTACULAR_SETTINGS``, while the dict was
        declared as ``SPECTACULAR``, so nothing was read at all: ``TITLE`` and
        ``VERSION`` never reached the document, and it published as
        ``title: ""`` / ``version: "0.0.0"`` — a specification that names
        nothing. Comparing against the setting under the wrong key degenerated to
        ``"" == ""``, which passes while proving nothing, so the earlier revision
        of this file asserted only the shape and recorded the gap.

        The two degeneracy guards are what stop that from recurring quietly.
        ``TITLE`` and ``VERSION`` have defaults (``""`` and ``"0.0.0"``) that are
        individually valid strings and would sail through both the ``isinstance``
        check above and a "the document has a title" reading of this test. An
        unset or empty declared value would therefore still publish a nameless
        specification with a green suite, which is the exact failure this
        assertion exists to catch.
        """
        declared = settings.SPECTACULAR_SETTINGS
        info = generated_document["info"]

        assert info["title"] == declared["TITLE"], (
            f"the document publishes as {info['title']!r} while the settings "
            f"declare {declared['TITLE']!r}; drf-spectacular is not reading "
            "the dict, so it fell back to its own default of ''"
        )
        assert info["version"] == declared["VERSION"], (
            f"the document publishes as {info['version']!r} while the settings "
            f"declare {declared['VERSION']!r}; drf-spectacular is not reading "
            "the dict, so it fell back to its own default of '0.0.0'"
        )

        # The declared values must themselves be real, or the two assertions
        # above would compare the library's defaults against empty strings and
        # agree with each other.
        assert declared["TITLE"].strip(), (
            "TITLE is declared empty; the published specification would name "
            "nothing even with the setting correctly wired"
        )
        assert declared["VERSION"].strip(), (
            "VERSION is declared empty; a client cannot tell which revision of "
            "the API it is reading"
        )
        assert info["version"] != "0.0.0", (
            "the document carries drf-spectacular's default version, which is "
            "the signature of the SPECTACULAR_SETTINGS dict not being read"
        )

    @pytest.mark.parametrize(
        "path_name",
        [TOKEN_PATH, PATIENTS_PATH, ABDM_CALLBACK_PATH],
        ids=["token", "patients", "abdm-callbacks"],
    )
    def test_the_named_route_is_in_the_document(self, generated_document, path_name):
        """Each route is present *and* has at least one documented operation.

        The operation check is the part that matters. A path item can survive in
        ``paths`` while every method under it was dropped by a resolver that
        gave up — drf-spectacular's own message for that is "Ignoring the view
        for now" — and a client reading the document would find a URL with
        nothing to call.
        """
        assert path_name in generated_document["paths"]
        assert _operations(generated_document, path_name), (
            f"{path_name} is present but documents no operation"
        )

    def test_security_schemes_declare_the_bearer_credential(self, generated_document):
        """``components.securitySchemes`` exists, is non-empty, and is usable.

        Checked against the rendered scheme, not merely the key's presence: a
        ``securitySchemes`` block holding an empty object satisfies "exists" and
        leaves a client with no way to send the credential the API demands.
        ``cookieAuth`` is asserted alongside because DRF's session authentication
        is registered globally, so its absence means the settings the
        ``IsAuthenticated`` default relies on are not reaching the document.
        """
        schemes = generated_document["components"].get("securitySchemes")

        assert schemes, "components.securitySchemes is missing or empty"
        assert schemes["jwtAuth"] == EXPECTED_BEARER_SCHEME["jwtAuth"], schemes
        # SimpleJWT's authentication class; named because it is the second of the
        # two, and a client using a session cookie is equally entitled to the
        # schema saying so.
        assert schemes["cookieAuth"]["in"] == "cookie", schemes
        assert schemes["cookieAuth"]["name"] == "sessionid", schemes


class TestTheDocumentationIsPubliclyReadable:
    """The schema and the Swagger UI must answer an anonymous request.

    ``config/settings/base.py`` declares ``SERVE_PERMISSIONS: [AllowAny]`` and
    ``SERVE_AUTHENTICATION: None`` under a comment explaining why: every data
    endpoint stays authenticated, but requiring a credential to *read the
    contract* would make the documentation unreachable to the integrator it
    exists for. That intent is what these tests enforce.

    They are here because the intent was, for a time, enforced by coincidence
    rather than by configuration. Those two values happen to be exactly
    drf-spectacular's own defaults, so while the dict was declared under a name
    the library never reads, ``/api/schema/`` and ``/api/docs/`` still answered
    200 — the behaviour was right and the declaration behind it was dead. Had
    the library's defaults ever tightened, the Swagger UI would have started
    requiring a JWT with nothing in the diff to explain it. Asserting the
    observable behaviour is what makes the two cases
    indistinguishable: whether the setting is read or the default happens to
    match, a reader can see that the surface is public and why.

    The converse is asserted too. ``SERVE_PERMISSIONS`` must not widen anything
    else: the health probes and the data endpoints keep their existing
    behaviour, because a permission class that leaked from the docs views into
    ``DEFAULT_PERMISSION_CLASSES`` would be the worst outcome of this setting
    being read at all.
    """

    @pytest.mark.parametrize(
        "path_name", [SCHEMA_PATH, DOCS_PATH], ids=["schema", "docs"]
    )
    def test_it_answers_200_without_credentials(self, path_name):
        """Both documentation routes answer an anonymous GET with 200.

        Asserted through the test client rather than by inspecting the view's
        ``permission_classes``, because the claim is about what a client
        experiences. A permission class can be configured correctly and still be
        unreachable if something else in the stack rejects the request first —
        a throttle, a middleware, a URLconf that no longer resolves — and only
        the request itself exercises the whole path.
        """
        response = APIClient().get(path_name)

        assert response.status_code == 200, (
            f"{path_name} answered {response.status_code} to an anonymous GET; "
            "the schema and Swagger UI are declared public in "
            "config/settings/base.py and must stay reachable without a "
            f"credential.\n{response.content[:400]!r}"
        )

    def test_the_token_endpoint_is_still_documented_as_anonymous(self, generated_document):
        """Issuing a token cannot require a token — the document must say so.

        The obvious way to check this is to look at ``info`` or at the schema
        view's own operation in the published document. It is asserted on
        ``TOKEN_PATH`` instead, for the reason the rest of this module cares
        about: the token endpoint is the one operation whose anonymity is a
        genuine round trip. An integrator reads the document, sees
        ``security: [{}]``, and knows to POST credentials rather than to
        expect a 401. If a future change documented it as secured, the client
        generated from that document would send a bearer header to the endpoint
        whose job is to issue one, and the failure would surface as a confusing
        auth error rather than as a schema regression.
        """
        operations = _operations(generated_document, TOKEN_PATH)

        assert operations, f"{TOKEN_PATH} is missing or documents no operation"
        for method, operation in operations:
            assert not _requires_authentication(operation), (
                f"{method.upper()} {TOKEN_PATH} is documented as requiring a "
                "credential, but a client cannot present one to obtain it"
            )


class TestDenyByDefaultIsVisible:
    """The document must state the authentication posture, not flatten it."""

    def test_data_operations_carry_a_security_requirement(
        self, generated_document
    ):
        """Every operation on the registry requires a credential.

        This is the assertion that keeps INT-001 honest. ``IsAuthenticated`` is
        the default permission class, so a viewset that forgot to be secured is
        still secured — but a schema that documents it as anonymous would tell a
        client, a scanner and a future reviewer that it is open. The requirement
        is checked on *every* method under the path, so adding a `DELETE` to a
        secured collection cannot slip past by inheriting the collection's
        description.
        """
        operations = _operations(generated_document, PATIENTS_PATH)

        assert operations
        for method, operation in operations:
            assert _requires_authentication(operation), (
                f"{method.upper()} {PATIENTS_PATH} is documented as requiring no "
                "credential, which contradicts DEFAULT_PERMISSION_CLASSES"
            )

    @pytest.mark.parametrize("path_name", HEALTH_PATHS + (ABDM_CALLBACK_PATH,))
    def test_the_anonymous_surface_is_documented_as_anonymous(
        self, generated_document, path_name
    ):
        """The health probes and the ABDM callback carry no credential.

        The other half of the same claim. A gate that only asserted "everything
        requires auth" would pass on a document in which the health probe had
        been locked down — breaking the container health check in
        ``ci.yml``'s smoke test — and one that only asserted "the probes are
        open" would pass on a document in which everything was. Both directions
        are asserted because the posture is the pair, not either half.
        """
        operations = _operations(generated_document, path_name)

        assert operations, f"{path_name} is missing or documents no operation"
        for method, operation in operations:
            assert not _requires_authentication(operation), (
                f"{method.upper()} {path_name} is documented as requiring a "
                "credential; it is anonymous by design"
            )

    def test_no_document_level_security_requirement_widens_the_api(
        self, generated_document
    ):
        """There is no global ``security``, so no operation inherits one.

        A document-level requirement is the subtler version of the same risk: it
        would leave every operation that omits ``security`` inheriting a
        requirement — meaning the anonymous probes above could be documented as
        secured, or the reverse — with no per-operation line to read. Asserting
        its absence is what makes the per-operation assertions above sufficient
        on their own.
        """
        assert "security" not in generated_document, (
            "the document declares a global security requirement, so an "
            "operation with no security key inherits one instead of being open"
        )


class TestTheCommandWritesItsFile:
    def test_the_agents_section_8_command_produces_a_document(
        self, written_schema_file
    ):
        """The documented command works, and what it wrote is a real schema.

        The command in AGENTS.md section 8 is what a developer and a release run
        by hand; asserting it end to end is what keeps that instruction from
        quietly rotting into a command that writes an empty file or a stack trace
        and still exits 0. The YAML is not parsed here — ``PyYAML`` is not a
        declared dependency of this project, and the document's *content* is
        asserted from the JSON rendering above.
        """
        assert written_schema_file.is_file()
        body = written_schema_file.read_text(encoding="utf-8")

        assert "paths:" in body
        assert "securitySchemes:" in body
        for path_name in (TOKEN_PATH, PATIENTS_PATH, ABDM_CALLBACK_PATH):
            assert path_name in body, f"{path_name} is absent from the written YAML"

    def test_the_repository_tree_is_never_written_to(self, written_schema_file):
        """Generation output stays outside the working tree.

        An earlier revision of this project established that pin for uploaded
        documents (``test_platform_files.py::TestTheRepositoryStaysClean``): a
        suite that writes into the repository leaves files that get committed,
        and generated artefacts are the ones nobody remembers to delete. The
        assertion is the path's own location, not a ``git status``, so it holds
        without a git binary and cannot be satisfied by a file that was already
        there.
        """
        assert written_schema_file.resolve().is_relative_to(REPO_ROOT) is False
        assert not (REPO_ROOT / "schema.yml").exists()
        assert not (REPO_ROOT / "backend" / "schema.yml").exists()


class TestTheGateIsNotVacuous:
    """Proof that the diagnostic assertions above can actually fail.

    Everything in this module so far asserts the *absence* of something. An
    absence assertion that cannot detect presence is indistinguishable from a
    passing test suite, and this one is load-bearing for INT-001: a future
    endpoint with an unresolvable serializer, or a custom action whose
    ``@extend_schema`` was dropped, must be caught by the gate above and not
    discovered by an integrator a quarter later.

    The broken viewset below is never routed into ``config/urls.py``. It exists
    only as a URL pattern handed straight to a generator, so the project's own
    URL surface is untouched and the operation count is unaffected.
    """

    @staticmethod
    def _unresolvable_viewset():
        """A viewset drf-spectacular cannot resolve, by construction.

        A ``ModelViewSet`` with no ``serializer_class`` — the case the library
        documents as "unable to resolve serializer class". It is not a mock and
        not a stub: it is a genuine DRF viewset that genuinely fails to describe
        itself, which is exactly what a real endpoint does when someone forgets
        a serializer or points one at a class that no longer imports.
        """

        class UnresolvableViewSet(viewsets.ModelViewSet):
            pass

        return UnresolvableViewSet

    def _patterns_for(self, viewset):
        return [path("probe/unresolvable/", viewset.as_view({"get": "list"}))]

    def test_a_warning_shaped_failure_is_detected_and_reported(self):
        """The capture, the pattern and the stats check all fire on a real fault.

        Three assertions rather than one, because each could in principle be the
        thing that is broken:

        * ``_diagnostics`` finds a severity-prefixed line in captured stderr;
        * ``GENERATOR_STATS`` is truthy, which is the condition
          ``manage.py spectacular --fail-on-warn`` tests — so the CI gate added
          for this task is pinned by the same evidence, not by inspection of the
          library's source;
        * generation still *succeeds*. This is the finding worth stating
          plainly: the exit status is 0 and the schema is valid OpenAPI while the
          operation is missing. Any gate built on the exit code alone would pass.
        """
        viewset = self._unresolvable_viewset()

        with redirect_stderr(io.StringIO()) as err:
            document = SchemaGenerator(
                patterns=self._patterns_for(viewset)
            ).get_schema(request=None, public=True)
        stderr = err.getvalue()

        assert _diagnostics(stderr), (
            "no diagnostic was captured for a viewset that cannot resolve; the "
            f"gate in this module is not wired to drf-spectacular's output.\n"
            f"stderr was: {stderr!r}"
        )
        assert "Ignoring the view" in stderr, stderr
        assert bool(GENERATOR_STATS) is True, (
            "GENERATOR_STATS is falsy after a diagnostic, so --fail-on-warn "
            "would not fail the CI step on it"
        )
        # The point of the whole module, demonstrated rather than assumed.
        assert isinstance(document, dict)
        assert "probe/unresolvable/" not in document["paths"], (
            "the broken viewset stayed in the document; the capture above is "
            "reporting something else"
        )

    def test_fail_on_warn_turns_that_diagnostic_into_a_failed_command(self):
        """``--fail-on-warn``, the flag the CI step passes, fails on the same fault.

        Driven through ``call_command`` rather than through ``GENERATOR_STATS``
        a second time, because the flag is what the pipeline depends on and a
        test of the underlying predicate does not prove the flag reads it. The
        broken URLconf is registered in ``sys.modules`` instead of being written
        to a module file: ``--urlconf`` takes a dotted path, ``tests/`` is not a
        package so the test module is not importable by one, and registering the
        module keeps the repository tree untouched while still going through
        ``import_module`` exactly as a real URLconf would be reached.
        """
        module = types.ModuleType("throwaway_openapi_urlconf")
        module.urlpatterns = self._patterns_for(self._unresolvable_viewset())
        sys.modules[module.__name__] = module
        try:
            with pytest.raises(CommandError, match="warnings"):
                _run_spectacular(
                    "--urlconf",
                    module.__name__,
                    "--fail-on-warn",
                )
        finally:
            del sys.modules[module.__name__]


class TestTheDocumentIsNotARegression:
    def test_the_published_surface_has_not_shrunk_under_the_gate(self, generated_document):
        """A floor on the documented operation count.

        Not an inventory — an exact count would break on every endpoint anyone
        adds, which trains the next person to update a number rather than to ask
        what changed. A floor fails on the failure mode that actually hides: an
        endpoint silently dropped from the document by a resolver that gave up.
        The current published surface is 331 operations; the bound is set well
        below it so ordinary growth does not trip it.
        """
        operations = sum(len(_operations(generated_document, p))
                         for p in generated_document["paths"])

        assert operations >= 300, (
            f"only {operations} operations are documented; the published surface "
            "was 331 at INT-001, so endpoints are being dropped silently"
        )
