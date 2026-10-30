from apps.core.statuses import guess_state


def test_imported_done_statuses_count_as_completed():
    assert guess_state("Completed") == ("completed", "success")
    assert guess_state("Done")[0] == "completed"
    assert guess_state("Not completed")[0] == "open"
    assert guess_state("Rejected")[0] == "closed"
    assert guess_state("Waiting on client")[0] == "open"
