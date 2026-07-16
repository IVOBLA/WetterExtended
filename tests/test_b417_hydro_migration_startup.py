import hydro_flood_ml as h

def test_startup_entrypoint_exists(): assert callable(h.run_hydro_startup_migrations)
