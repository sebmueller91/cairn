def test_scheduler_configures_both_jobs_without_starting():
    from app.scheduler import create_scheduler

    scheduler = create_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {"price_fetch", "snapshot_rebuild"}
    assert not scheduler.running
