import copy

import pytest
from conftest import A1, A2, A3, D1, D2, S1, U1

from immich_album_relay.api import RelayError
from immich_album_relay.relay import Relay


def test_multi_user_album_destination_idempotency(config, fake):
    relay = Relay(config, client_factory=fake.client)
    original_sources = copy.deepcopy({k: v for k, v in fake.albums.items() if k in [S1]})
    report = relay.execute(config.jobs[0])
    assert report.ok
    assert report.added == 6
    assert set(fake.albums[D1]) == {A1, A2, A3}
    assert set(fake.albums[D2]) == {A1, A2, A3}
    assert fake.albums[D1][A1]["ownerId"] == U1
    assert fake.albums[S1] == original_sources[S1]
    assert any(row.skipped for row in report.rows)
    assert all((ref == "sam") == (A2 in ids) for ref, _, ids in fake.calls)
    count = len(fake.calls)
    again = relay.execute(config.jobs[0])
    assert again.ok and again.added == 0
    assert len(fake.calls) == count


def test_dry_run_never_writes(config, fake):
    report = Relay(config, client_factory=fake.client).execute(config.jobs[0], dry_run=True)
    assert report.ok and report.status == "dry-run"
    assert sum(row.would_add for row in report.rows) == 6
    assert not fake.calls and not fake.albums[D1]


def test_missing_permission_continues_destination(config, fake):
    fake.denied.add(("sam", D1))
    report = Relay(config, client_factory=fake.client).execute(config.jobs[0])
    assert not report.ok
    assert report.added == 5
    assert A2 not in fake.albums[D1] and A2 in fake.albums[D2]
    assert "permissions" in " ".join(report.errors)


def test_invalid_key_continues_other_users(config, fake):
    fake.bad_keys.add("sam")
    report = Relay(config, client_factory=fake.client).execute(config.jobs[0])
    assert not report.ok and report.added == 4


def test_missing_source_continues(config, fake):
    del fake.albums[S1]
    report = Relay(config, client_factory=fake.client).execute(config.jobs[0])
    assert not report.ok and report.added == 4


@pytest.mark.parametrize("failure", ["no_permission", "not_found", "unknown", "validation"])
def test_partial_batch_failures(config, fake, failure):
    fake.partial[A3] = failure
    report = Relay(config, client_factory=fake.client).execute(config.jobs[0])
    assert not report.ok
    assert sum(row.failed for row in report.rows) == 2
    assert report.added == 4


def test_missing_batch_result_is_failure(config, fake):
    fake.missing_results.add(A3)
    report = Relay(config, client_factory=fake.client).execute(config.jobs[0])
    assert not report.ok and sum(r.failed for r in report.rows) == 2


def test_network_batch_failure_continues(config, fake):
    fake.failures.add(("alex", D1))
    report = Relay(config, client_factory=fake.client).execute(config.jobs[0])
    assert not report.ok
    assert A2 in fake.albums[D1] and set(fake.albums[D2]) == {A1, A2, A3}


def test_removing_source_never_removes_destination(config, fake):
    relay = Relay(config, client_factory=fake.client)
    relay.execute(config.jobs[0])
    fake.albums[S1].clear()
    relay.execute(config.jobs[0])
    assert set(fake.albums[D1]) == {A1, A2, A3}


def test_multiple_jobs_and_selection(config, fake):
    job2 = config.jobs[0].model_copy(deep=True)
    job2.id = "second"
    config.jobs.append(job2)
    relay = Relay(config, client_factory=fake.client)
    assert len(relay.selected()) == 2
    assert relay.selected("second") == [job2]
    assert all(relay.execute(job).ok for job in relay.selected())
    with pytest.raises(RelayError, match="Unknown"):
        relay.selected("missing")
    job2.enabled = False
    with pytest.raises(RelayError, match="disabled"):
        relay.selected("second")


def test_validate_is_read_only(config, fake):
    Relay(config, client_factory=fake.client).validate()
    assert not fake.calls


def test_large_album_batching(config, fake):
    config.http.batch_size = 100
    fake.albums[S1] = {f"asset-{i}": {"id": f"asset-{i}", "ownerId": U1} for i in range(2501)}
    report = Relay(config, client_factory=fake.client).execute(config.jobs[0])
    assert report.ok
    assert max(len(ids) for _, _, ids in fake.calls) <= 100
    assert len(fake.albums[D1]) == 2503
