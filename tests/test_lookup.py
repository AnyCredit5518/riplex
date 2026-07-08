from types import SimpleNamespace

import pytest

from riplex.lookup import lookup_metadata
from riplex.metadata.provider import (
    MetadataProvider,
    SeasonMetadata,
    ShowDetail,
)
from riplex.models import PlannedSeason, PlannedShow, SearchRequest


class _StubProvider(MetadataProvider):
    async def search(self, query, *, year=None, media_type="auto"):
        return []

    async def get_movie_detail(self, source_id):
        raise AssertionError("movie detail should not be called")

    async def get_show_detail(self, source_id, *, include_specials=True):
        raise AssertionError("show detail should not be called")


@pytest.mark.asyncio
async def test_lookup_metadata_qualifies_dvdcompare_title_for_tv_season(monkeypatch):
    async def _fake_pick_match(request, provider):
        # Only .media_type is read downstream in lookup_metadata.
        return SimpleNamespace(
            title="Scrubs", year=2001, media_type="tv", source_id="tv:1",
        )

    async def _fake_plan_show(match, provider, request):
        return PlannedShow(
            canonical_title="Scrubs",
            year=2001,
            seasons=[PlannedSeason(season_number=6, episodes=[])],
        )

    recorded = {}

    async def _fake_fetch_film(self, title, disc_format=None, year=None):
        recorded["title"] = title
        recorded["disc_format"] = disc_format
        recorded["year"] = year
        return SimpleNamespace(releases=[], film_id=None)

    def _fake_select_release(film, disc_info=None, preferred=None):
        return [], ""

    monkeypatch.setattr("riplex.lookup.pick_match", _fake_pick_match)
    monkeypatch.setattr("riplex.lookup._plan_show", _fake_plan_show)
    monkeypatch.setattr(
        "riplex.disc.provider.DiscProvider.fetch_film", _fake_fetch_film,
    )
    monkeypatch.setattr(
        "riplex.lookup.select_dvdcompare_release", _fake_select_release,
    )

    result = await lookup_metadata(
        SearchRequest(title="Scrubs", year=2001, season_number=6, media_type="tv"),
        _StubProvider(),
        disc_format="Blu-ray",
    )

    assert result.canonical == "Scrubs"
    assert recorded["title"] == "Scrubs: Season 6"
    assert recorded["disc_format"] == "Blu-ray"


@pytest.mark.asyncio
async def test_lookup_metadata_captures_dvdcompare_film_id(monkeypatch):
    """The film_id of the resolved dvdcompare film propagates onto the
    ``LookupResult`` so downstream ``build_rip_manifest`` calls can
    record it. Persisted so organize can skip the release picker."""
    async def _fake_pick_match(request, provider):
        return SimpleNamespace(
            title="Psych", year=2006, media_type="tv", source_id="tv:1447",
        )

    async def _fake_plan_show(match, provider, request):
        return PlannedShow(
            canonical_title="Psych",
            year=2006,
            seasons=[PlannedSeason(season_number=1, episodes=[])],
        )

    async def _fake_fetch_film(self, title, disc_format=None, year=None):
        return SimpleNamespace(releases=[SimpleNamespace(name="R1", discs=[])], film_id=12345)

    def _fake_select_release(film, disc_info=None, preferred=None):
        return [], "Psych: Season 1 (TV) (DVD)"

    monkeypatch.setattr("riplex.lookup.pick_match", _fake_pick_match)
    monkeypatch.setattr("riplex.lookup._plan_show", _fake_plan_show)
    monkeypatch.setattr("riplex.disc.provider.DiscProvider.fetch_film", _fake_fetch_film)
    monkeypatch.setattr("riplex.lookup.select_dvdcompare_release", _fake_select_release)

    result = await lookup_metadata(
        SearchRequest(title="Psych", year=2006, season_number=1, media_type="tv"),
        _StubProvider(),
    )

    assert result.dvdcompare_film_id == 12345
    assert result.release_name == "Psych: Season 1 (TV) (DVD)"
    assert result.tmdb_match.source_id == "tv:1447"


class _StubProviderWithShow(MetadataProvider):
    """Like _StubProvider but returns a caller-supplied ShowDetail so the
    season-prompt code path can exercise it."""

    def __init__(self, show_detail: ShowDetail):
        self._detail = show_detail

    async def search(self, query, *, year=None, media_type="auto"):
        return []

    async def get_movie_detail(self, source_id):
        raise AssertionError("movie detail should not be called")

    async def get_show_detail(self, source_id, *, include_specials=True):
        return self._detail


