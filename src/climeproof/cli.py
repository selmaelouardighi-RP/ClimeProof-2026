"""Command-line interface:  climeproof --help"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from .catalog import HAZARDS_BY_ID, METRICS
from .config import load_settings
from .geocode import geocode_one
from .http import CachedHttp
from .inputs import build_locations, read_rows
from .pipeline import run, write_outputs
from .schema import Location, Status

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="ClimeProof hazard-exposure pipeline (public data only).",
)

ConfigOpt = Annotated[Path | None, typer.Option("--config", help="Path to pipeline.toml")]
OfflineOpt = Annotated[bool, typer.Option("--offline", help="Use cached raw responses only")]
RefreshOpt = Annotated[bool, typer.Option("--refresh", help="Ignore cache and refetch everything")]


def _setup(
    config: Path | None, offline: bool = False, refresh: bool = False, verbose: bool = False
):
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    settings = load_settings(config)
    http = CachedHttp(
        settings.pipeline.cache_dir,
        settings.pipeline.user_agent,
        settings.pipeline.http_timeout_s,
        offline=offline,
        refresh=refresh,
    )
    return settings, http


def _point(settings, http, address: str | None, lat: float | None, lon: float | None) -> Location:
    if address:
        return geocode_one(http, settings.geocoder, "query", address)
    if lat is None or lon is None:
        raise typer.BadParameter("give an ADDRESS or both --lat and --lon")
    return Location(id="query", latitude=lat, longitude=lon)


@app.command()
def profile(
    address: Annotated[str | None, typer.Argument(help="One-line U.S. address")] = None,
    lat: Annotated[float | None, typer.Option(help="Latitude (instead of address)")] = None,
    lon: Annotated[float | None, typer.Option(help="Longitude (instead of address)")] = None,
    out: Annotated[
        Path | None, typer.Option(help="Write JSON record here instead of stdout")
    ] = None,
    config: ConfigOpt = None,
    offline: OfflineOpt = False,
    refresh: RefreshOpt = False,
    verbose: Annotated[bool, typer.Option("-v")] = False,
) -> None:
    """Hazard profile for ONE location, printed as JSON."""
    settings, http = _setup(config, offline, refresh, verbose)
    record = run([_point(settings, http, address, lat, lon)], settings, http)[0]
    text = record.model_dump_json(indent=2)
    if out:
        out.write_text(text, encoding="utf-8")
        typer.echo(f"wrote {out}")
    else:
        typer.echo(text)


@app.command()
def batch(
    input_csv: Annotated[Path, typer.Argument(help="CSV with id + coordinates or address columns")],
    out_dir: Annotated[
        Path | None, typer.Option(help="Output folder (default outputs/<timestamp>)")
    ] = None,
    config: ConfigOpt = None,
    offline: OfflineOpt = False,
    refresh: RefreshOpt = False,
    verbose: Annotated[bool, typer.Option("-v")] = False,
) -> None:
    """Hazard profiles for every row of a bulk public input CSV."""
    settings, http = _setup(config, offline, refresh, verbose)
    locations, failures = build_locations(read_rows(input_csv), settings, http)
    records = run(locations, settings, http)
    out_dir = out_dir or Path("outputs") / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    paths = write_outputs(records, out_dir)
    if failures:
        (out_dir / "unplaced.csv").write_text(
            "id,reason\n" + "".join(f"{k},{v}\n" for k, v in failures.items()), encoding="utf-8"
        )
    counts: dict[str, int] = {}
    for r in records:
        for mv in r.metrics.values():
            counts[mv.status.value] = counts.get(mv.status.value, 0) + 1
    typer.echo(f"{len(records)} record(s), {len(failures)} unplaced -> {out_dir}")
    per = settings.periods
    typer.echo(
        f"data windows: recent {per.recent_label}, trend {per.trend_label}, "
        f"records through {per.records_end}"
    )
    typer.echo("status counts: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    for p in paths.values():
        typer.echo(f"  {p}")


@app.command()
def catalog(
    implemented: Annotated[bool, typer.Option(help="Only metrics with a provider")] = False,
) -> None:
    """List every metric in the output schema and which provider fills it."""
    for m in METRICS:
        if implemented and not m.provider:
            continue
        hz = HAZARDS_BY_ID[m.hazard]
        typer.echo(
            f"{hz.layer}  {m.id:<52} {m.unit or '-':<20} {m.provider or Status.NOT_IMPLEMENTED}"
        )


@app.command()
def compare(
    address: Annotated[str | None, typer.Argument()] = None,
    lat: Annotated[float | None, typer.Option()] = None,
    lon: Annotated[float | None, typer.Option()] = None,
    config: ConfigOpt = None,
    offline: OfflineOpt = False,
) -> None:
    """Cross-check days >= 90/100/105F across Normals, ACIS grids and Daymet at one point."""
    from .compare import THRESHOLDS, compare_heat_days

    settings, http = _setup(config, offline)
    loc = _point(settings, http, address, lat, lon)
    typer.echo(f"{'source':<38} {'detail':<28} " + " ".join(f">={t}F".rjust(8) for t in THRESHOLDS))
    for row in compare_heat_days(loc, settings, http):
        cells = " ".join(
            ("-" if row.get(t) is None else f"{row[t]:.1f}").rjust(8) for t in THRESHOLDS
        )
        typer.echo(f"{row['source']:<38} {str(row['detail'])[:28]:<28} {cells}")


if __name__ == "__main__":
    app()
