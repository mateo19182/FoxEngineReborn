"""Tests for job recovery mappings."""

from foxengine.services.job_recovery import FOX_BACKGROUND_JOB_TYPES, TASK_NAME_BY_JOB_TYPE


def test_task_name_mapping_covers_background_job_types() -> None:
    assert TASK_NAME_BY_JOB_TYPE["ingest_file"] == "foxengine_ingest_file"
    assert TASK_NAME_BY_JOB_TYPE["export"] == "foxengine_export"
    assert TASK_NAME_BY_JOB_TYPE["bulk_tag"] == "foxengine_bulk_tag"
    assert set(TASK_NAME_BY_JOB_TYPE) == set(FOX_BACKGROUND_JOB_TYPES)
