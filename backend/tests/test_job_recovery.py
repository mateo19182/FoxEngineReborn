"""Tests for job recovery helpers."""

from foxengine.services.job_recovery import FOX_BACKGROUND_JOB_TYPES, TASK_NAME_BY_JOB_TYPE


def test_background_job_types_have_procrastinate_tasks() -> None:
    assert set(TASK_NAME_BY_JOB_TYPE) == set(FOX_BACKGROUND_JOB_TYPES)
    assert TASK_NAME_BY_JOB_TYPE["ingest_file"] == "foxengine_ingest_file"
    assert TASK_NAME_BY_JOB_TYPE["batch_purge"] == "foxengine_purge_batch"