@pytest.mark.asyncio
async def test_lookup_metadata_prompts_for_season_on_multi_season_tv(monkeypatch):
    """Interactive + TV + no season_number set -> prompt user, use their
    pick for both _plan_show and the dvdcompare title bias."""
    async def _fake_pick_match(request, provider):
        return SimpleNamespace(
            title="Psych", year=2006, media_type="tv", source_id="tv:1447",
        )

    async def _fake_plan_show(match, provider, request):
        return PlannedShow(
            canonical_title="Psych",
            year=2006,
            seasons=[PlannedSeason(season_number=request.season_number or 0, episodes=[])],
        )

    recorded: dict = {}

    async def _fake_fetch_film(self, title, disc_format=None, year=None):
        recorded["title"] = title
        return SimpleNamespace(releases=[], film_id=None)

    def _fake_select_release(film, disc_info=None, preferred=None):
        return [], ""

    def _fake_prompt_choice(header, options, *, default=0):
        recorded["prompt_options"] = list(options)
        recorded["prompt_header"] = header
        return 1  # user picks Season 2 (index 1 in the non-special list)

    monkeypatch.setattr("riplex.lookup.pick_match", _fake_pick_match)
    monkeypatch.setattr("riplex.lookup._plan_show", _fake_plan_show)
    monkeypatch.setattr("riplex.disc.provider.DiscProvider.fetch_film", _fake_fetch_film)
    monkeypatch.setattr("riplex.lookup.select_dvdcompare_release", _fake_select_release)
    monkeypatch.setattr("riplex.lookup.is_interactive", lambda: True)
    monkeypatch.setattr("riplex.lookup.prompt_choice", _fake_prompt_choice)
    # Isolate from any real Psych rips that may live under the dev
    # machine's configured output root -- we're testing the prompt
    # plumbing, not the in-progress scan.
    monkeypatch.setattr(
        "riplex.manifest.scan_in_progress_seasons",
        lambda *_a, **_kw: {},
    )

    show = ShowDetail(
        source_id="tv:1447",
        title="Psych",
        year=2006,
        seasons=[
            SeasonMetadata(season_number=0, episodes=[], name="Specials"),
            SeasonMetadata(season_number=1, episodes=[], name="Season 1"),
            SeasonMetadata(season_number=2, episodes=[], name="Season 2"),
            SeasonMetadata(season_number=3, episodes=[], name="Season 3"),
        ],
    )
    result = await lookup_metadata(
        SearchRequest(title="Psych", media_type="tv"),
        _StubProviderWithShow(show),
    )

    # Season 0 must NOT appear in the prompt list.
    assert len(recorded["prompt_options"]) == 3
    assert not any("Season 0" in o for o in recorded["prompt_options"])
    # Prompt header carries the show title for context.
    assert "Psych" in recorded["prompt_header"]
    # dvdcompare query was biased with the picked season.
    assert recorded["title"] == "Psych: Season 2"
    assert result.canonical == "Psych"
    # LookupResult surfaces the picked season so callers can persist
    # it into the session marker / rip manifest.
    assert result.season_number == 2


@pytest.mark.asyncio
async def test_lookup_metadata_skips_season_prompt_for_miniseries(monkeypatch):
    """When the show only has one non-special season (mini-series), we
    do NOT prompt and we do NOT set season_number -- the dvdcompare
    query stays as the bare title so mini-series films (which are not
    listed per-season on dvdcompare) match correctly. Season 0 extras
    on the disc still route correctly at organize time because
    _plan_show returns the full plan."""
    async def _fake_pick_match(request, provider):
        return SimpleNamespace(
            title="Planet Earth II", year=2016, media_type="tv",
            source_id="tv:68595",
        )

    async def _fake_plan_show(match, provider, request):
        assert request.season_number is None, (
            "mini-series must not have season_number set"
        )
        return PlannedShow(
            canonical_title="Planet Earth II",
            year=2016,
            seasons=[PlannedSeason(season_number=1, episodes=[])],
        )

    recorded: dict = {}

    async def _fake_fetch_film(self, title, disc_format=None, year=None):
        recorded["title"] = title
        return SimpleNamespace(releases=[], film_id=None)

    def _fake_select_release(film, disc_info=None, preferred=None):
        return [], ""

    def _fake_prompt_choice(header, options, *, default=0):
        raise AssertionError("prompt_choice must not be called for mini-series")

    monkeypatch.setattr("riplex.lookup.pick_match", _fake_pick_match)
    monkeypatch.setattr("riplex.lookup._plan_show", _fake_plan_show)
    monkeypatch.setattr("riplex.disc.provider.DiscProvider.fetch_film", _fake_fetch_film)
    monkeypatch.setattr("riplex.lookup.select_dvdcompare_release", _fake_select_release)
    monkeypatch.setattr("riplex.lookup.is_interactive", lambda: True)
    monkeypatch.setattr("riplex.lookup.prompt_choice", _fake_prompt_choice)

    show = ShowDetail(
        source_id="tv:68595",
        title="Planet Earth II",
        year=2016,
        seasons=[
            SeasonMetadata(season_number=0, episodes=[], name="Specials"),
            SeasonMetadata(season_number=1, episodes=[], name="Miniseries"),
        ],
    )
    result = await lookup_metadata(
        SearchRequest(title="Planet Earth II", media_type="tv"),
        _StubProviderWithShow(show),
    )

    # dvdcompare gets the bare title (no "Season 1" suffix).
    assert recorded["title"] == "Planet Earth II"
    assert result.canonical == "Planet Earth II"


@pytest.mark.asyncio
async def test_lookup_metadata_season_prompt_skipped_when_non_interactive(monkeypatch):
    """CI/pipe runs must not block on a prompt. When not interactive we
    fall through with season_number=None regardless of season count."""
    async def _fake_pick_match(request, provider):
        return SimpleNamespace(
            title="Psych", year=2006, media_type="tv", source_id="tv:1447",
        )

    async def _fake_plan_show(match, provider, request):
        assert request.season_number is None
        return PlannedShow(canonical_title="Psych", year=2006, seasons=[])

    async def _fake_fetch_film(self, title, disc_format=None, year=None):
        return SimpleNamespace(releases=[], film_id=None)

    def _fake_select_release(film, disc_info=None, preferred=None):
        return [], ""

    def _boom_get_show_detail(*a, **kw):
        raise AssertionError(
            "get_show_detail must not be called when non-interactive "
            "-- the prompt path should be skipped entirely"
        )

    monkeypatch.setattr("riplex.lookup.pick_match", _fake_pick_match)
    monkeypatch.setattr("riplex.lookup._plan_show", _fake_plan_show)
    monkeypatch.setattr("riplex.disc.provider.DiscProvider.fetch_film", _fake_fetch_film)
    monkeypatch.setattr("riplex.lookup.select_dvdcompare_release", _fake_select_release)
    monkeypatch.setattr("riplex.lookup.is_interactive", lambda: False)

    class _Provider(MetadataProvider):
        async def search(self, *a, **kw): return []
        async def get_movie_detail(self, *a, **kw): raise AssertionError()
        async def get_show_detail(self, *a, **kw):
            _boom_get_show_detail()

    await lookup_metadata(
        SearchRequest(title="Psych", media_type="tv"),
        _Provider(),
    )


@pytest.mark.asyncio
async def test_lookup_metadata_season_prompt_biases_default_to_in_progress(
    monkeypatch,
):
    """When Season 2 has an in-progress rip and Season 1 doesn't, the
    prompt's default index shifts to Season 2 so the user can just hit
    Enter to resume the season they're mid-way through. Hint text also
    appears next to that season in the options list."""
    async def _fake_pick_match(request, provider):
        return SimpleNamespace(
            title="Psych", year=2006, media_type="tv", source_id="tv:1447",
        )

    async def _fake_plan_show(match, provider, request):
        return PlannedShow(
            canonical_title="Psych", year=2006,
            seasons=[PlannedSeason(
                season_number=request.season_number or 0, episodes=[],
            )],
        )

    recorded: dict = {}

    async def _fake_fetch_film(self, title, disc_format=None, year=None):
        return SimpleNamespace(releases=[], film_id=None)

    def _fake_select_release(film, disc_info=None, preferred=None):
        return [], ""

    def _fake_prompt_choice(header, options, *, default=0):
        recorded["options"] = list(options)
        recorded["default"] = default
        return default  # accept the default (simulating "hit Enter")

    monkeypatch.setattr("riplex.lookup.pick_match", _fake_pick_match)
    monkeypatch.setattr("riplex.lookup._plan_show", _fake_plan_show)
    monkeypatch.setattr("riplex.disc.provider.DiscProvider.fetch_film", _fake_fetch_film)
    monkeypatch.setattr("riplex.lookup.select_dvdcompare_release", _fake_select_release)
    monkeypatch.setattr("riplex.lookup.is_interactive", lambda: True)
    monkeypatch.setattr("riplex.lookup.prompt_choice", _fake_prompt_choice)
    monkeypatch.setattr(
        "riplex.manifest.scan_in_progress_seasons",
        lambda _title, _seasons: {2: "in progress (2/4 discs ripped)"},
    )

    show = ShowDetail(
        source_id="tv:1447", title="Psych", year=2006,
        seasons=[
            SeasonMetadata(season_number=0, episodes=[], name="Specials"),
            SeasonMetadata(season_number=1, episodes=[], name="Season 1"),
            SeasonMetadata(season_number=2, episodes=[], name="Season 2"),
            SeasonMetadata(season_number=3, episodes=[], name="Season 3"),
        ],
    )
    result = await lookup_metadata(
        SearchRequest(title="Psych", media_type="tv"),
        _StubProviderWithShow(show),
    )

    # Season 2 is index 1 in the non-special list -- default shifts to it.
    assert recorded["default"] == 1
    # Only Season 2's option carries the hint text.
    assert "in progress" in recorded["options"][1]
    assert "2/4 discs ripped" in recorded["options"][1]
    assert "in progress" not in recorded["options"][0]
    assert "in progress" not in recorded["options"][2]
    # And the returned lookup honors the biased default.
    assert result.season_number == 2


@pytest.mark.asyncio
async def test_lookup_metadata_filters_boxset_release_to_picked_season(monkeypatch):
    """The "one season at a time" invariant: when the resolved
    dvdcompare release is a multi-season boxset, ``LookupResult.discs``
    only contains discs for the season the request asked for."""
    from riplex.models import PlannedDisc

    async def _fake_pick_match(request, provider):
        return SimpleNamespace(
            title="Psych", year=2006, media_type="tv", source_id="tv:1447",
        )

    async def _fake_plan_show(match, provider, request):
        return PlannedShow(
            canonical_title="Psych", year=2006,
            seasons=[PlannedSeason(season_number=2, episodes=[])],
        )

    async def _fake_fetch_film(self, title, disc_format=None, year=None):
        # dvdcompare returns a boxset film titled generically -- the
        # per-disc "Season N" titles do the split work.
        return SimpleNamespace(
            releases=[SimpleNamespace(name="Complete Series", discs=[])],
            film_id=99999,
            title="Psych: The Complete Series (TV) (Blu-ray)",
        )

    def _fake_select_release(film, disc_info=None, preferred=None):
        boxset = (
            [PlannedDisc(number=n, disc_format="Blu-ray", title="Season 1")
             for n in range(1, 5)]
            + [PlannedDisc(number=n, disc_format="Blu-ray", title="Season 2")
               for n in range(5, 9)]
            + [PlannedDisc(number=n, disc_format="Blu-ray", title="Season 3")
               for n in range(9, 13)]
        )
        return boxset, "Complete Series"

    monkeypatch.setattr("riplex.lookup.pick_match", _fake_pick_match)
    monkeypatch.setattr("riplex.lookup._plan_show", _fake_plan_show)
    monkeypatch.setattr("riplex.disc.provider.DiscProvider.fetch_film", _fake_fetch_film)
    monkeypatch.setattr("riplex.lookup.select_dvdcompare_release", _fake_select_release)

    result = await lookup_metadata(
        SearchRequest(
            title="Psych", year=2006, media_type="tv", season_number=2,
        ),
        _StubProvider(),
    )

    assert [d.number for d in result.discs] == [5, 6, 7, 8]
    assert result.season_number == 2


@pytest.mark.asyncio
async def test_lookup_metadata_movie_release_not_filtered(monkeypatch):
    """Movie rips never hit the season filter -- ``season_number`` is
    None on the request so the whole release passes through."""
    from riplex.models import PlannedDisc, PlannedMovie

    async def _fake_pick_match(request, provider):
        return SimpleNamespace(
            title="Batman Begins", year=2005, media_type="movie",
            source_id="movie:272",
        )

    async def _fake_plan_movie(match, provider, request):
        return PlannedMovie(
            canonical_title="Batman Begins", year=2005,
            runtime="2h20m", runtime_seconds=8400,
        )

    async def _fake_fetch_film(self, title, disc_format=None, year=None):
        return SimpleNamespace(
            releases=[SimpleNamespace(name="R1", discs=[])],
            film_id=1, title="Batman Begins",
        )

    def _fake_select_release(film, disc_info=None, preferred=None):
        return [PlannedDisc(number=1, disc_format="Blu-ray")], "R1"

    monkeypatch.setattr("riplex.lookup.pick_match", _fake_pick_match)
    monkeypatch.setattr("riplex.lookup._plan_movie", _fake_plan_movie)
    monkeypatch.setattr("riplex.disc.provider.DiscProvider.fetch_film", _fake_fetch_film)
    monkeypatch.setattr("riplex.lookup.select_dvdcompare_release", _fake_select_release)

    result = await lookup_metadata(
        SearchRequest(title="Batman Begins", media_type="movie"),
        _StubProvider(),
    )

    assert len(result.discs) == 1
    assert result.season_number is None


